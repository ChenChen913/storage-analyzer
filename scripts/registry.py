# -*- coding: utf-8 -*-
"""registry.py —— 目录定性档案引擎（storage-analyzer v3 核心组件）

解决的问题：跨轮失忆。每轮分析都是「从头再看」，导致同目录同类文件反复成为「新发现」。

用法：
  python registry.py baseline [--csv <CSV>] [--min-mb 20] [--drive C]
      从 CSV 建立/更新档案基线，采集目录大小与活跃度（两层 mtime）。
  python registry.py diff [--csv <CSV>] [--min-mb 20]
      输出增量审计报告：新目录 / 增大目录 / 复活目录 / 未定性目录。
  python registry.py mark <path> <green|yellow|red|keep> "<note>"
      agent 定性后写回档案（防止下轮重复定性）。
  python registry.py stats
      档案统计：已定性/未定性数量、覆盖体积。

档案位置：<skill>\state\registry.json（与 Trae/hermes 经 junction 共享同一份）
CSV 格式："路径",大小（Everything 导出，无表头）；溢出值 >= 2^63 置 0。
"""
import os
import sys
import json
import time
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, "..", "state")
REG_FILE = os.path.join(STATE_DIR, "registry.json")


def load_csv(csv_path):
    """读 Everything CSV -> {目录: 直接文件字节}"""
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


def load_reg():
    if os.path.exists(REG_FILE):
        with open(REG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"version": 1, "updated_at": "", "dirs": {}}


def save_reg(reg):
    os.makedirs(STATE_DIR, exist_ok=True)
    reg["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(REG_FILE, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)


def cmd_baseline(args):
    direct = load_csv(args.csv)
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
            was_deleted = ent.get("deleted", False)
            if was_deleted and sz > 0:
                ent["resurrected"] = ent.get("resurrected", 0) + 1
            ent.update({"size": sz, "last_seen": now, "deleted": False})
            # 活跃度只对变化明显或无记录的重新采集，控制耗时
            if abs(sz - ent.get("size", 0)) > 10 * 2**20 or not ent.get("mtime"):
                ent["mtime"] = mtime2(d)

    # 本轮没见到的 -> deleted
    for d, ent in reg["dirs"].items():
        if d not in seen and not ent.get("deleted"):
            ent["deleted"] = True
            n_gone += 1

    save_reg(reg)
    print(f"基线已更新: {REG_FILE}")
    print(f"档案目录 {len(reg['dirs'])} 个 | 新增 {n_new} | 标记删除 {n_gone}")


def cmd_diff(args):
    if not os.path.exists(args.csv):
        print(f"CSV 不存在: {args.csv}", file=sys.stderr)
        sys.exit(1)
    direct = load_csv(args.csv)
    tree = build_tree(direct)
    reg = load_reg()
    thresh = args.min_mb * 2**20
    now = time.time()

    new_items, grew_items, res_items, unrev_items = [], [], [], []
    for d, sz in tree.items():
        if sz < thresh:
            continue
        ent = reg["dirs"].get(d)
        if ent is None:
            new_items.append((d, sz))
        else:
            delta = sz - ent.get("size", 0)
            if delta >= 50 * 2**20:
                grew_items.append((d, sz, delta))
            if ent.get("resurrected", 0) > 0:
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
    p.add_argument("--csv", default=os.path.join(os.environ.get("TEMP", "."), "scan_C.csv"))
    p.add_argument("--min-mb", type=int, default=20)
    p.add_argument("--drive", default="C")
    p.set_defaults(func=cmd_baseline)

    p = sub.add_parser("diff")
    p.add_argument("--csv", default=os.path.join(os.environ.get("TEMP", "."), "scan_C.csv"))
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
