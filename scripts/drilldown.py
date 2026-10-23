#!/usr/bin/env python3
"""Read-only directory drilldown helper for storage-analyzer.

Takes a path and shows immediate children with sizes, sorted descending.
Useful for exploring "mystery directories" during the analysis phase without
the agent having to write ad-hoc Python one-liners.

Usage:
    python drilldown.py <path> [--min-mb 50] [--depth 1] [--limit 30]

Output: JSON array of {name, path, size_kb, size_h, is_dir}
"""

import json
import os
import sys


def human(kb):
    n = float(kb) * 1024
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit not in ("B", "KB") else f"{int(n)} {unit}"
        n /= 1024


def dir_size_bytes(path):
    total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_symlink():
                        continue
                    if e.is_file(follow_symlinks=False):
                        total += e.stat(follow_symlinks=False).st_size
                    elif e.is_dir(follow_symlinks=False):
                        total += dir_size_bytes(e.path)
                except (PermissionError, OSError):
                    continue
    except (PermissionError, OSError):
        pass
    return total


def drilldown(path, min_kb=51200, limit=30):
    if not os.path.isdir(path):
        print(json.dumps({"error": "not_a_directory", "path": path}, ensure_ascii=False))
        return

    results = []
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        print(json.dumps({"error": "permission_denied", "path": path}, ensure_ascii=False))
        return

    for name in entries:
        if name in (".", ".."):
            continue
        child = os.path.join(path, name)
        if os.path.islink(child):
            continue
        try:
            if os.path.isfile(child):
                kb = os.path.getsize(child) // 1024
                is_dir = False
            elif os.path.isdir(child):
                kb = dir_size_bytes(child) // 1024
                is_dir = True
            else:
                continue
        except (PermissionError, OSError):
            continue
        if kb < min_kb:
            continue
        results.append({
            "name": name,
            "path": child,
            "size_kb": kb,
            "size_h": human(kb),
            "is_dir": is_dir,
        })

    results.sort(key=lambda r: r["size_kb"], reverse=True)
    # Summary line for total
    total_kb = sum(r["size_kb"] for r in results)
    output = {
        "path": path,
        "total_visible_kb": total_kb,
        "total_visible_h": human(total_kb),
        "item_count": len(results),
        "children": results[:limit],
    }
    if len(results) > limit:
        output["truncated"] = True
        output["omitted_count"] = len(results) - limit
    print(json.dumps(output, ensure_ascii=False, indent=2))


def parse_args():
    args = {"min_kb": 51200, "limit": 30}
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--min-mb" and i + 1 < len(sys.argv):
            args["min_kb"] = int(sys.argv[i + 1]) * 1024
            i += 2
        elif sys.argv[i] == "--limit" and i + 1 < len(sys.argv):
            args["limit"] = int(sys.argv[i + 1])
            i += 2
        else:
            if "path" not in args:
                args["path"] = sys.argv[i]
            i += 1
    return args


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    a = parse_args()
    drilldown(a.get("path", ""), min_kb=a["min_kb"], limit=a["limit"])
