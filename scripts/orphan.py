# -*- coding: utf-8 -*-
"""orphan.py —— 卸载残留检测器（storage-analyzer v3 核心组件）

解决的问题：应用卸载后数据目录无人认领。实战教训：Kiro 卸载 90 天后其 720MB
数据目录才在第六轮被发现；Codex 四处分布 1.7GB 由用户口述才清除。

机制：枚举用户侧数据目录（%APPDATA% / %LOCALAPPDATA% / ~ 点目录），对照五处
安装证据（Programs / Program Files / WindowsApps 包仓库 / 开始菜单 / 卸载注册表）
判定应用是否还在。数据在而本体找不到 -> 孤儿候选，附最后活动时间与置信度。

用法：
  python orphan.py [--min-mb 20] [--csv <CSV>]
--csv 提供 Everything 导出清单时走查表（秒级）；缺省时回退 os.walk 实测（慢）。
输出 JSON 到 stdout。
"""
import os
import re
import sys
import json
import time
import argparse
import winreg

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


def collect_installed_names():
    """三处安装证据 -> 已安装应用名集合（规范化）"""
    names = set()

    # 1) %LOCALAPPDATA%\Programs
    prog = os.path.join(LOCAL, "Programs")
    if os.path.isdir(prog):
        for e in os.scandir(prog):
            names.add(norm(e.name))

    # 2) Program Files 两处
    for pf in [r"C:\Program Files", r"C:\Program Files (x86)"]:
        if os.path.isdir(pf):
            try:
                for e in os.scandir(pf):
                    names.add(norm(e.name))
            except OSError:
                pass

    # 3) 开始菜单
    sm = os.path.join(U, "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs")
    for root, dirs, fs in os.walk(sm, onerror=lambda e: None):
        for f in fs:
            if f.endswith(".lnk"):
                names.add(norm(os.path.splitext(f)[0]))

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
    except OSError:
        wa = r"C:\Program Files\WindowsApps"
        if os.path.isdir(wa):
            try:
                pkgs = {e.name for e in os.scandir(wa)}
            except OSError:
                pass
    for full in pkgs:
        pkg = full.split("_")[0]
        names.add(norm(pkg))
        # 末段短名用于匹配「Anthropic.Claude -> claude」这类；纯数字段（1.6/1.7）
        # 会污染集合，导致 .m2 之类被 '2' 误判为已安装，必须排除。
        tail = pkg.rsplit(".", 1)[1] if "." in pkg else ""
        if len(tail) >= 3 and not tail.isdigit():
            names.add(norm(tail))

    # 5) 注册表卸载键
    for hive, key_path in [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]:
        try:
            key = winreg.OpenKey(hive, key_path)
        except OSError:
            continue
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
                        except OSError:
                            pass
                except OSError:
                    pass
    return names


def load_csv_tree(csv_path):
    """CSV -> {目录: 子树大小}（含祖先传播）"""
    direct = {}
    with open(csv_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            i = line.rfind('",')
            if i < 0:
                continue
            p = line[1:i]
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
    ap.add_argument("--csv", default=None, help="Everything CSV，提供则查表取大小（快）")
    args = ap.parse_args()
    min_b = int(args.min_mb * 2**20)

    csv_tree = load_csv_tree(args.csv) if args.csv and os.path.exists(args.csv) else None
    installed = collect_installed_names()

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
        # 名称匹配：直接/别名/安装名包含
        alias_hit = norm(ALIAS.get(base.lower(), nb))
        installed_hit = (
            alias_hit in installed
            or nb in installed
            or any(nb and (nb in n or n in nb) for n in installed if abs(len(n) - len(nb)) < 8)
        )
        if installed_hit:
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
        elif days >= 90:
            confidence = "high"
        elif days >= 30:
            confidence = "medium"
        else:
            confidence = "low"
        orphans.append({
            "path": p,
            "size_bytes": sz,
            "last_active": time.strftime("%Y-%m-%d", time.localtime(m)) if m else "未知",
            "days_idle": days,
            "confidence": confidence,
            "note": "数据目录存在，未找到对应安装（Programs/Program Files/WindowsApps/开始菜单/卸载注册表）",
        })

    orphans.sort(key=lambda x: -x["size_bytes"])
    print(json.dumps({
        "installed_names_count": len(installed),
        "orphans": orphans,
        "summary": {
            "count": len(orphans),
            "total_bytes": sum(o["size_bytes"] for o in orphans),
        },
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
