# -*- coding: utf-8 -*-
"""registry.py —— 目录定性档案引擎（storage-analyzer v3 核心组件）

解决的问题：跨轮失忆。每轮分析都是「从头再看」，导致同目录同类文件反复成为「新发现」。

用法：
  python registry.py baseline [--csv <CSV> ...] [--min-mb 20]
      从 CSV 建立/更新档案基线，采集目录大小与活跃度（两层 mtime）。
      --csv 可传多个文件（如 C、D 两盘）；缺省自动发现 %TEMP%\\scan_*.csv。
  python registry.py diff [--csv <CSV> ...] [--min-mb 20]
      输出增量审计报告：新目录 / 增大目录 / 复活目录 / 未定性目录，
      并写 state/last_diff.json 供报告标注「新发现 / 删后复发」。
  python registry.py mark <path> <green|yellow|red|keep> "<note>"
      agent 定性后写回档案（防止下轮重复定性）。
  python registry.py stats
      档案统计：已定性/未定性数量、覆盖体积。

档案位置：<skill>\\state\\registry.json（可用 STORAGE_ANALYZER_STATE 环境变量覆盖目录）
CSV 格式："路径",大小（Everything 导出，无表头）；溢出值 >= 2^63 置 0。
"""
import os
import sys
import glob
import time
import argparse

import statefile

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.environ.get("STORAGE_ANALYZER_STATE") or os.path.join(HERE, "..", "state")
REG_FILE = os.path.join(STATE_DIR, "registry.json")
DIFF_FILE = os.path.join(STATE_DIR, "last_diff.json")


def resolve_csvs(arg_csv):
    """--csv 可传多个；缺省自动发现 TEMP 下的 scan_*.csv，避免单盘误判。"""
    if arg_csv:
        return arg_csv
    temp = os.environ.get("TEMP") or os.environ.get("TMP") or "."
    found = sorted(glob.glob(os.path.join(temp, "scan_*.csv")))
    return found or [os.path.join(temp, "scan_C.csv")]


def load_csvs(paths):
    """合并多盘 CSV -> ({目录: 直接文件字节}, 实际读取的 CSV 数)"""
    direct = {}
    used = 0
    for p in paths:
        if not os.path.exists(p):
            print(f"CSV 不存在，跳过: {p}", file=sys.stderr)
            continue
        used += 1
        for d, sz in load_csv(p).items():
            direct[d] = direct.get(d, 0) + sz
    return direct, used


def load_csv(csv_path):
    """读 Everything CSV -> {目录: 直接文件字节}"""
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
    return direct


def build_tree(direct):
    """直接文件大小 -> 全树大小（先收祖先集合，再按路径长度降序传播）"""
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


def mtime2(p, max_depth=2, cur=0):
    """轻量活跃度：只 scandir 下探两层，取最新 mtime（避免全量 walk 超时）"""
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


REG_DEFAULT = {"version": 1, "updated_at": "", "last_diff_check": "", "dirs": {}}


def normalize_reg(reg):
    """旧版本/手工改坏的档案 -> 补齐缺省字段，保证后续 .get 安全"""
    if not isinstance(reg, dict):
        reg = {}
    for k, v in REG_DEFAULT.items():
        reg.setdefault(k, v.copy() if isinstance(v, dict) else v)
    if not isinstance(reg.get("dirs"), dict):
        reg["dirs"] = {}
    clean = {}
    for d, ent in reg["dirs"].items():
        if not isinstance(ent, dict):
            ent = {}
        ent.setdefault("size", 0)
        ent.setdefault("mtime", 0)
        ent.setdefault("tier", None)
        ent.setdefault("note", "")
        ent.setdefault("first_seen", "")
        ent.setdefault("last_seen", "")
        ent.setdefault("deleted", False)
        ent.setdefault("resurrected", 0)
        if not isinstance(ent["size"], (int, float)):
            ent["size"] = 0
        clean[d] = ent
    reg["dirs"] = clean
    return reg


def load_reg():
    """读档案：损坏文件会被隔离并回退到空档案，不再让整条分析链崩掉"""
    with statefile.locked(REG_FILE):
        return normalize_reg(statefile.load_json(REG_FILE, {}))


def save_reg(reg):
    """原子写：先写临时文件再替换，避免中断/并发留下半截 JSON"""
    with statefile.locked(REG_FILE):
        reg["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        statefile.save_json(REG_FILE, normalize_reg(reg))


def reg_locked(fn):
    """给「读-改-写」命令整体加锁：两个 agent 同时跑 baseline 也不会互相覆盖"""
    def wrapper(args):
        with statefile.locked(REG_FILE):
            return fn(args)
    return wrapper


@reg_locked
def cmd_baseline(args):
    paths = resolve_csvs(args.csv)
    direct, n_csv = load_csvs(paths)
    if not n_csv:
        print("没有可用的 CSV，基线未更新", file=sys.stderr)
        sys.exit(1)
    print(f"读取 {n_csv} 个 CSV: " + ", ".join(os.path.basename(p) for p in paths if os.path.exists(p)))
    tree = build_tree(direct)
    reg = load_reg()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    seen = set()
    n_new = n_gone = 0
    thresh = args.min_mb * 2**20

    # 只对 >= 阈值的目录建档案
    for d, sz in tree.items():
        if sz < thresh:
            continue
        seen.add(d)
        ent = reg["dirs"].get(d)
        if ent is None:
            reg["dirs"][d] = {
                "size": sz, "mtime": mtime2(d), "tier": None, "note": "",
                "first_seen": now, "last_seen": now,
                "deleted": False, "resurrected": 0,
            }
            n_new += 1
        else:
            old_size = ent.get("size", 0)
            was_deleted = ent.get("deleted", False)
            if was_deleted and sz > 0:
                ent["resurrected"] = ent.get("resurrected", 0) + 1
                ent["last_resurrected"] = now
            ent.update({"size": sz, "last_seen": now, "deleted": False})
            # 活跃度只对变化明显或无记录的重新采集，控制耗时。
            # 注意必须先保存旧大小再 update，否则差值恒为 0。
            if abs(sz - old_size) > 10 * 2**20 or not ent.get("mtime"):
                ent["mtime"] = mtime2(d)

    # 本轮没见到的 -> deleted
    for d, ent in reg["dirs"].items():
        if d not in seen and not ent.get("deleted"):
            ent["deleted"] = True
            n_gone += 1

    save_reg(reg)
    print(f"基线已更新: {REG_FILE}")
    print(f"档案目录 {len(reg['dirs'])} 个 | 新增 {n_new} | 标记删除 {n_gone}")


@reg_locked
def cmd_diff(args):
    paths = resolve_csvs(args.csv)
    direct, n_csv = load_csvs(paths)
    if not n_csv:
        print("没有可用的 CSV，无法做增量审计", file=sys.stderr)
        sys.exit(1)
    tree = build_tree(direct)
    reg = load_reg()
    thresh = args.min_mb * 2**20
    now = time.time()
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    # 用上一轮 diff 的时间做检查点，而不是靠「档案里有没有」。
    # 这样即使本轮先跑过 baseline（新目录已建档），diff 仍能把它标成新发现。
    last_check = reg.get("last_diff_check")

    new_items, grew_items, res_items, unrev_items = [], [], [], []
    for d, sz in tree.items():
        if sz < thresh:
            continue
        ent = reg["dirs"].get(d)
        if ent is None:
            new_items.append((d, sz))
        else:
            if last_check and ent.get("first_seen", "") > last_check:
                new_items.append((d, sz))
            delta = sz - ent.get("size", 0)
            if delta >= 50 * 2**20:
                grew_items.append((d, sz, delta))
            if last_check and ent.get("last_resurrected", "") > last_check:
                res_items.append((d, sz))
            if not ent.get("tier"):
                unrev_items.append((d, sz))

    def show(items, title, fmt):
        print(f"\n===== {title} ({len(items)}) =====")
        for it in sorted(items, key=lambda x: -x[1])[:40]:
            print(" " + fmt(it))

    show(new_items, "新目录(档案无记录)", lambda t: f"{t[1]/2**20:>9.1f} MB  {t[0]}")
    show(grew_items, "显著增大(+50MB)", lambda t: f"{t[1]/2**20:>9.1f} MB (+{t[2]/2**20:.0f})  {t[0]}")
    show(res_items, "删后复活(活水缓存)", lambda t: f"{t[1]/2**20:>9.1f} MB  {t[0]}")
    show(unrev_items, "未定性(tier=null)", lambda t: f"{t[1]/2**20:>9.1f} MB  {t[0]}")

    # 未定性目录的活跃度提示
    stale = [(d, s) for d, s in unrev_items
             if reg["dirs"].get(d, {}).get("mtime")
             and now - reg["dirs"][d]["mtime"] > 30 * 86400]
    if stale:
        print(f"\n===== 未定性且超 30 天无活动（优先审查，疑似弃用） ({len(stale)}) =====")
        for d, s in sorted(stale, key=lambda x: -x[1])[:25]:
            days = (now - reg["dirs"][d]["mtime"]) / 86400
            print(f" {s/2**20:>9.1f} MB  {days:>4.0f} 天未动  {d}")

    # 供报告标注用：只存路径，不存体积，文件很小。
    payload = {
        "generated_at": now_str,
        "csv": [p for p in paths if os.path.exists(p)],
        "new": [d for d, _ in new_items],
        "resurrected": [d for d, _ in res_items],
        "grew": [d for d, _, _ in grew_items],
    }
    statefile.save_json(DIFF_FILE, payload)
    reg["last_diff_check"] = now_str
    save_reg(reg)
    print(f"\n增量清单已写入: {DIFF_FILE}")
    print(f"读取 {n_csv} 个 CSV: " + ", ".join(os.path.basename(p) for p in paths if os.path.exists(p)))


@reg_locked
def cmd_mark(args):
    reg = load_reg()
    ent = reg["dirs"].get(args.path)
    if ent is None:
        reg["dirs"][args.path] = {"size": 0, "mtime": 0, "tier": args.tier,
                                  "note": args.note, "first_seen": "", "last_seen": "",
                                  "deleted": False, "resurrected": 0}
    else:
        ent["tier"] = args.tier
        ent["note"] = args.note
    save_reg(reg)
    print(f"已标记 {args.path} -> {args.tier}")


def cmd_stats(_):
    reg = load_reg()
    dirs = reg["dirs"]
    tiers = {}
    for ent in dirs.values():
        tiers[ent.get("tier") or "未定性"] = tiers.get(ent.get("tier") or "未定性", 0) + 1
    print(f"档案: {REG_FILE}")
    print(f"更新时间: {reg.get('updated_at')}")
    print(f"目录总数: {len(dirs)}")
    for k, v in sorted(tiers.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")


def main():
    ap = argparse.ArgumentParser(description="目录定性档案引擎")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("baseline")
    p.add_argument("--csv", nargs="+", default=None,
                   help="一个或多个 Everything CSV；缺省自动发现 %%TEMP%%\\scan_*.csv")
    p.add_argument("--min-mb", type=int, default=20)
    p.set_defaults(func=cmd_baseline)

    p = sub.add_parser("diff")
    p.add_argument("--csv", nargs="+", default=None,
                   help="一个或多个 Everything CSV；缺省自动发现 %%TEMP%%\\scan_*.csv")
    p.add_argument("--min-mb", type=int, default=20)
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("mark")
    p.add_argument("path")
    p.add_argument("tier", choices=["green", "yellow", "red", "keep"])
    p.add_argument("note")
    p.set_defaults(func=cmd_mark)

    p = sub.add_parser("stats")
    p.set_defaults(func=cmd_stats)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
