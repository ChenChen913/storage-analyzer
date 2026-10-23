#!/usr/bin/env python3
"""Read-only storage scanner (macOS + Windows).

Collects disk usage, system info, and per-directory size breakdowns for the
hot spots that typically eat disk, and emits one JSON blob to stdout for Claude
to interpret and classify. Auto-detects the OS and scans the right locations.

STRICTLY READ-ONLY: only sizes/lists/reads metadata. Never creates, moves, or
deletes anything.

Output shape (same on both OSes):
{
  "generated_at", "scan_seconds",
  "system": {os, build, arch, user, home, filesystem,
             disk_total, disk_used, disk_free, purgeable,
             disks: [{name, total, used, free}]},   # all volumes/drives
  "groups": { "<group>": [{name, path, size_kb, size_h}], ... },
  "coverage": {method, drives, files_scanned, es_path, wiztree_path, ...},
  "temp_artifacts": {dir, files: [{path, size_kb, size_h}], total_kb, total_h, rule}
}
"""
import json
import os
import shutil
import sys
import time
import csv

HOME = os.path.expanduser("~")


def human(kb):
    """KB number -> human string like '12.3 GB'."""
    n = float(kb) * 1024
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit not in ("B", "KB") else f"{int(n)} {unit}"
        n /= 1024


# ======================================================================
# macOS
# ======================================================================
import re
import subprocess


def run(cmd, timeout=180):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def du_children(path, min_kb=51200, limit=40):
    """Size every immediate child of `path` via du, sorted desc. macOS."""
    if not os.path.isdir(path):
        return []
    results = []
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return [{"name": "(permission denied)", "path": path,
                 "size_kb": 0, "size_h": "?", "denied": True}]
    for name in entries:
        if name in (".", ".."):
            continue
        child = os.path.join(path, name)
        if os.path.islink(child):
            continue
        out = run(["du", "-sk", child], timeout=120)
        m = re.match(r"\s*(\d+)", out)
        if not m:
            continue
        kb = int(m.group(1))
        if kb < min_kb:
            continue
        results.append({"name": name, "path": child, "size_kb": kb, "size_h": human(kb)})
    results.sort(key=lambda r: r["size_kb"], reverse=True)
    return results[:limit]


MAC_TARGETS = [
    ("home", HOME, 102400),
    ("library", os.path.join(HOME, "Library"), 51200),
    ("caches", os.path.join(HOME, "Library/Caches"), 51200),
    ("containers", os.path.join(HOME, "Library/Containers"), 51200),
    ("group_containers", os.path.join(HOME, "Library/Group Containers"), 51200),
    ("app_support", os.path.join(HOME, "Library/Application Support"), 51200),
    ("applications", "/Applications", 102400),
    ("downloads", os.path.join(HOME, "Downloads"), 51200),
    ("dev_caches", None, 51200),
]

MAC_DEV_CACHE_PATHS = [
    "~/Library/Caches/pip", "~/Library/Caches/uv", "~/.cache", "~/.cargo",
    "~/.npm", "~/.pnpm-store", "~/.gradle", "~/.m2",
    "~/Library/Developer/Xcode/DerivedData", "~/Library/Developer/CoreSimulator",
    "~/Library/Developer/Xcode/iOS DeviceSupport", "~/Library/pnpm",
    "~/go/pkg", "~/.docker",
]


def dev_caches_macos():
    results = []
    for p in MAC_DEV_CACHE_PATHS:
        path = os.path.expanduser(p)
        if not os.path.isdir(path):
            continue
        out = run(["du", "-sk", path], timeout=180)
        m = re.match(r"\s*(\d+)", out)
        if not m:
            continue
        kb = int(m.group(1))
        if kb < 51200:
            continue
        results.append({"name": os.path.basename(path.rstrip("/")) or path,
                        "path": path, "size_kb": kb, "size_h": human(kb)})
    results.sort(key=lambda r: r["size_kb"], reverse=True)
    return results


def system_info_macos():
    info = {}
    info["os"] = "macOS " + run(["sw_vers", "-productVersion"]).strip()
    info["build"] = run(["sw_vers", "-buildVersion"]).strip()
    arch = run(["uname", "-m"]).strip()
    brand = run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
    info["arch"] = (f"Apple Silicon (arm64){' / ' + brand if brand else ''}"
                    if arch == "arm64" else f"{arch}{' / ' + brand if brand else ''}")
    info["user"] = os.environ.get("USER", "") or run(["whoami"]).strip()
    info["home"] = HOME
    total, used, free = "?", "?", "?"
    try:
        t, u, f = shutil.disk_usage("/")
        total, used, free = human(t // 1024), human(u // 1024), human(f // 1024)
    except Exception:
        pass
    info["disk_total"], info["disk_used"], info["disk_free"] = total, used, free
    dinfo = run(["diskutil", "info", "/"])
    fs = re.search(r"File System Personality:\s*(.+)", dinfo)
    info["filesystem"] = fs.group(1).strip() if fs else "APFS"
    pm = re.search(r"Purgeable Space:\s*([\d.,]+ \w+)", dinfo)
    info["purgeable"] = pm.group(1).strip() if pm else ""
    info["disk_name"] = "Macintosh HD"
    info["disks"] = [{"name": "Macintosh HD", "total": total, "used": used, "free": free}]
    return info


def scan_macos():
    system = system_info_macos()
    groups = {}
    for key, path, floor in MAC_TARGETS:
        groups[key] = dev_caches_macos() if key == "dev_caches" else du_children(path, min_kb=floor)
    return system, groups


# ======================================================================
# Windows
# ======================================================================
# 数据源策略（v2 升级）：
#   1. Everything (es.exe) 优先 —— 秒级导出全盘清单，多维聚合基于同一份 CSV，
#      零重复扫描；这是"全盘覆盖 + 反复多维度分析"的首选（实测 350 万文件
#      导出 5-6 秒/盘，聚合约 1 分钟/盘）。
#   2. WizTree (wiztree64.exe) 次选 —— 读取 MFT 导出文件清单，速度接近
#      Everything，且不需要常驻服务；没有 Everything 时的最佳替代。
#   3. 回退 os.scandir 全盘遍历 —— 两个工具都不可用时保证"全盘覆盖"而非固定目标列表。
# 三者输出都归一成 '"路径",大小' 两列 CSV，后续聚合完全一致。
# 所有聚合输出统一为 groups: {name,path,size_kb,size_h}，与 macOS 输出一致。
# ======================================================================
import re as _re
import string
import subprocess as _sp
import tempfile as _tf

# ---- Everything 探测 ----
ES_CANDIDATES = [
    "es.exe",  # PATH
    r"D:\Everything\es.exe",
    r"C:\Everything\es.exe",
    r"C:\Program Files\Everything\es.exe",
    r"C:\Program Files (x86)\Everything\es.exe",
]


def find_es():
    la = os.environ.get("LOCALAPPDATA", "")
    cands = list(ES_CANDIDATES)
    if la:
        cands.append(os.path.join(la, "Everything", "es.exe"))
    for c in cands:
        if os.path.sep in c:
            if os.path.isfile(c):
                return c
        else:
            p = shutil.which(c)
            if p:
                return p
    return None


def _csv_rows(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def es_export_csv(es, drive, out_csv, timeout=1200):
    """Everything 导出某盘全部文件清单（路径+大小）。让 es 自己写文件，规避
    PowerShell 重定向 UTF-16 与命令行超长问题。

    导出前后各跑一次同一查询：先取 -get-result-count，再导出并核对行数。
    索引过期、排除项或 IPC 半失败时，文件可能"非空但严重不全"；只看返回码
    会把这种结果当成功，后续总账永远对不平。行数不足 98% 即判失败并删掉
    半成品，交给下一个数据源。"""
    query = [es, "-path", drive, "/a-d",
             "-full-path-and-name", "-size", "-no-digit-grouping"]
    expected = None
    try:
        r = _sp.run(query + ["-get-result-count"],
                    capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            lines = [x.strip() for x in r.stdout.splitlines() if x.strip()]
            if lines:
                try:
                    expected = int(lines[-1].replace(",", ""))
                except ValueError:
                    expected = None
        r = _sp.run(query + ["-export-csv", out_csv, "-no-header"],
                    capture_output=True, text=True, timeout=timeout)
        if (r.returncode != 0 or not os.path.exists(out_csv)
                or os.path.getsize(out_csv) == 0):
            return {"ok": False, "expected": expected, "actual": 0,
                    "error": "es.exe 导出失败或输出为空"}
        actual = _csv_rows(out_csv)
        if expected and actual < expected * 0.98:
            try:
                os.remove(out_csv)
            except OSError:
                pass
            return {"ok": False, "expected": expected, "actual": actual,
                    "error": "导出行数 %d 明显少于索引计数 %d" % (actual, expected)}
        return {"ok": True, "expected": expected, "actual": actual, "error": ""}
    except Exception as e:
        return {"ok": False, "expected": expected, "actual": 0, "error": str(e)}


# ---- WizTree 探测（Everything 之外的第二数据源）----
WIZTREE_CANDIDATES = [
    "wiztree64.exe",  # PATH
    r"C:\Program Files\WizTree\WizTree64.exe",
    r"C:\Program Files (x86)\WizTree\WizTree64.exe",
    r"D:\WizTree\WizTree64.exe",
    r"D:\Program Files\WizTree\WizTree64.exe",
]
WIZTREE_ENV = "STORAGE_ANALYZER_WIZTREE"


def find_wiztree():
    env = os.environ.get(WIZTREE_ENV, "")
    if env and os.path.isfile(env):
        return env
    la = os.environ.get("LOCALAPPDATA", "")
    cands = list(WIZTREE_CANDIDATES)
    if la:
        cands.append(os.path.join(la, "WizTree", "WizTree64.exe"))
        cands.append(os.path.join(la, "Programs", "WizTree", "WizTree64.exe"))
    for c in cands:
        if os.path.sep in c:
            if os.path.isfile(c):
                return c
        else:
            p = shutil.which(c)
            if p:
                return p
    return None


def normalize_wiztree_csv(src, dst):
    """WizTree CSV -> 本项目统一的 '"路径",大小' 两列 CSV。

    WizTree 格式：File Name, Size, Allocated, Modified, Attributes, Files, Folders
    目录行的 Name 以反斜杠结尾且 Size 是子树总量，必须跳过，否则重复计数。
    使用 Size（逻辑大小）而非 Allocated，避免硬链接的 0 前缀干扰。
    """
    ok = False
    try:
        with open(src, encoding="utf-8-sig", errors="replace", newline="") as f, \
                open(dst, "w", encoding="utf-8", newline="") as out:
            rd = csv.reader(f)
            header = next(rd, None)
            if not header:
                return False
            hdr = [h.strip().lower() for h in header]
            try:
                i_name = hdr.index("file name")
                i_size = hdr.index("size")
            except ValueError:
                # 没有表头时按前两列处理
                i_name, i_size = 0, 1
                rd = iter([header] + list(rd))
            for row in rd:
                if len(row) <= max(i_name, i_size):
                    continue
                name = row[i_name]
                if not name or name.endswith("\\") or name.endswith("/"):
                    continue
                raw = row[i_size].replace(",", "").strip()
                try:
                    sz = int(float(raw))
                except ValueError:
                    continue
                if sz < 0:
                    continue
                out.write('"%s",%d\n' % (name, sz))
                ok = True
    except OSError:
        return False
    return ok and os.path.exists(dst) and os.path.getsize(dst) > 0


def wiztree_export_csv(exe, drive, out_csv, timeout=1200, admin=False):
    """WizTree 命令行导出（仅文件行，避免目录行重复计数）。

    admin=False 时用 /admin=0，不弹 UAC，但读不到 WindowsApps 等受保护目录；
    admin=True 需要当前进程已提权，走 MFT 直读，速度快且覆盖完整。
    导出的是 WizTree 原生格式，随后转成本项目统一 CSV。
    """
    raw = out_csv + ".wiz"
    args = [exe, drive, "/export=" + raw,
            "/exportfolders=0", "/exportfiles=1",
            "/admin=" + ("1" if admin else "0")]
    try:
        os.remove(raw)  # 清掉上次崩溃遗留的导出文件，避免把旧数据当新结果
    except OSError:
        pass
    try:
        _sp.run(args, capture_output=True, text=True, timeout=timeout)
    except Exception:
        pass
    ok = False
    if os.path.exists(raw) and os.path.getsize(raw) > 0:
        try:
            ok = normalize_wiztree_csv(raw, out_csv)
        finally:
            try:
                os.remove(raw)
            except OSError:
                pass
    if not ok:
        # 失败时不留半成品，否则 --reuse-csv 会把残缺清单当有效数据
        try:
            os.remove(out_csv)
        except OSError:
            pass
    return ok


# auto 的尝试顺序；显式指定 --source 时只试该数据源，失败即跳过该盘（便于基准测试）
SOURCE_CHAIN = {
    "auto": ("everything", "wiztree", "walk"),
    "everything": ("everything",),
    "wiztree": ("wiztree",),
    "walk": ("walk",),
}


# ---- 行流解析与清洗 ----
def iter_rows(csv_path):
    """流式解析 '"路径",大小' CSV。清洗 2**64-1（Everything 未知大小占位）、
    负值、畸形行。这是全部分析的单一数据源。"""
    with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line:
                continue
            try:
                if line.startswith('"'):
                    idx = line.rfind('",')
                    p = line[1:idx].replace('""', '"')
                    sz = int(line[idx + 2:])
                else:
                    p, sz = line.rsplit(",", 1)
                    sz = int(sz)
                if sz < 0 or sz >= 2 ** 63:
                    sz = 0  # 占位/未知大小，不参与统计
                yield p, sz
            except (ValueError, IndexError):
                continue


# ---- 启发式模式（负面素材库见 references/lessons-learned-windows.md）----
# 缓存目录关键字：更具体的放前面，避免 'cache' 抢匹配 'code cache' 等
CACHE_KEYWORDS = (
    "code cache", "service worker", "cachedextensionvsix", "component_crx",
    "gecko_cache", "gpu cache", "grshader", "gpucache", "blob_storage",
    "cacheddata", "web_cache", "shader", "cache", "dawn", "graphite",
)
UPDATER_KEYWORDS = (
    "auto-updater", "autoupdate", "patch_exec", "upgrade_files",
    "squirrel", "update download", "updates",
)
VERSION_SEG_RE = _re.compile(r"(?:^|\\\\)(?:app-)?\d+(?:\.\d+){1,3}$", _re.I)
INSTALLER_EXTS = (".exe", ".msi", ".msp", ".iso", ".zip", ".7z", ".rar",
                  ".tar.gz", ".tar.xz", ".cab", ".pkg", ".apk", ".appx",
                  ".msix", ".bin", ".img", ".dmg")


def _mkitem(key, sz, note=None):
    it = {"name": os.path.basename(key.rstrip("\\/")) or key, "path": key,
          "size_kb": sz // 1024, "size_h": human(sz // 1024)}
    if note:
        it["note"] = note
    return it


def combined_pass(csv_path, drive, min_dir_mb=10, big_mb=100,
                  cache_mb=30, updater_mb=30, ver_mb=50, top=80):
    """单次遍历同时完成所有维度聚合，避免多次全文件遍历。

    返回 dict: total, count, dir2[], dir3[], big[], installers[],
               cache_dirs[], updater_dirs[], version_dirs[]
    """
    drive_l = drive.lower()
    c2, c3 = {}, {}
    big, inst = [], []
    cache_d, updater_d = {}, {}
    ver_size = {}   # 版本目录 -> 大小
    total = count = 0
    for p, sz in iter_rows(csv_path):
        if not p.lower().startswith(drive_l):
            continue
        total += sz
        count += 1
        rest = p[len(drive):].lstrip("\\")
        parts = rest.split("\\")
        # depth2 / depth3 目录聚合
        k2 = "\\".join(parts[:2]) if len(parts) >= 2 else rest
        c2[k2] = c2.get(k2, 0) + sz
        if len(parts) >= 3:
            k3 = "\\".join(parts[:3])
            c3[k3] = c3.get(k3, 0) + sz
        # 大文件
        if sz >= big_mb * 1024 * 1024:
            big.append(_mkitem(p, sz))
        # 安装包
        low = p.lower()
        if sz >= big_mb * 1024 * 1024 and low.endswith(INSTALLER_EXTS):
            inst.append(_mkitem(p, sz))
        # 缓存 / 更新器目录（按命名模式）
        if sz >= cache_mb * 1024 * 1024:
            for kw in CACHE_KEYWORDS:
                i = low.find(kw)
                if i >= 0:
                    j = p.find("\\", i + len(kw))
                    key = p[:j] if j > 0 else p
                    cache_d[key] = cache_d.get(key, 0) + sz
                    break
            for kw in UPDATER_KEYWORDS:
                i = low.find(kw)
                if i >= 0:
                    j = p.find("\\", i + len(kw))
                    key = p[:j] if j > 0 else p
                    updater_d[key] = updater_d.get(key, 0) + sz
                    break
        # 版本目录（最深匹配段）
        for idx in range(len(parts) - 1, -1, -1):
            if VERSION_SEG_RE.match(parts[idx]):
                d = drive.rstrip("\\") + "\\" + "\\".join(parts[:idx + 1])
                ver_size[d] = ver_size.get(d, 0) + sz
                break
    # 组装目录聚合结果（min 过滤 + 排序）
    def to_items(counter, floor_mb, n):
        items = [_mkitem(os.path.join(drive, k), v)
                 for k, v in counter.items() if v >= floor_mb * 1024 * 1024]
        items.sort(key=lambda r: r["size_kb"], reverse=True)
        return items[:n]
    dir2 = to_items(c2, min_dir_mb, top)
    dir3 = to_items(c3, min_dir_mb, top)
    big.sort(key=lambda r: -r["size_kb"]); big = big[:top]
    inst.sort(key=lambda r: -r["size_kb"]); inst = inst[:top]
    cache_dirs = [_mkitem(k, v) for k, v in cache_d.items() if v >= cache_mb * 1024 * 1024]
    cache_dirs.sort(key=lambda r: -r["size_kb"]); cache_dirs = cache_dirs[:top]
    updater_dirs = [_mkitem(k, v) for k, v in updater_d.items() if v >= updater_mb * 1024 * 1024]
    updater_dirs.sort(key=lambda r: -r["size_kb"]); updater_dirs = updater_dirs[:top]
    # 版本目录：按父目录分组，标注"多版本并存"
    vgroups = {}
    for d, sz in ver_size.items():
        if sz >= ver_mb * 1024 * 1024:
            vgroups.setdefault(os.path.dirname(d), []).append((d, sz))
    version_dirs = []
    for parent, vers in vgroups.items():
        if len(vers) >= 2:
            vers.sort(key=lambda x: -x[1])
            note = "多版本并存: " + " | ".join(
                "%s=%s" % (os.path.basename(v[0]), human(v[1] // 1024)) for v in vers)
            version_dirs.append(_mkitem(parent, sum(v[1] for v in vers), note))
    version_dirs.sort(key=lambda r: -r["size_kb"])
    version_dirs = version_dirs[:top]
    return {"total": total, "count": count, "dir2": dir2, "dir3": dir3,
            "big": big, "installers": inst, "cache_dirs": cache_dirs,
            "updater_dirs": updater_dirs, "version_dirs": version_dirs}


# ---- Everything 不可用时的回退：os.scandir 全盘遍历（写同样格式 CSV）----
def walk_export_csv(drive, out_csv):
    """无 Everything 时保证全盘覆盖。慢（350 万文件约 30-90 分钟），
    大磁盘强烈建议装 Everything。跳过 symlink 与无权限目录，并统计拒绝数量，
    不再静默吞掉权限错误。"""
    stats = {"files": 0, "denied": 0, "errors": []}

    def note(msg):
        if len(stats["errors"]) < 20:
            stats["errors"].append(msg)

    with open(out_csv, "w", encoding="utf-8") as f:
        def visit(d):
            try:
                with os.scandir(d) as it:
                    for e in it:
                        try:
                            if e.is_symlink():
                                continue
                            if e.is_file(follow_symlinks=False):
                                sz = e.stat(follow_symlinks=False).st_size
                                f.write('"%s",%d\n' % (e.path.replace('"', '""'), sz))
                                stats["files"] += 1
                            elif e.is_dir(follow_symlinks=False):
                                visit(e.path)
                        except PermissionError:
                            stats["denied"] += 1
                            note("权限拒绝：%s" % e.path)
                        except OSError as ex:
                            note("%s：%s" % (e.path, ex))
            except PermissionError:
                stats["denied"] += 1
                note("权限拒绝：%s" % d)
            except OSError as ex:
                note("%s：%s" % (d, ex))
        visit(drive)
    return stats


def list_drives_windows():
    drives = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if os.path.exists(root):
            try:
                t, u, f = shutil.disk_usage(root)
                drives.append({"name": root, "total": human(t // 1024),
                               "used": human(u // 1024), "free": human(f // 1024)})
            except Exception:
                continue
    return drives


def system_info_windows():
    import platform
    info = {}
    ver_str = platform.release()
    build_str = platform.version()
    try:
        build_parts = build_str.split(".")
        build_num = int(build_parts[2]) if len(build_parts) >= 3 else 0
    except (ValueError, IndexError):
        build_num = 0
    if build_num >= 22000:
        ver_str = "11"
    info["os"] = platform.system() + " " + ver_str
    info["build"] = build_str
    info["arch"] = os.environ.get("PROCESSOR_ARCHITECTURE", platform.machine())
    info["user"] = os.environ.get("USERNAME", "")
    info["home"] = os.environ.get("USERPROFILE", HOME)
    sysdrive = os.environ.get("SystemDrive", "C:") + "\\"
    total, used, free = "?", "?", "?"
    try:
        t, u, f = shutil.disk_usage(sysdrive)
        total, used, free = human(t // 1024), human(u // 1024), human(f // 1024)
    except Exception:
        pass
    info["disk_total"], info["disk_used"], info["disk_free"] = total, used, free
    info["filesystem"] = "NTFS"
    info["purgeable"] = ""
    info["disk_name"] = sysdrive
    info["disks"] = list_drives_windows()
    return info


def dir_size_bytes(path):
    """递归大小（os.scandir，跳过 symlink/无权限）。用于回收站等小范围精确统计。
    注意：必须用 st_file_attributes 的 REPARSE_POINT 判断 junction——Windows 的
    junction 对 Path.is_symlink() 返回 False，跟随它会循环虚增（pnpm store 实测
    幻增 61GB）。"""
    FILE_ATTRIBUTE_REPARSE_POINT = 0x400
    total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                    if st.st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT:
                        continue
                    if e.is_file(follow_symlinks=False):
                        total += st.st_size
                    elif e.is_dir(follow_symlinks=False):
                        total += dir_size_bytes(e.path)
                except (PermissionError, OSError):
                    continue
    except (PermissionError, OSError):
        pass
    return total


def running_apps(limit=50):
    """列出运行中且位于用户/程序目录的进程名（供报告 kill_processes 参考）。"""
    try:
        r = _sp.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process | Where-Object { $_.Path -like '*Users*' -or "
             "$_.Path -like '*Program Files*' } | "
             "Select-Object -ExpandProperty ProcessName | Sort-Object -Unique"],
            capture_output=True, text=True, timeout=120)
        names = [n.strip() for n in r.stdout.splitlines() if n.strip()]
        return [{"name": n, "path": "", "size_kb": 0, "size_h": ""}
                for n in names[:limit]]
    except Exception:
        return []


def collect_temp_artifacts(tmpdir, drives):
    """本轮扫描留在临时目录的中间文件（只报告，不删除）。

    这些 CSV 是 Step 1.5 增量审计与 --reuse-csv 复扫的输入，不能在扫描后
    立即清掉；由 agent 在本轮分析结束、用户确认后按 SKILL.md Step 5 处理。
    """
    files = []
    for drive in drives:
        csv_path = os.path.join(tmpdir, "scan_%s.csv" % drive[0])
        for path in (csv_path, csv_path + ".wiz"):
            if not os.path.exists(path):
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            files.append({"path": path,
                          "size_kb": size // 1024,
                          "size_h": human(size // 1024)})
    total_kb = sum(f["size_kb"] for f in files)
    return {"dir": tmpdir, "files": files,
            "total_kb": total_kb, "total_h": human(total_kb),
            "rule": "Step 1.5 与复扫依赖这些 CSV；本轮分析结束、"
                    "用户确认不再复扫后再删除"}


def scan_windows(opts):
    source = opts.get("source", "auto")
    es = find_es() if source in ("auto", "everything") else None
    wz = find_wiztree() if source in ("auto", "wiztree") else None
    drives = opts.get("drives") or [d["name"] for d in list_drives_windows()]
    tmpdir = opts.get("tmpdir") or _tf.gettempdir()
    min_dir_mb = int(opts.get("min_dir_mb", 10))
    big_mb = int(opts.get("big_mb", 100))
    cache_mb = int(opts.get("cache_mb", 30))
    updater_mb = int(opts.get("updater_mb", 30))
    ver_mb = int(opts.get("ver_mb", 50))
    top = int(opts.get("top", 80))

    groups = {}
    coverage = {"method": "none", "source_requested": source,
                "es_path": es, "wiztree_path": wz, "drives": drives,
                "files_scanned": 0, "reused_csv": [],
                "drives_detail": [], "fallback_reasons": [],
                "denied_dirs": 0, "errors": [], "partial": False}
    used = set()
    reused_drives = []
    for drive in drives:
        csv_path = os.path.join(tmpdir, "scan_%s.csv" % drive[0])
        detail = {"drive": drive, "source": None, "files": 0, "reused": False,
                  "denied": 0, "status": "ok", "fallbacks": [], "errors": []}
        if opts.get("reuse_csv") and os.path.exists(csv_path) \
                and os.path.getsize(csv_path) > 0:
            reused_drives.append(csv_path)  # 复用上次导出的清单，跳过重复导出
            detail["reused"] = True
            detail["source"] = "reused"
            print("reused existing csv: %s" % csv_path, file=sys.stderr)
        else:
            picked = None
            for src in SOURCE_CHAIN[source]:
                if src == "everything":
                    if not es:
                        msg = "未找到 es.exe"
                        detail["fallbacks"].append({"source": "everything", "reason": msg})
                        if source == "everything":
                            print(msg + "：请安装 Everything，或设置 PATH", file=sys.stderr)
                        continue
                    info = es_export_csv(es, drive, csv_path)
                    if info["ok"]:
                        picked = "everything"
                        detail["expected"] = info.get("expected")
                        break
                    reason = info.get("error") or "导出失败"
                    # ES 存在但 Everything 没运行时，es.exe 会报 Error 8（IPC window not found）
                    print("Everything %s（常见原因：Everything 未启动），%s 盘"
                          % (reason, drive), file=sys.stderr)
                    detail["fallbacks"].append({"source": "everything", "reason": reason})
                elif src == "wiztree":
                    if not wz:
                        msg = "未找到 WizTree（wiztree64.exe）"
                        detail["fallbacks"].append({"source": "wiztree", "reason": msg})
                        if source == "wiztree":
                            print(msg + "：请安装 WizTree，"
                                  "或设置环境变量 %s 指向 exe" % WIZTREE_ENV,
                                  file=sys.stderr)
                        continue
                    if wiztree_export_csv(wz, drive, csv_path,
                                          admin=bool(opts.get("wiztree_admin"))):
                        picked = "wiztree"
                        break
                    reason = "WizTree 导出失败或清单为空"
                    print("%s，%s 盘" % (reason, drive), file=sys.stderr)
                    detail["fallbacks"].append({"source": "wiztree", "reason": reason})
                else:
                    print("%s 盘回退全盘遍历（无可用索引工具），耗时较长" % drive,
                          file=sys.stderr)
                    wstats = walk_export_csv(drive, csv_path)
                    detail["denied"] += wstats["denied"]
                    detail["errors"] = list(wstats["errors"])
                    if wstats["files"] > 0:
                        picked = "walk"
                        break
                    reason = "全盘遍历没有产出文件"
                    print("%s，%s 盘" % (reason, drive), file=sys.stderr)
                    detail["fallbacks"].append({"source": "walk", "reason": reason})
            if not picked:
                print("%s 盘所有数据源均失败，跳过该盘" % drive, file=sys.stderr)
                detail["status"] = "failed"
                coverage["partial"] = True
                coverage["drives_detail"].append(detail)
                coverage["errors"].extend(detail["errors"])
                continue
            used.add(picked)
            detail["source"] = picked
        res = combined_pass(csv_path, drive, min_dir_mb=min_dir_mb, big_mb=big_mb,
                            cache_mb=cache_mb, updater_mb=updater_mb,
                            ver_mb=ver_mb, top=top)
        detail["files"] = res["count"]
        coverage["files_scanned"] += res["count"]
        coverage["denied_dirs"] += detail["denied"]
        coverage["errors"].extend(detail["errors"])
        if detail["denied"]:
            coverage["partial"] = True
        if detail["fallbacks"]:
            pairs = "；".join("%s: %s" % (x["source"], x["reason"])
                             for x in detail["fallbacks"])
            coverage["fallback_reasons"].append("%s %s" % (drive, pairs))
        coverage["drives_detail"].append(detail)
        g = groups.setdefault("drive_" + drive[0], {})
        g["root_depth2"] = res["dir2"]
        g["root_depth3"] = res["dir3"]
        g["big_files"] = res["big"]
        g["installers"] = res["installers"]
        g["cache_dirs"] = res["cache_dirs"]
        g["updater_dirs"] = res["updater_dirs"]
        g["version_dirs"] = res["version_dirs"]

    coverage["reused_csv"] = reused_drives
    coverage["errors"] = coverage["errors"][:30]
    coverage["complete"] = not coverage["partial"]
    coverage["method"] = "+".join(
        s for s in ("everything", "wiztree", "walk") if s in used) \
        or ("reused" if reused_drives else "none")
    if "walk" in used and source == "auto":
        if not es and not wz:
            print("提示：未检测到 Everything / WizTree，已回退全盘遍历。"
                  "推荐先安装 Everything（免费、无需提权即可全盘覆盖、重复扫描秒级）。",
                  file=sys.stderr)
        elif es and not wz:
            print("提示：Everything 已安装但本次导出失败（常见原因：主程序未运行）。"
                  "启动 Everything 后重扫可提速 10 倍以上；也可安装 WizTree 作为备选。",
                  file=sys.stderr)
    if "wiztree" in used and not opts.get("wiztree_admin"):
        print("提示：WizTree 以普通权限导出，WindowsApps 等受保护目录可能漏计；"
              "需要完整覆盖请在提权终端加 --wiztree-admin 重扫。", file=sys.stderr)

    # 回收站（各盘）：合并大小
    recycle_items = []
    for drive in drives:
        rp = os.path.join(drive, "$Recycle.Bin")
        if os.path.exists(rp):
            kb = dir_size_bytes(rp) // 1024
            if kb >= 10240:
                recycle_items.append({"name": "$Recycle.Bin", "path": rp,
                                      "size_kb": kb, "size_h": human(kb)})
    groups["recycle_bin"] = recycle_items or []

    # 传统开发缓存固定列表（补充，用于快速发现；主数据仍是全盘聚合）
    profile = os.environ.get("USERPROFILE", HOME)
    local = os.environ.get("LOCALAPPDATA", os.path.join(profile, "AppData", "Local"))
    dev_paths = [
        os.path.join(profile, ".cache"), os.path.join(profile, ".npm"),
        os.path.join(profile, ".gradle"), os.path.join(profile, ".m2"),
        os.path.join(profile, ".cargo"), os.path.join(profile, ".rustup"),
        os.path.join(local, "ms-playwright"), os.path.join(local, "pip", "Cache"),
        os.path.join(local, "JetBrains"), os.path.join(local, "Yarn"),
        os.path.join(local, "pnpm"), os.path.join(local, "uv"),
        os.path.join(profile, ".vscode", "extensions"),
        os.path.join(profile, ".trae-cn", "extensions"),
        os.path.join(profile, ".cursor", "extensions"),
    ]
    dev = []
    for p in dev_paths:
        if not os.path.isdir(p):
            continue
        try:
            kb = dir_size_bytes(p) // 1024
        except (PermissionError, OSError):
            continue
        if kb >= 51200:
            dev.append({"name": os.path.basename(p.rstrip("\\/")) or p,
                        "path": p, "size_kb": kb, "size_h": human(kb)})
    dev.sort(key=lambda r: r["size_kb"], reverse=True)
    groups["dev_caches"] = dev
    groups["running_apps"] = running_apps()
    artifacts = collect_temp_artifacts(tmpdir, drives)
    if artifacts["files"]:
        print("临时清单：%s（合计 %s）。Step 1.5 与复扫依赖这些 CSV，"
              "本轮分析结束、用户确认不再复扫后再删除。"
              % (", ".join("%s %s" % (os.path.basename(f["path"]), f["size_h"])
                           for f in artifacts["files"]),
                 artifacts["total_h"]),
              file=sys.stderr)
    return system_info_windows(), groups, coverage, artifacts


def main():
    started = time.time()
    if sys.platform == "darwin":
        system, groups = scan_macos()
        hierarchy = {
            "home": {"parent": None, "children": ["library", "downloads", "dev_caches"]},
            "library": {"parent": "home", "children": ["caches", "containers", "group_containers", "app_support"]},
            "caches": {"parent": "library", "children": []},
            "containers": {"parent": "library", "children": []},
            "group_containers": {"parent": "library", "children": []},
            "app_support": {"parent": "library", "children": []},
            "applications": {"parent": None, "children": []},
            "downloads": {"parent": "home", "children": []},
            "dev_caches": {"parent": "home", "children": [], "note": "与 home/其他组有路径重叠，分析时需去重"},
        }
        data = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "system": system, "groups": groups, "_hierarchy": hierarchy,
            "coverage": {"method": "du", "drives": ["/"],
                         "files_scanned": None,
                         "drives_detail": [{"drive": "/", "source": "du",
                                            "files": None, "denied": 0,
                                            "status": "ok"}],
                         "fallback_reasons": [], "denied_dirs": 0,
                         "errors": [], "partial": False, "complete": None,
                         "note": "macOS 用 du 统计目标目录，非全盘文件清单"},
            "temp_artifacts": {"dir": _tf.gettempdir(), "files": [],
                               "total_kb": 0, "total_h": "0 KB",
                               "rule": "macOS 不生成 CSV；调用方保存的 scan JSON "
                                       "在本轮结束后按 SKILL.md Step 5 询问是否删除"},
            "scan_seconds": round(time.time() - started, 1),
        }
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    elif not sys.platform.startswith("win"):
        print(json.dumps({"error": "unsupported_platform", "platform": sys.platform,
                          "message": "scan.py supports macOS and Windows only."},
                         ensure_ascii=False))
        return

    # Windows CLI：scan.py [--drives C,D] [--source auto|everything|wiztree|walk]
    #              [--min-dir 10] [--big 100] [--cache 30] [--updater 30]
    #              [--ver 50] [--top 80] [--out FILE]
    import argparse
    ap = argparse.ArgumentParser(
        description="Read-only Windows storage scanner (Everything / WizTree / walk)")
    ap.add_argument("--drives", default="", help="comma list e.g. C,D (default: all fixed drives)")
    ap.add_argument("--source", choices=("auto", "everything", "wiztree", "walk"),
                    default="auto",
                    help="data source; auto = Everything -> WizTree -> walk")
    ap.add_argument("--no-everything", action="store_true",
                    help="等同于 --source walk（保留兼容）")
    ap.add_argument("--wiztree-admin", action="store_true", dest="wiztree_admin",
                    help="WizTree 以管理员模式导出（需已提权），走 MFT 且覆盖受保护目录")
    ap.add_argument("--reuse-csv", action="store_true", dest="reuse_csv",
                    help="reuse existing scan_<drive>.csv in temp dir instead of re-exporting")
    ap.add_argument("--min-dir", type=int, default=10, dest="min_dir_mb")
    ap.add_argument("--big", type=int, default=100, dest="big_mb")
    ap.add_argument("--cache", type=int, default=30, dest="cache_mb")
    ap.add_argument("--updater", type=int, default=30, dest="updater_mb")
    ap.add_argument("--ver", type=int, default=50, dest="ver_mb")
    ap.add_argument("--top", type=int, default=80)
    ap.add_argument("--out", default="", help="write JSON to file instead of stdout")
    args = ap.parse_args()
    opts = {"source": "walk" if args.no_everything else args.source,
            "min_dir_mb": args.min_dir_mb,
            "big_mb": args.big_mb, "cache_mb": args.cache_mb,
            "updater_mb": args.updater_mb, "ver_mb": args.ver_mb,
            "top": args.top, "tmpdir": None, "reuse_csv": args.reuse_csv,
            "wiztree_admin": args.wiztree_admin}
    if args.drives.strip():
        opts["drives"] = [d.strip() + ":\\" for d in args.drives.split(",") if d.strip()]
    system, groups, coverage, artifacts = scan_windows(opts)
    hierarchy = {
        "drive_*": {"parent": None, "children": []},
        "recycle_bin": {"parent": None, "children": [], "note": "回收站，清空后释放空间"},
        "dev_caches": {"parent": None, "children": [], "note": "与 drive_* 聚合有重叠，分析时需去重"},
        "running_apps": {"parent": None, "children": [], "note": "供 kill_processes 参考"},
    }
    data = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "system": system,
        "groups": groups,
        "coverage": coverage,
        "temp_artifacts": artifacts,
        "_hierarchy": hierarchy,
        "scan_seconds": round(time.time() - started, 1),
    }
    blob = json.dumps(data, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(blob)
        print("scan written to %s (%d bytes)" % (args.out, len(blob)), file=sys.stderr)
    else:
        print(blob)


if __name__ == "__main__":
    main()
