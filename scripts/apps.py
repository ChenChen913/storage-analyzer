# -*- coding: utf-8 -*-
"""apps.py —— 应用登记表（storage-analyzer v3 组件）

解决的问题：审查顺序按「谁大看谁」，装过但没审过的应用长期排在视线外。

机制：枚举安装侧应用（Local\\Programs、Program Files 两处、注册表卸载键的
InstallLocation）和用户侧数据目录（Roaming、Local、家目录点目录、Packages），
按名称/别名配对，登记每个应用的数据路径、体积、最后活动时间。每轮先看
「未审查」清单，而不是只看 TopN。

注册表是跨盘安装的唯一可靠来源：实测多个编辑器与套壳应用全部装在其他盘，
只扫系统盘三处安装目录会全部漏掉。

用法：
  python apps.py build [--csv <CSV> ...] [--min-mb 20]
  python apps.py list  [--unreviewed] [--min-mb 20] [--json]
  python apps.py mark  <key> [--note "一句话结论"] [--unreviewed]

状态文件：<skill>\\state\\apps.json（可用 STORAGE_ANALYZER_STATE 覆盖目录）
"""
import os
import re
import sys
import glob
import json
import time
import argparse
import winreg

from orphan import norm, ALIAS, INFRA, mtime2

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.environ.get("STORAGE_ANALYZER_STATE") or os.path.join(HERE, "..", "state")
APPS_FILE = os.path.join(STATE_DIR, "apps.json")

U = os.path.expanduser("~")
LOCAL = os.path.join(U, "AppData", "Local")
ROAMING = os.path.join(U, "AppData", "Roaming")

INSTALL_ROOTS = [
    (os.path.join(LOCAL, "Programs"), "Programs"),
    (r"C:\Program Files", "Program Files"),
    (r"C:\Program Files (x86)", "Program Files (x86)"),
    (r"C:\Program Files\WindowsApps", "WindowsApps"),
]
SKIP_INSTALL = {
    "common files", "windowsapps", "modifiablewindowsapps", "windows defender",
    "windows nt", "internet explorer", "windows mail", "windows media player",
}

# 常见安装名与数据目录名之间的补充映射（在 orphan.ALIAS 之上）
APP_ALIAS = {
    "microsoft vs code": "visual studio code",
    "vs code": "visual studio code",
    "code": "visual studio code",
    "microsoft edge": "edge",
    "google chrome": "chrome",
    "trae cn": "trae",
    "trae solo": "trae",
    "bytedance trae": "trae",
    "wechat": "微信",
    "weixin": "微信",
    "dingtalk": "钉钉",
    "jianyingpro": "剪映",
    "jianying": "剪映",
    "quark": "夸克",
    # 注册表 DisplayName 常带后缀与厂商前缀，需显式收敛到数据目录名
    "qoder cn ide": "qoder",
    "qoder ide": "qoder",
    "trae solo": "trae",
    "antigravity ide": "antigravity",
}


def variants(name):
    """应用名/目录名 -> 一组可比较的规范化键（含去供应商前缀与别名）"""
    cleaned = re.sub(r"\s*[（(][^)）]*[)）]\s*$", "", name)  # 去掉 "(User)" 之类后缀
    n = norm(cleaned)
    out = {n}
    alias = APP_ALIAS.get(n) or ALIAS.get(cleaned.lower()) or ALIAS.get(name.lower())
    if alias:
        out.add(norm(alias))
    # 末段短名只收有意义的（"com.openhuman.app -> app" 这类要排除，
    # 纯数字段会把「Typora 1.2」错配到「AndroidStudio2024.2」）
    tail = n.rsplit(".", 1)[1] if "." in n else ""
    if len(tail) >= 3 and not tail.isdigit():
        out.add(norm(tail))
    for prefix in ("microsoft ", "google ", "adobe ", "jetbrains ", "tencent ", "bytedance "):
        if n.startswith(prefix):
            out.add(n[len(prefix):])
    # 对去前缀后的结果再查一次别名
    for v in list(out):
        a = APP_ALIAS.get(v)
        if a:
            out.add(norm(a))
    return {x for x in out if x}


def load_csv_tree(paths):
    """多个 Everything CSV -> {目录: 全树大小}"""
    direct = {}
    used = 0
    for p in paths:
        if not os.path.exists(p):
            print(f"CSV 不存在，跳过: {p}", file=sys.stderr)
            continue
        used += 1
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                i = line.rfind('",')
                if i < 0:
                    continue
                path = line[1:i]
                try:
                    sz = int(line[i + 2:].strip())
                except ValueError:
                    continue
                if sz >= 2**63 or sz < 0:
                    sz = 0
                d = os.path.dirname(path)
                direct[d] = direct.get(d, 0) + sz
    tree = dict(direct)
    all_dirs = set()
    for d in tree:
        parts = d.split("\\")
        for k in range(1, len(parts) + 1):
            all_dirs.add("\\".join(parts[:k]))
    for d in all_dirs:
        tree.setdefault(d, 0)
    for d in sorted(tree, key=len, reverse=True):
        if tree[d] == 0 and d not in direct:
            continue
        parent = os.path.dirname(d)
        if parent and parent in tree and parent != d:
            tree[parent] += tree[d]
    return tree, used


def collect_registry_apps():
    """注册表卸载键 -> [{name, install_path}]（跨盘安装的唯一可靠来源）"""
    out = []
    keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, path in keys:
        try:
            root_key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with root_key:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root_key, i)
                    i += 1
                except OSError:
                    break
                try:
                    with winreg.OpenKey(root_key, sub) as sk:
                        try:
                            name = winreg.QueryValueEx(sk, "DisplayName")[0]
                        except OSError:
                            continue
                        try:
                            if winreg.QueryValueEx(sk, "SystemComponent")[0] == 1:
                                continue
                        except OSError:
                            pass
                        try:
                            loc = winreg.QueryValueEx(sk, "InstallLocation")[0].strip('" ')
                        except OSError:
                            loc = ""
                        if not loc:
                            # 无 InstallLocation 时退回 DisplayIcon（形如 "D:\\App\\a.exe",0）
                            try:
                                icon = winreg.QueryValueEx(sk, "DisplayIcon")[0]
                                if icon.lower().endswith(".exe") or ".exe," in icon.lower():
                                    loc = icon.split(",")[0].strip('" ')
                                    loc = os.path.dirname(loc)
                            except OSError:
                                loc = ""
                        out.append({"name": str(name), "install_path": loc})
                except OSError:
                    pass
    return out


def collect_install_apps():
    """安装侧应用 -> {规范化键: {name, keys, install_paths, install_source}}"""
    apps = {}

    def add(display, path, source):
        if not display or display.lower() in SKIP_INSTALL:
            return
        base = norm(re.sub(r"\s*[（(][^)）]*[)）]\s*$", "", display))
        if not base:
            return
        # 别名收敛后再做 key，避免「Qoder IDE / Qoder CN IDE」分裂成两条
        key = APP_ALIAS.get(base) or base
        ent = apps.setdefault(key, {
            "name": display,
            "keys": set(),
            "install_paths": [],
            "install_source": source,
        })
        ent["keys"].update(variants(display))
        if path and path not in ent["install_paths"]:
            ent["install_paths"].append(path)

    for root, source in INSTALL_ROOTS:
        if not os.path.isdir(root):
            continue
        try:
            entries = list(os.scandir(root))
        except OSError:
            continue
        for e in entries:
            if not e.is_dir():
                continue
            display = e.name.split("_")[0] if source == "WindowsApps" else e.name
            add(display, e.path, source)

    for item in collect_registry_apps():
        add(item["name"], item["install_path"], "Registry")
    return apps


def collect_data_dirs():
    """用户侧数据目录候选（一级目录 + 点目录 + Packages + Microsoft/Google 子目录）"""
    out = []
    for base in (ROAMING, LOCAL):
        try:
            for e in os.scandir(base):
                if e.is_dir() and norm(e.name) not in INFRA:
                    out.append(e.path)
        except OSError:
            pass
    try:
        for e in os.scandir(U):
            if e.is_dir() and e.name.startswith(".") and len(e.name) > 1:
                out.append(e.path)
    except OSError:
        pass
    packages = os.path.join(LOCAL, "Packages")
    if os.path.isdir(packages):
        try:
            for e in os.scandir(packages):
                if e.is_dir():
                    out.append(e.path)
        except OSError:
            pass
    for vendor in ("Microsoft", "Google"):
        vdir = os.path.join(LOCAL, vendor)
        if os.path.isdir(vdir):
            try:
                for e in os.scandir(vdir):
                    if e.is_dir():
                        out.append(e.path)
            except OSError:
                pass
    return out


def match(app_keys, data_keys):
    return any(key in data_keys for key in app_keys)


def load_store():
    if os.path.exists(APPS_FILE):
        with open(APPS_FILE, encoding="utf-8-sig") as f:
            return json.load(f)
    return {"version": 1, "updated_at": "", "apps": {}}


def save_store(store):
    os.makedirs(STATE_DIR, exist_ok=True)
    store["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(APPS_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=1)


def resolve_csvs(arg_csv):
    if arg_csv:
        return arg_csv
    temp = os.environ.get("TEMP") or os.environ.get("TMP") or "."
    found = sorted(glob.glob(os.path.join(temp, "scan_*.csv")))
    return found or [os.path.join(temp, "scan_C.csv")]


def cmd_build(args):
    paths = resolve_csvs(args.csv)
    tree, used = load_csv_tree(paths)
    if not used:
        print("没有可用的 CSV，无法建立应用登记表", file=sys.stderr)
        sys.exit(1)
    install_apps = collect_install_apps()
    data_dirs = [(d, variants(os.path.basename(d))) for d in collect_data_dirs()]
    store = load_store()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    seen = set()

    for key, app in install_apps.items():
        seen.add(key)
        matched = [d for d, dk in data_dirs if match(app["keys"], dk)]
        size = sum(tree.get(d, 0) for d in matched)
        m = max((mtime2(d) for d in matched), default=0)
        old = store["apps"].get(key, {})
        ent = {
            "name": app["name"],
            "install_source": app["install_source"],
            "install_paths": sorted(set(app["install_paths"])),
            "data_paths": sorted(matched),
            "size_bytes": size,
            "last_active": time.strftime("%Y-%m-%d", time.localtime(m)) if m else "",
            "days_idle": round((time.time() - m) / 86400, 0) if m else -1,
            "installed": True,
            "reviewed": old.get("reviewed", False),
            "note": old.get("note", ""),
            "first_seen": old.get("first_seen") or now,
            "last_seen": now,
        }
        store["apps"][key] = ent

    # 已消失的安装项保留历史，但标记 installed=false
    for key, ent in store["apps"].items():
        if key not in seen and ent.get("installed"):
            ent["installed"] = False
            ent["last_seen"] = now

    save_store(store)
    with_data = [a for a in store["apps"].values() if a.get("installed") and a.get("data_paths")]
    unreviewed = [a for a in with_data if not a.get("reviewed")]
    print(f"应用登记表已更新: {APPS_FILE}")
    print(f"读取 {used} 个 CSV | 安装应用 {len(install_apps)} 个 | 有数据目录 {len(with_data)} 个 | 未审查 {len(unreviewed)} 个")


def cmd_list(args):
    store = load_store()
    thresh = args.min_mb * 2**20
    rows = []
    for key, ent in store["apps"].items():
        if not ent.get("installed") or not ent.get("data_paths"):
            continue
        if ent.get("size_bytes", 0) < thresh:
            continue
        if args.unreviewed and ent.get("reviewed"):
            continue
        rows.append((key, ent))
    rows.sort(key=lambda x: -x[1].get("size_bytes", 0))

    if args.json:
        print(json.dumps([
            {"key": k, **v} for k, v in rows
        ], ensure_ascii=False, indent=1))
        return
    if not rows:
        print("没有符合条件的应用")
        return
    print(f"{'大小':>10}  应用 / 数据目录 / 活跃度")
    for key, ent in rows:
        size = ent.get("size_bytes", 0) / 2**20
        active = ent.get("last_active") or "未知"
        days = ent.get("days_idle", -1)
        age = f"{days:.0f} 天前" if days >= 0 else "活跃度未知"
        flag = "已审查" if ent.get("reviewed") else "未审查"
        print(f"{size:>8.1f} MB  {key}  [{flag}]  {active}（{age}）")
        for p in ent.get("data_paths", []):
            print(f"            {p}")


def cmd_mark(args):
    store = load_store()
    ent = store["apps"].get(args.key)
    if ent is None:
        print(f"没有这个应用: {args.key}", file=sys.stderr)
        sys.exit(1)
    if args.note:
        ent["note"] = args.note
    ent["reviewed"] = not args.unreviewed
    save_store(store)
    print(f"已标记 {args.key} -> {'未审查' if args.unreviewed else '已审查'}")


def main():
    ap = argparse.ArgumentParser(description="应用登记表")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build")
    p.add_argument("--csv", nargs="+", default=None)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("list")
    p.add_argument("--unreviewed", action="store_true")
    p.add_argument("--min-mb", type=float, default=20.0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("mark")
    p.add_argument("key")
    p.add_argument("--note", default="")
    p.add_argument("--unreviewed", action="store_true")
    p.set_defaults(func=cmd_mark)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
