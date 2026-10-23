#!/usr/bin/env python3
"""Inject an analysis JSON into the HTML template -> a standalone report.

Usage:
    build_report.py <analysis.json> [output.html]

The analysis JSON is produced by Claude after interpreting scan.py output.
Schema (all sections optional except system):

{
  "generated_at": "2026-05-28 12:00:00",
  "scan_seconds": 42.1,
  "system": {os, build, arch, user, home, filesystem,
             disk_total, disk_used, disk_free, purgeable},
  "top5": [{rank, tier(green|yellow|red), size, type, name, path, note}],
  "green":  [{name, path, size_estimate, kill_processes:[], trash_paths:[...], commands:[{label,cmd}]}],
  "yellow": [{name, path, size, content_profile, why_manual, disposal, risk, trash_paths:[...]?, open_note?}],
  "red":    [{name, path, size, why_keep, indirect_release, auto_reclaim, app_paths:[...]?}],
  "denied": ["/path/one", ...],
  "summary": {overview, tier_stats:{green,yellow,red}, priority:[...], long_term:[...]}
}
"""
import argparse
import json
import os
import sys

import history
from report_util import json_for_script

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "assets", "report_template.html")


def main():
    ap = argparse.ArgumentParser(description="生成静态存储分析报告")
    ap.add_argument("src", help="analysis JSON")
    ap.add_argument("out", nargs="?", default=os.path.expanduser("~/Desktop/storage-report.html"))
    ap.add_argument("--diff", default=None, help="registry.py diff 写出的 last_diff.json")
    ap.add_argument("--registry", default=None, help="state/registry.json")
    ap.add_argument("--no-history", action="store_true", help="不标注新增/复发与活跃度")
    args = ap.parse_args()

    with open(args.src, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not args.no_history:
        try:
            stats = history.annotate(data, reg_path=args.registry, diff_path=args.diff)
            print(f"增量标注: 新发现 {stats['new']} | 删后复发 {stats['resurrected']} "
                  f"| 活跃度 {stats['activity']} | 档案命中 {stats['known']}")
        except Exception as e:
            print(f"增量标注跳过: {e}", file=sys.stderr)
    with open(TEMPLATE, "r", encoding="utf-8") as f:
        tpl = f.read()

    blob = json_for_script(data)
    # 静态报告不带删除能力（DELETE=null），删除按钮只在 server.py 服务时出现
    html = tpl.replace("__REPORT_DATA__", blob).replace("__DELETE_CONFIG__", "null")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"报告已生成: {args.out}")


if __name__ == "__main__":
    main()
