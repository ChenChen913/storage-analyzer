#!/usr/bin/env python3
r"""Serve the storage report with a guarded delete API (Windows + macOS).

Starts on 127.0.0.1 + a random port + a random per-session token, serves the
interactive report, and exposes POST /action to move green-tier paths to the
Recycle Bin / Trash or delete them outright. Stop with Ctrl+C.

Usage:
    Windows: python scripts\\server.py %TEMP%\\analysis.json
             python scripts\\server.py %TEMP%\\analysis.json --allow-rm
    macOS:   python3 scripts/server.py /tmp/analysis.json

SAFETY MODEL — read before changing:
- Allowlist: only paths listed in this report's green items `trash_paths` are
  accepted for rm/trash. Every request path is realpath-resolved and must be in
  the allowlist AND under an allowed root (default: $HOME + Program Files).
- Permanent delete is OFF by default. `--allow-rm` must be passed explicitly;
  without it the server rejects mode=rm and the report hides delete buttons.
- Sensitive paths (home root, drive roots, AppData, Documents/Desktop/Downloads,
  Program Files roots, Windows/System32, ...) are rejected even if they somehow
  appear in the allowlist.
- Junctions / symlinks are deleted as a link only; the target is never recursed.
- Bound to 127.0.0.1 only; every POST requires the session token; Host header
  must be 127.0.0.1 (blocks DNS-rebinding from a malicious page).
- Every action is appended to state/audit.jsonl (path, mode, result, time).
- Windows: Recycle Bin uses SHFileOperationW with FOF_ALLOWUNDO; the result is
  verified (return code, fAnyOperationsAborted, source path gone).
"""
import argparse
import json
import os
import secrets
import shutil
import stat
import string
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from report_util import json_for_script
import statefile

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "assets", "report_template.html")
STATE_DIR = os.environ.get("STORAGE_ANALYZER_STATE") or os.path.join(HERE, "..", "state")
AUDIT_FILE = os.path.join(STATE_DIR, "audit.jsonl")
HOME = os.path.realpath(os.path.expanduser("~"))
TOKEN = secrets.token_urlsafe(24)

DATA = {}
TPL = ""
RM_ALLOW = set()
TRASH_ALLOW = set()
OPEN_ALLOW = set()
ALLOW_RM = False
ROOTS = [HOME]


def expand(p):
    return os.path.realpath(os.path.expanduser(p))


def _norm(p):
    return os.path.normcase(os.path.realpath(p))


def is_reparse_point(path):
    """Windows junction / 符号链接返回 True；macOS 的符号链接同样返回 True。"""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    attrs = getattr(st, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & flag) or os.path.islink(path)


def remove_link(path):
    """只删除链接本身。Windows 的目录 junction 用 rmdir，文件链接用 unlink。"""
    if sys.platform.startswith("win") and os.path.isdir(path):
        os.rmdir(path)
    else:
        os.unlink(path)


def hard_delete(path):
    if is_reparse_point(path):
        remove_link(path)
        return
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def sensitive_paths():
    """破坏性操作的黑名单：即使误入白名单也不允许删除。"""
    out = {_norm(HOME)}
    if sys.platform.startswith("win"):
        for rel in ("AppData", os.path.join("AppData", "Local"),
                    os.path.join("AppData", "Roaming"),
                    os.path.join("AppData", "LocalLow"),
                    "Desktop", "Documents", "Downloads", "Pictures", "Videos",
                    "Music", "OneDrive", "Saved Games", "Favorites", "Links",
                    "Searches", "Contacts"):
            out.add(_norm(os.path.join(HOME, rel)))
        for env in ("USERPROFILE", "PUBLIC", "ProgramData", "ProgramFiles",
                    "ProgramFiles(x86)", "SystemRoot", "windir", "TEMP", "TMP"):
            v = os.environ.get(env)
            if v:
                out.add(_norm(v))
        for letter in string.ascii_uppercase:
            root = letter + ":\\"
            if os.path.exists(root):
                out.add(_norm(root))
        windows = os.environ.get("SystemRoot") or r"C:\Windows"
        for rel in ("", "System32", "SysWOW64", "WinSxS",
                    "System Volume Information"):
            out.add(_norm(os.path.join(windows, rel)))
        out.add(_norm(r"C:\Users"))
        out.add(_norm(r"C:\Program Files\WindowsApps"))
    else:
        for rel in ("Desktop", "Documents", "Downloads", "Pictures", "Movies",
                    "Music", "Library", "Applications", ".Trash"):
            out.add(_norm(os.path.join(HOME, rel)))
        for p in ("/", "/System", "/Users", "/Library", "/Applications"):
            out.add(_norm(p))
    return out


def validate_target(rp, allow, mode, roots=None):
    """返回 None 表示允许，否则返回拒绝原因。rp 必须是 realpath 结果。"""
    roots = ROOTS if roots is None else roots
    if rp not in allow:
        return "路径不在白名单"
    rp_c = os.path.normcase(rp)
    bases = [os.path.normcase(b) for b in roots]
    if not any(rp_c == b or rp_c.startswith(b + os.sep) for b in bases):
        return "路径越界"
    if mode in ("rm", "trash") and _norm(rp) in sensitive_paths():
        return "拒绝操作敏感目录"
    return None


def audit(entry):
    """追加一条操作记录；审计失败不影响主流程，但会打印到 stderr。

    多个浏览器标签可能并发提交，追加写必须持锁，否则 jsonl 会出现半行。
    """
    entry = dict(entry)
    entry["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with statefile.locked(AUDIT_FILE):
            with open(AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except (OSError, TimeoutError) as e:
        print("审计日志写入失败：%s" % e, file=sys.stderr)


def load(src):
    with open(src, encoding="utf-8") as f:
        data = json.load(f)
    try:
        import history
        stats = history.annotate(data)
        print(f"增量标注: 新发现 {stats['new']} | 删后复发 {stats['resurrected']} "
              f"| 活跃度 {stats['activity']} | 档案命中 {stats['known']}")
    except Exception as e:
        print(f"增量标注跳过: {e}", file=sys.stderr)
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    # 三套白名单，权限从严到宽：
    #   rm    = 仅绿灯 trash_paths（可直接删的纯缓存）
    #   trash = 绿灯 + 黄灯 trash_paths（黄灯只准移回收站/废纸篓，不准直接删）
    #   open  = trash 全集 + 黄灯 path + 红灯 app_paths（仅"在文件管理器打开"）
    rm_allow, trash_allow, open_allow = set(), set(), set()
    for it in data.get("green", []):
        for p in (it.get("trash_paths") or []):
            rp = expand(p)
            rm_allow.add(rp)
            trash_allow.add(rp)
            open_allow.add(rp)
    for it in data.get("yellow", []):
        for p in (it.get("trash_paths") or []):
            rp = expand(p)
            trash_allow.add(rp)
            open_allow.add(rp)
        if it.get("path"):
            rp = expand(it["path"])
            if os.path.exists(rp):
                open_allow.add(rp)
    # 红灯只允许"打开"（应用本体在 /Applications，删除让用户在访达里自己卸）
    for it in data.get("red", []):
        for p in (it.get("app_paths") or []):
            rp = expand(p)
            if os.path.exists(rp):
                open_allow.add(rp)
    return data, tpl, rm_allow, trash_allow, open_allow


def move_to_trash(path):
    if sys.platform == "darwin":
        _trash_macos(path)
    elif sys.platform.startswith("win"):
        _trash_windows(path)
    else:
        raise OSError("移到废纸篓仅支持 macOS / Windows")
    if os.path.exists(path):
        raise OSError("移到回收站后源路径仍然存在")


def _trash_macos(path):
    # osascript Finder delete -> macOS Trash, recoverable. First run may prompt
    # for Finder automation permission. Fall back to ~/.Trash move if it fails.
    script = 'tell application "Finder" to delete (POSIX file %s as alias)' % json.dumps(path)
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        dest = os.path.join(HOME, ".Trash",
                            os.path.basename(path.rstrip("/")) + "." + time.strftime("%H%M%S"))
        shutil.move(path, dest)


def _trash_windows(path):
    # Send to Recycle Bin via SHFileOperationW with FOF_ALLOWUNDO (stdlib ctypes).
    # FOF_NOCONFIRMATION + FOF_SILENT + FOF_NOERRORUI keeps it headless.
    # Never falls back to a permanent delete when the Recycle Bin is unavailable.
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    FO_DELETE = 3
    FOF_ALLOWUNDO = 0x0040
    FOF_NOCONFIRMATION = 0x0010
    FOF_SILENT = 0x0004
    FOF_NOERRORUI = 0x0400
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = os.path.abspath(path) + "\x00\x00"  # double-null terminated list
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0:
        raise OSError("SHFileOperation failed (code %d)" % rc)
    if op.fAnyOperationsAborted:
        raise OSError("回收站操作被系统取消")


def open_in_file_manager(path):
    # 非破坏性：在访达 / 资源管理器里打开该位置，方便用户自己审查删除
    target = path if os.path.isdir(path) else os.path.dirname(path)
    if sys.platform == "darwin":
        # .app 是 bundle，对它用 open 会"启动应用"而非显示；必须用 open -R 在访达里选中。
        if target.rstrip("/").endswith(".app"):
            r = subprocess.run(["open", "-R", target], capture_output=True, text=True)
            if r.returncode != 0:
                raise OSError((r.stderr or "open -R 失败").strip())
            return
        # 普通文件夹：先试直接打开看内容；沙盒容器（如微信）open 会报 -10814，
        # 退回 open -R 在父目录里选中它。两者都失败才算错。
        r = subprocess.run(["open", target], capture_output=True, text=True)
        if r.returncode != 0:
            r2 = subprocess.run(["open", "-R", target], capture_output=True, text=True)
            if r2.returncode != 0:
                raise OSError((r.stderr or r2.stderr or "open 失败").strip())
    elif sys.platform.startswith("win"):
        subprocess.run(["explorer", target])  # explorer 退出码不可靠，不据此判成败
    else:
        raise OSError("打开文件夹仅支持 macOS / Windows")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            blob = json_for_script(DATA)
            cfg = json.dumps({"token": TOKEN, "endpoint": "/action",
                              "allow_rm": ALLOW_RM})
            html = TPL.replace("__REPORT_DATA__", blob).replace("__DELETE_CONFIG__", cfg)
            self._send(200, html, "text/html; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        if self.path != "/action":
            self._send(404, json.dumps({"ok": False, "error": "not found"}))
            return
        # DNS-rebinding guard: only accept local Host
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            self._send(403, json.dumps({"ok": False, "error": "host 不被允许"}))
            return
        n = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            self._send(400, json.dumps({"ok": False, "error": "请求格式错误"}))
            return
        token = req.get("token")
        if not isinstance(token, str) or not secrets.compare_digest(token, TOKEN):
            self._send(403, json.dumps({"ok": False, "error": "token 校验失败"}))
            return
        mode = req.get("mode")
        allow = {"rm": RM_ALLOW, "trash": TRASH_ALLOW, "open": OPEN_ALLOW}.get(mode)
        if allow is None:
            self._send(400, json.dumps({"ok": False, "error": "未知操作"}))
            return
        if mode == "rm" and not ALLOW_RM:
            self._send(403, json.dumps({
                "ok": False,
                "error": "永久删除未启用：启动服务时加 --allow-rm 才会开放",
            }, ensure_ascii=False))
            return
        paths = req.get("paths") or []
        if (not isinstance(paths, list) or not paths
                or not all(isinstance(p, str) for p in paths)):
            self._send(400, json.dumps({"ok": False, "error": "paths 必须是非空字符串数组"},
                                       ensure_ascii=False))
            return
        if len(paths) > 5000:
            self._send(400, json.dumps({"ok": False, "error": "单次路径数量过多"},
                                       ensure_ascii=False))
            return

        # 先整体校验，再执行：任何一条不合法都不会造成半批删除。
        prepared = []
        for p in paths:
            rp = expand(p)
            raw = os.path.abspath(os.path.expanduser(p))
            err = validate_target(rp, allow, mode)
            if err is None and is_reparse_point(raw):
                # 链接本身也必须在白名单/根目录内，但执行时只删链接
                err = validate_target(expand(raw), allow, mode)
            if err:
                audit({"mode": mode, "path": p, "ok": False,
                       "status": "rejected", "error": err})
                self._send(403, json.dumps({"ok": False, "error": "%s：%s" % (err, p)},
                                           ensure_ascii=False))
                return
            prepared.append((p, rp, raw))

        results = []
        for p, rp, raw in prepared:
            target = raw if is_reparse_point(raw) else rp
            if mode in ("rm", "trash") and not os.path.exists(raw):
                results.append({"path": p, "ok": True, "status": "missing"})
                audit({"mode": mode, "path": p, "ok": True, "status": "missing"})
                continue
            try:
                if mode == "open":
                    open_in_file_manager(target)
                    status = "opened"
                elif mode == "trash":
                    move_to_trash(target)
                    status = "trashed"
                else:
                    hard_delete(target)
                    status = "deleted"
                if mode in ("rm", "trash") and os.path.exists(raw):
                    raise OSError("操作后源路径仍然存在")
                results.append({"path": p, "ok": True, "status": status})
                audit({"mode": mode, "path": p, "ok": True, "status": status})
            except Exception as e:
                results.append({"path": p, "ok": False, "status": "failed",
                                "error": str(e)})
                audit({"mode": mode, "path": p, "ok": False,
                       "status": "failed", "error": str(e)})

        failed = [r for r in results if not r["ok"]]
        # 批量汇总单独记一条，便于聊天记录之外的复盘：谁在什么时候动了多少路径
        audit({"mode": mode, "action": "batch",
               "risk": {"rm": "high", "trash": "medium", "open": "none"}[mode],
               "count": len(results), "ok_count": len(results) - len(failed),
               "failed": len(failed),
               "failed_paths": [r["path"] for r in failed]})
        self._send(200, json.dumps({
            "ok": not failed,
            "done": [r["path"] for r in results if r["ok"]],
            "failed": len(failed),
            "results": results,
        }, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="存储分析报告服务")
    ap.add_argument("src", help="analysis JSON")
    ap.add_argument("--allow-rm", action="store_true", help="启用永久删除（默认关闭）")
    ap.add_argument("--allow-root", action="append", default=[], metavar="PATH",
                    help="额外允许的根目录，可重复；用于放行非 HOME 盘的绿灯项")
    ap.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    ap.add_argument("--port", type=int, default=0, help="监听端口，默认随机")
    args = ap.parse_args()

    global DATA, TPL, RM_ALLOW, TRASH_ALLOW, OPEN_ALLOW, ALLOW_RM, ROOTS
    DATA, TPL, RM_ALLOW, TRASH_ALLOW, OPEN_ALLOW = load(args.src)
    ALLOW_RM = args.allow_rm
    roots = [HOME]
    if sys.platform.startswith("win"):
        roots.append(os.environ.get("ProgramFiles", r"C:\Program Files"))
        roots.append(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    else:
        roots.append("/Applications")
    for p in args.allow_root:
        rp = os.path.realpath(os.path.expanduser(p))
        if not os.path.isdir(rp):
            print("警告：--allow-root 不是有效目录，已忽略：%s" % p, file=sys.stderr)
            continue
        roots.append(rp)
    ROOTS = list(dict.fromkeys(roots))

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    port = srv.server_address[1]
    url = "http://127.0.0.1:%d/" % port
    trash_word = "回收站" if sys.platform.startswith("win") else "废纸篓"
    print("报告服务已启动：" + url)
    print("绿灯可删 %d 项 | 黄灯可移%s/打开文件夹 %d 项 | 页面上点"
          % (len(RM_ALLOW), trash_word, len(TRASH_ALLOW) - len(RM_ALLOW)))
    if ALLOW_RM:
        print("永久删除：已启用（--allow-rm）。不可恢复，请逐项确认。")
    else:
        print("永久删除：未启用（默认）。网页只提供移到%s。" % trash_word)
    print("允许的根目录：" + " | ".join(ROOTS))
    print("用完按 Ctrl+C 停止服务（服务关掉后按钮即失效）")
    sys.stdout.flush()
    if not args.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止服务。")


if __name__ == "__main__":
    main()
