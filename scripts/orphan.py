# -*- coding: utf-8 -*-
"""orphan.py —— 卸载残留检测器（storage-analyzer v3 核心组件）

解决的问题：应用卸载后数据目录无人认领。实战教训：某编辑器卸载 90 天后其数百 MB
数据目录才在第六轮被发现；另一个 AI 工具四处分布数 GB，由用户口述才清除。

机制：枚举用户侧数据目录（%APPDATA% / %LOCALAPPDATA% / ~ 点目录），对照五处
安装证据（Programs / Program Files / WindowsApps 包仓库 / 开始菜单 / 卸载注册表）
判定应用是否还在。数据在而本体找不到 -> 孤儿候选，附最后活动时间与置信度。

用法：
  python orphan.py [--min-mb 20] [--csv <CSV> ...] [--out <JSON>]
--csv 可传多个文件（C、D 多盘时必须全传），提供时走查表（秒级）；
缺省回退 os.walk 实测（慢）。
--out 直接写 UTF-8 无 BOM 的 JSON 文件，避免 PowerShell 重定向产生 BOM。
输出 JSON 到 stdout（未指定 --out 时）。
"""
import os
import re
import sys
import json
import time
import argparse
import difflib

try:
    import winreg
except ImportError:  # 非 Windows：模块仍可导入，注册表证据按“不可用”处理
    winreg = None

U = os.path.expanduser("~")
LOCAL = os.path.join(U, "AppData", "Local")
ROAMING = os.path.join(U, "AppData", "Roaming")

# 数据目录名 -> 安装侧候选名（含中文名映射：中文系统开始菜单/注册表用中文 DisplayName）
ALIAS = {
    ".kiro": "kiro", ".codex": "codex", ".workbuddy": "workbuddy",
    ".lingma": "lingma", ".trae-cn": "trae", ".cursor": "cursor",
    ".vscode": "visual studio code", ".dsh": "dsh", ".zcode": "zcode",
    "doubao": "豆包", "doubaowork": "豆包", "dingtalk": "钉钉",
    "jianyingpro": "剪映", "jianying": "剪映", "quark": "夸克",
    "qianwen": "通义千问", "kiro": "kiro", "openhuman": "openhuman",
    "qoder": "qoder", "tdappdesktop": "腾讯文档", "tencentdocs": "腾讯文档",
    "baidunetdisk": "百度网盘", "bilibili": "哔哩哔哩", "iqiyi": "爱奇艺",
    "youku": "优酷", "xwechat": "微信", "wechat": "微信", "qq": "qq",
}

# 这些目录名是通用基础设施（开发运行时/多应用共用库），不是「应用」本体，不做孤儿判定
INFRA = {
    "temp", "cache", "programs", "microsoft", "google", "packages", "connecteddevicesplatform",
    "comms", "crashdumps", "squirreltemp", "appdata", "local", "roaming", "low",
    "jetbrains", "npm-cache", "npm", "pip", "pypa", "go-build", "gnupg",
    "python", "hermes", "ms-playwright", "rustup", ".rustup", ".cargo",
    ".cache", ".npm", ".gradle", ".m2", ".ollama", ".venv", "node-gyp",
    ".git", ".ssh", ".gnupg", ".config", ".local", ".docker",
}


def norm(name):
    """规范化目录名：去点、去版本后缀(_133 等)、去空格标点、小写"""
    n = name.lower().strip(".")
    n = re.sub(r"[_\-\. ](x64|x86|win|windows|desktop|app|cn|stable|insider|beta|preview|\d{2,})$", "", n)
    return n


def dsize(p):
    total = 0
    for root, dirs, fs in os.walk(p, onerror=lambda e: None):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def mtime2(p, max_depth=2, cur=0):
    """两层 mtime 活跃度"""
    latest = 0
    try:
        for e in os.scandir(p):
            try:
                m = e.stat(follow_symlinks=False).st_mtime
                if m > latest:
                    latest = m
                if e.is_dir(follow_symlinks=False) and cur < max_depth - 1:
                    m2 = mtime2(e.path, max_depth, cur + 1)
                    if m2 > latest:
                        latest = m2
            except OSError:
                pass
    except OSError:
        pass
    return latest


def _source(sources, name, status, count=0, note=""):
    sources.append({"source": name, "status": status, "names": count, "note": note})


def collect_installed_names():
    """五处安装证据 -> (已安装应用名集合, 证据来源清单)

    证据来源清单会随结果一起输出：某个来源读不到时，必须让使用者看到
    「这次判断缺了哪一块」，而不是把读不到当成「没安装」。"""
    names = set()
    sources = []

    # 1) %LOCALAPPDATA%\Programs
    prog = os.path.join(LOCAL, "Programs")
    if os.path.isdir(prog):
        try:
            ents = list(os.scandir(prog))
            for e in ents:
                names.add(norm(e.name))
            _source(sources, "LOCALAPPDATA\\Programs", "ok", len(ents))
        except OSError as e:
            _source(sources, "LOCALAPPDATA\\Programs", "denied", 0, str(e))
    else:
        _source(sources, "LOCALAPPDATA\\Programs", "missing")

    # 2) Program Files 两处
    for pf, label in [(r"C:\Program Files", "Program Files"),
                      (r"C:\Program Files (x86)", "Program Files (x86)")]:
        if os.path.isdir(pf):
            try:
                ents = list(os.scandir(pf))
                for e in ents:
                    names.add(norm(e.name))
                _source(sources, label, "ok", len(ents))
            except OSError as e:
                _source(sources, label, "denied", 0, str(e))
        else:
            _source(sources, label, "missing")

    # 3) 开始菜单
    sm = os.path.join(U, "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs")
    walk_errors = []
    lnk = 0
    for root, dirs, fs in os.walk(sm, onerror=walk_errors.append):
        for f in fs:
            if f.endswith(".lnk"):
                names.add(norm(os.path.splitext(f)[0]))
                lnk += 1
    if not os.path.isdir(sm):
        _source(sources, "Start Menu", "missing")
    elif walk_errors:
        _source(sources, "Start Menu", "denied", lnk, "%d 个目录无法读取" % len(walk_errors))
    else:
        _source(sources, "Start Menu", "ok", lnk)

    if winreg is None:
        _source(sources, "WindowsApps", "denied", 0, "非 Windows 平台，无注册表证据")
        _source(sources, "卸载注册表", "denied", 0, "非 Windows 平台，无注册表证据")
        return names, sources

    # 4) WindowsApps（Store 应用）：包名形如 Publisher.App_版本_架构_哈希
    # 目录本身受 ACL 保护，普通权限 scandir 会 PermissionError，改从注册表
    # AppModel 仓库枚举包全名（HKCR 可读，实测 400+ 包），目录枚举仅作回退。
    pkgs = set()
    repo = r"Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages"
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, repo) as k:
            n = winreg.QueryInfoKey(k)[0]
            for i in range(n):
                try:
                    pkgs.add(winreg.EnumKey(k, i))
                except OSError:
                    pass
        _source(sources, "WindowsApps (AppModel)", "ok", len(pkgs))
    except OSError as e:
        wa = r"C:\Program Files\WindowsApps"
        if os.path.isdir(wa):
            try:
                pkgs = {e2.name for e2 in os.scandir(wa)}
                _source(sources, "WindowsApps (directory)", "ok", len(pkgs), "注册表不可读，改用目录枚举")
            except OSError as e2:
                _source(sources, "WindowsApps", "denied", 0, "注册表与目录均不可读：%s / %s" % (e, e2))
        else:
            _source(sources, "WindowsApps", "denied", 0, "注册表不可读：%s" % e)
    for full in pkgs:
        pkg = full.split("_")[0]
        names.add(norm(pkg))
        # 末段短名用于匹配「Anthropic.Claude -> claude」这类；纯数字段（1.6/1.7）
        # 会污染集合，导致 .m2 之类被 '2' 误判为已安装，必须排除。
        tail = pkg.rsplit(".", 1)[1] if "." in pkg else ""
        if len(tail) >= 3 and not tail.isdigit():
            names.add(norm(tail))

    # 5) 注册表卸载键
    reg_ok = 0
    reg_names = 0
    reg_errors = []
    for hive, key_path in [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]:
        try:
            key = winreg.OpenKey(hive, key_path)
        except OSError as e:
            reg_errors.append("%s: %s" % (key_path, e))
            continue
        reg_ok += 1
        with key:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                    i += 1
                except OSError:
                    break
                try:
                    with winreg.OpenKey(key, sub) as sk:
                        try:
                            dn, _ = winreg.QueryValueEx(sk, "DisplayName")
                            names.add(norm(dn))
                            reg_names += 1
                        except OSError:
                            pass
                except OSError:
                    pass
    if reg_ok == 3:
        _source(sources, "卸载注册表", "ok", reg_names)
    elif reg_ok:
        _source(sources, "卸载注册表", "partial", reg_names, "; ".join(reg_errors))
    else:
        _source(sources, "卸载注册表", "denied", 0, "; ".join(reg_errors))
    return names, sources


def match_installed(nb, alias_hit, installed):
    """候选名 -> (匹配置信方式, 命中的安装名)

    只允许三种命中：别名精确、规范化精确、长名互相包含。互相包含限制最短
    5 个字符且长度比 >= 0.5：原来「长度差 < 8 就子串命中」会让 qq / dsh 之类
    的短名被任意长名吞掉，把真残留误判成「已安装」，这正是漏删的来源。"""
    if alias_hit and alias_hit in installed:
        return "alias", alias_hit
    if nb in installed:
        return "exact", nb
    if len(nb) < 5:
        return None, None
    for n in installed:
        if not n or len(n) < 5:
            continue
        short, long_ = (nb, n) if len(nb) <= len(n) else (n, nb)
        if short in long_ and len(short) / len(long_) >= 0.5:
            return "contains", n
    return None, None


def load_csv_tree(csv_path):
    """CSV -> {目录: 子树大小}（含祖先传播）"""
    direct = {}
    with open(csv_path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            i = line.rfind('",')
            if i < 0:
                continue
            p = line[1:i] if line.startswith('"') else line[:i].lstrip('"')
            try:
                sz = int(line[i + 2:].strip())
            except ValueError:
                continue
            if sz >= 2**63 or sz < 0:
                sz = 0
            d = os.path.dirname(p)
            direct[d] = direct.get(d, 0) + sz
    tree = dict(direct)
    all_dirs = set()
    for d in tree:
        parts = d.split('\\')
        for k in range(1, len(parts) + 1):
            all_dirs.add('\\'.join(parts[:k]))
    for d in all_dirs:
        tree.setdefault(d, 0)
    for d in sorted(tree, key=len, reverse=True):
        if tree[d] == 0 and d not in direct:
            continue
        parent = os.path.dirname(d)
        if parent and parent in tree and parent != d:
            tree[parent] += tree[d]
    return tree


def main():
    ap = argparse.ArgumentParser(description="卸载残留检测器")
    ap.add_argument("--min-mb", type=float, default=20.0)
    ap.add_argument("--csv", nargs="+", default=None,
                    help="一个或多个 Everything CSV（多盘时要全传），提供则查表取大小（快）")
    ap.add_argument("--out", default="",
                    help="把 JSON 写入文件（UTF-8 无 BOM），避免 PowerShell 重定向产生 BOM")
    args = ap.parse_args()
    min_b = int(args.min_mb * 2**20)

    csv_tree = None
    for cp in args.csv or []:
        if not os.path.exists(cp):
            print("CSV 不存在，跳过: %s" % cp, file=sys.stderr)
            continue
        t = load_csv_tree(cp)
        if csv_tree is None:
            csv_tree = t
        else:
            for d, sz in t.items():
                csv_tree[d] = csv_tree.get(d, 0) + sz
    installed, sources = collect_installed_names()
    incomplete = [s["source"] for s in sources if s["status"] in ("denied", "partial")]

    candidates = []
    # 候选来源三处：Roaming 一级、Local 一级、~ 下点目录
    for base in [ROAMING, LOCAL]:
        try:
            entries = list(os.scandir(base))
        except OSError:
            continue
        for e in entries:
            if e.is_dir():
                candidates.append(e.path)
    for e in os.scandir(U):
        if e.is_dir() and e.name.startswith(".") and len(e.name) > 1:
            candidates.append(e.path)

    orphans = []
    for p in candidates:
        base = os.path.basename(p)
        nb = norm(base)
        if nb in INFRA:
            continue
        # 名称匹配：别名精确 / 规范化精确 / 受限的长名互相包含
        alias_hit = norm(ALIAS.get(base.lower(), nb))
        kind, _ = match_installed(nb, alias_hit, installed)
        if kind:
            continue
        if csv_tree is not None:
            sz = csv_tree.get(p, 0)
        else:
            try:
                sz = dsize(p)
            except OSError:
                continue
        if sz < min_b:
            continue
        m = mtime2(p)
        days = round((time.time() - m) / 86400, 0) if m else -1
        if days < 0:
            confidence = "unknown"
            basis = "目录内文件 mtime 不可读，无法判断最后活动时间"
        else:
            if days >= 90:
                confidence = "high"
            elif days >= 30:
                confidence = "medium"
            else:
                confidence = "low"
            basis = "最后活动 %d 天前，安装侧五处证据均未命中" % days
        if incomplete and confidence == "high":
            confidence = "medium"
            basis += "；安装证据不完整（%s），置信度上限降为 medium" % "、".join(incomplete)
        orphans.append({
            "path": p,
            "size_bytes": sz,
            "last_active": time.strftime("%Y-%m-%d", time.localtime(m)) if m else "未知",
            "days_idle": days,
            "confidence": confidence,
            "confidence_basis": basis,
            "name_checked": {
                "raw": base,
                "normalized": nb,
                "alias": alias_hit if alias_hit != nb else "",
            },
            "evidence": {
                "matched": None,
                "closest_installed": difflib.get_close_matches(nb, installed, n=2, cutoff=0.72),
                "sources_checked": len(sources),
                "sources_incomplete": incomplete,
            },
            "note": "数据目录存在，五处安装证据均未找到对应应用；请结合下方证据链人工确认",
        })

    orphans.sort(key=lambda x: -x["size_bytes"])
    blob = json.dumps({
        "installed_names_count": len(installed),
        "install_evidence": {
            "sources": sources,
            "incomplete": incomplete,
        },
        "orphans": orphans,
        "summary": {
            "count": len(orphans),
            "total_bytes": sum(o["size_bytes"] for o in orphans),
            "high_confidence": sum(1 for o in orphans if o["confidence"] == "high"),
            "incomplete_install_evidence": bool(incomplete),
        },
    }, ensure_ascii=False, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(blob)
        print("orphans written to %s" % args.out, file=sys.stderr)
    else:
        print(blob)


if __name__ == "__main__":
    main()
