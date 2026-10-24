# -*- coding: utf-8 -*-
"""rules.py —— 清理规则引擎（storage-analyzer v3 核心组件）

解决的问题：成套清理失败。靠 agent 现场按文件名模式挑着删，同目录同类文件被漏掉
（实战教训：某一轮只按文件名模式删了少数 zip，同目录其余同类 zip 全部漏网，
下一轮成为「新发现」）。

机制：规则以「目录级」为单位整体命中，绝不挑单个文件。命中结果直接作为绿灯候选
输入分析流程，agent 只需复核定性，不需要枚举文件。

用法：
  python rules.py [--csv <CSV> ...] [--min-mb 1]
  --csv 可传多个文件（如 C、D 两盘）；缺省自动发现 %TEMP%\\scan_*.csv。

输出 JSON 到 stdout：
  green_candidates     规则可直接判绿的成组路径（zip 组/转储组）
  review_candidates    名字宽泛或状态不明、必须人工确认的项（tmp/logs/cache、巨型日志）
  multi_version_groups  多版本共存组（给出建议保留版本，但必须按启动器确认）
  cache_families        具体缓存目录组（六件套成套识别）
"""
import os
import re
import sys
import glob
import json
import argparse
from collections import defaultdict

# ---------- 规则表：从 2026-10-15 六轮实战提炼，可持续追加 ----------

# 具体缓存目录基名 -> 可直接判绿（删了不影响功能，随用再生）
SAFE_CACHE_BASENAMES = {
    "code cache", "gpucache", "shadercache", "grshadercache",
    "dawncache", "component_crx_cache", "extensions_crx_cache", "crashdumps",
    "imagecache", "jcef_cache", "icon-cache", "compile-cache", "cef_cache",
    "webview2cache", "cacheddata", "cachedextensionvsixs", "cachestorage",
    "sharedclientcache", "shared dictionary",
}

# 名字过于宽泛：tmp/logs/cache 也可能是应用正在使用的数据目录，只进待确认
BROAD_CACHE_BASENAMES = {"cache", "caches", "tmp", "temp", "logs", "log"}

# 语义化版本目录名（bin 下多版本共存判定）
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")

# 已解压插件目录的判定：plugins 父目录下的已展开子目录不算缓存，zip/_download 才是
PLUGIN_CACHE_RE = re.compile(r"[\\/]plugins[\\/]$", re.IGNORECASE)


def load_csv(csv_path):
    """返回 [(路径, 大小), ...] 全量文件清单

    用 utf-8-sig 读取：Everything 导出的 CSV 常带 BOM，按固定列偏移截取路径时
    BOM 会顶掉开头的引号，导致同一个目录被拆成两个键（实战中表现为同组缓存
    被拆散、漏删）。"""
    out = []
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
            out.append((p, sz))
    return out


def resolve_csvs(arg_csv):
    if arg_csv:
        return arg_csv
    temp = os.environ.get("TEMP") or os.environ.get("TMP") or "."
    found = sorted(glob.glob(os.path.join(temp, "scan_*.csv")))
    return found or [os.path.join(temp, "scan_C.csv")]


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
    ap.add_argument("--csv", nargs="+", default=None,
                    help="一个或多个 Everything CSV；缺省自动发现 %%TEMP%%\\scan_*.csv")
    ap.add_argument("--min-mb", type=float, default=1.0)
    ap.add_argument("--out", default="",
                    help="把 JSON 写入文件（UTF-8 无 BOM），避免 PowerShell 重定向产生 BOM")
    args = ap.parse_args()
    min_b = int(args.min_mb * 2**20)

    paths = resolve_csvs(args.csv)
    files = []
    used = 0
    for p in paths:
        if not os.path.exists(p):
            print(f"CSV 不存在，跳过: {p}", file=sys.stderr)
            continue
        used += 1
        files.extend(load_csv(p))
    if not used:
        print("没有可用的 CSV", file=sys.stderr)
        sys.exit(1)
    tree, direct = dsize_from_files(files)
    U = os.path.expanduser("~")

    green_candidates = []      # 规则直接判绿的组
    review_candidates = []     # 需人工确认的组
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
            # 语义化版本排序：2.6.10 > 2.6.9；带 -beta/-rc 的同版本排在稳定版之后。
            def ver_key(v):
                m = re.match(r"^(\d+(?:\.\d+)*)", v)
                nums = tuple(int(x) for x in m.group(1).split(".")) if m else ()
                prerelease = bool(re.search(
                    r"(?i)(alpha|beta|rc|pre|dev|snapshot|nightly)", v))
                return (nums, 0 if prerelease else 1)
            newest = max(vers, key=ver_key)
            multi_version_groups.append({
                "rule": "multi_version_bin",
                "path": parent,
                "keep": newest,
                "confidence": "needs_review",
                "removable": [{"version": v, "size_bytes": s} for v, s in
                              sorted(vers.items(), key=lambda x: ver_key(x[0]), reverse=True)
                              if v != newest],
                "note": f"多版本共存，按版本号最新的是 {newest}；仅凭目录名不能确认"
                        "当前版本，必须查启动器/配置/快捷方式指向后再决定旧版是否可删",
            })

    # ===== 规则 3：崩溃转储目录 =====
    for d, sz in tree.items():
        base = os.path.basename(d).lower()
        if base in ("crashdumps", "minidump") and sz >= min_b:
            green_candidates.append({
                "rule": "crash_dumps",
                "path": d,
                "size_bytes": sz,
                "note": "程序崩溃转储，仅用于事后排查，删除无任何影响",
            })
        elif base == "dumps" and sz >= min_b:
            review_candidates.append({
                "rule": "ambiguous_dumps",
                "path": d,
                "size_bytes": sz,
                "note": "名字只叫 dumps，可能是崩溃转储，也可能是应用数据备份，需看内容",
            })

    # ===== 规则 4：缓存家族目录（具体名直接判绿，宽泛名只进待确认） =====
    for d, sz in tree.items():
        if sz < min_b:
            continue
        base = os.path.basename(d).lower()
        if base in SAFE_CACHE_BASENAMES:
            cache_families.append({"path": d, "size_bytes": sz})
        elif base in BROAD_CACHE_BASENAMES:
            review_candidates.append({
                "rule": "broad_cache_name",
                "path": d,
                "size_bytes": sz,
                "note": "目录名宽泛（cache/tmp/logs 等），可能是纯缓存，也可能是应用正在使用的数据，需逐目录看内容",
            })

    # ===== 规则 5：单文件巨型日志（可能正在写入，只进待确认） =====
    big_logs = []
    for p, sz in files:
        if p.lower().endswith(".log") and sz >= 20 * 2**20:
            big_logs.append({"path": p, "size_bytes": sz})
    for e in sorted(big_logs, key=lambda x: -x["size_bytes"])[:20]:
        review_candidates.append({
            "rule": "big_log_file",
            "path": e["path"],
            "size_bytes": e["size_bytes"],
            "note": "单文件 >= 20MB 的日志；先确认没有进程正在写入，再决定是否清空或删除",
        })

    result = {
        "green_candidates": sorted(green_candidates, key=lambda x: -x["size_bytes"]),
        "review_candidates": sorted(review_candidates, key=lambda x: -x["size_bytes"]),
        "multi_version_groups": sorted(multi_version_groups,
                                        key=lambda x: -sum(v["size_bytes"] for v in x["removable"])),
        "cache_families": sorted(cache_families, key=lambda x: -x["size_bytes"]),
        "summary": {
            "csv_files": used,
            "green_groups": len(green_candidates),
            "green_bytes": sum(g["size_bytes"] for g in green_candidates),
            "review_groups": len(review_candidates),
            "review_bytes": sum(g["size_bytes"] for g in review_candidates),
            "multi_version_groups": len(multi_version_groups),
            "multi_version_removable_bytes": sum(
                v["size_bytes"] for g in multi_version_groups for v in g["removable"]),
            "cache_family_dirs": len(cache_families),
            "cache_family_bytes": sum(c["size_bytes"] for c in cache_families),
        },
    }
    blob = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(blob)
        print("rules written to %s" % args.out, file=sys.stderr)
    else:
        print(blob)


if __name__ == "__main__":
    main()
