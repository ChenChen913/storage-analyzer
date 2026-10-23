# -*- coding: utf-8 -*-
"""rules.py —— 清理规则引擎（storage-analyzer v3 核心组件）

解决的问题：成套清理失败。靠 agent 现场按文件名模式挑着删，同目录同类文件被漏掉
（实战教训：第四轮删了 9 个 lingma/qoder zip，同目录 28 个 fullLine/CodeGeeX zip 漏网，
第五轮成为「新发现」）。

机制：规则以「目录级」为单位整体命中，绝不挑单个文件。命中结果直接作为绿灯候选
输入分析流程，agent 只需复核定性，不需要枚举文件。

用法：
  python rules.py [--csv <CSV>] [--min-mb 1]

输出 JSON 到 stdout：
  green_candidates     规则直接判绿的成组路径（zip 组/转储组/日志组）
  multi_version_groups  多版本共存组（保留最新，旧版可删）
  cache_families        缓存家族目录组（六件套成套识别）
"""
import os
import re
import sys
import json
import argparse
from collections import defaultdict

# ---------- 规则表：从 2026-10-15 六轮实战提炼，可持续追加 ----------

# 目录基名 -> 纯缓存判定（删了不影响功能，随用再生）
CACHE_BASENAMES = {
    "cache", "caches", "code cache", "gpucache", "shadercache", "grshadercache",
    "dawncache", "component_crx_cache", "extensions_crx_cache", "crashdumps",
    "imagecache", "jcef_cache", "icon-cache", "compile-cache", "cef_cache",
    "webview2cache", "cacheddata", "cachedextensionvsixs", "cachestorage",
    "sharedclientcache", "tmp", "temp", "logs", "log",
}

# 语义化版本目录名（bin 下多版本共存判定）
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")

# 已解压插件目录的判定：plugins 父目录下的已展开子目录不算缓存，zip/_download 才是
PLUGIN_CACHE_RE = re.compile(r"[\\/]plugins[\\/]$", re.IGNORECASE)


def load_csv(csv_path):
    """返回 [(路径, 大小), ...] 全量文件清单"""
    out = []
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
            out.append((p, sz))
    return out


def dsize_from_files(files):
    """文件清单 -> {目录: 直接文件字节} -> 全树"""
    direct = defaultdict(int)
    for p, sz in files:
        d = os.path.dirname(p)
        direct[d] += sz
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
    return tree, direct


def main():
    ap = argparse.ArgumentParser(description="清理规则引擎")
    ap.add_argument("--csv", default=os.path.join(os.environ.get("TEMP", "."), "scan_C.csv"))
    ap.add_argument("--min-mb", type=float, default=1.0)
    args = ap.parse_args()
    min_b = int(args.min_mb * 2**20)

    files = load_csv(args.csv)
    tree, direct = dsize_from_files(files)
    U = os.path.expanduser("~")

    green_candidates = []      # 规则直接判绿的组
    multi_version_groups = []  # 多版本组
    cache_families = []        # 缓存家族组

    # ===== 规则 1：plugins 目录下的 zip / *_download（成套，绝不挑） =====
    plugin_zips = defaultdict(int)   # plugins目录 -> 累计字节
    plugin_files = defaultdict(list)
    for p, sz in files:
        d = os.path.dirname(p)
        if PLUGIN_CACHE_RE.search(d + "\\"):
            fn = os.path.basename(p)
            if fn.endswith(".zip") or (fn.endswith("_download") and not fn.endswith(".json")):
                if sz >= 2**20:  # 单文件 >= 1MB 才记
                    plugin_zips[d] += sz
                    plugin_files[d].append((fn, sz))
    for d, sz in sorted(plugin_zips.items(), key=lambda x: -x[1]):
        if sz >= min_b:
            green_candidates.append({
                "rule": "plugins_zip_cache",
                "path": d,
                "size_bytes": sz,
                "files": [{"name": n, "size_bytes": s} for n, s in
                          sorted(plugin_files[d], key=lambda x: -x[1])],
                "note": "插件下载缓存：zip 与 *_download 均为安装残留，插件本体已解压至 Roaming 对应目录",
            })

    # ===== 规则 2：bin 下语义化多版本目录（保留最新） =====
    # 收集 bin 父目录 -> {版本: 大小}
    bins = defaultdict(dict)
    for d, sz in tree.items():
        parent, base = os.path.split(d)
        if SEMVER_RE.match(base) and parent.rstrip("\\").endswith("bin"):
            if sz >= min_b:
                bins[parent][base] = sz
    for parent, vers in bins.items():
        if len(vers) >= 2:
            # 语义化版本排序：2.6.10 > 2.6.9（字符串比较会错）
            def ver_key(v):
                try:
                    return tuple(int(x) for x in v.split("."))
                except ValueError:
                    return (0,)
            newest = max(vers, key=ver_key)
            multi_version_groups.append({
                "rule": "multi_version_bin",
                "path": parent,
                "keep": newest,
                "removable": [{"version": v, "size_bytes": s} for v, s in
                              sorted(vers.items(), key=lambda x: ver_key(x[0]), reverse=True)
                              if v != newest],
                "note": f"多版本共存，保留最新 {newest}，其余旧版本为更新机制不清理的残留",
            })

    # ===== 规则 3：崩溃转储目录 =====
    for d, sz in tree.items():
        base = os.path.basename(d).lower()
        if base in ("crashdumps", "dumps", "minidump") and sz >= min_b:
            green_candidates.append({
                "rule": "crash_dumps",
                "path": d,
                "size_bytes": sz,
                "note": "程序崩溃转储，仅用于事后排查，删除无任何影响",
            })

    # ===== 规则 4：缓存家族目录（成套识别，整体进绿灯候选） =====
    for d, sz in tree.items():
        base = os.path.basename(d).lower()
        if base in CACHE_BASENAMES and sz >= min_b:
            cache_families.append({"path": d, "size_bytes": sz})

    # ===== 规则 5：单文件巨型日志 =====
    big_logs = []
    for p, sz in files:
        if p.lower().endswith(".log") and sz >= 20 * 2**20:
            big_logs.append({"path": p, "size_bytes": sz})
    for e in sorted(big_logs, key=lambda x: -x["size_bytes"])[:20]:
        green_candidates.append({
            "rule": "big_log_file",
            "path": e["path"],
            "size_bytes": e["size_bytes"],
            "note": "单文件 >= 20MB 的日志，删除不影响应用运行",
        })

    result = {
        "green_candidates": sorted(green_candidates, key=lambda x: -x["size_bytes"]),
        "multi_version_groups": sorted(multi_version_groups,
                                        key=lambda x: -sum(v["size_bytes"] for v in x["removable"])),
        "cache_families": sorted(cache_families, key=lambda x: -x["size_bytes"]),
        "summary": {
            "green_groups": len(green_candidates),
            "green_bytes": sum(g["size_bytes"] for g in green_candidates),
            "multi_version_groups": len(multi_version_groups),
            "multi_version_removable_bytes": sum(
                v["size_bytes"] for g in multi_version_groups for v in g["removable"]),
            "cache_family_dirs": len(cache_families),
            "cache_family_bytes": sum(c["size_bytes"] for c in cache_families),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
