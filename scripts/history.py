# -*- coding: utf-8 -*-
"""history.py —— 报告增量标注（storage-analyzer v3 组件）

把 registry.py diff 写出的 state/last_diff.json 和 state/registry.json 应用到
分析 JSON：给每项标注「新发现 / 删后复发」，并补上最后活动时间。
build_report.py 与 server.py 共用，保证静态报告和网页报告看到同一套增量信息。

用法（由调用方 import）：
  import history
  stats = history.annotate(data)
"""
import os
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.environ.get("STORAGE_ANALYZER_STATE") or os.path.join(HERE, "..", "state")
REG_FILE = os.path.join(STATE_DIR, "registry.json")
DIFF_FILE = os.path.join(STATE_DIR, "last_diff.json")


def _norm(p):
    return os.path.normpath(str(p)).rstrip("\\/").lower()


def _load(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    return {}


def _ancestor(path, keys):
    """path 本身或它的祖先目录是否在 keys 里（keys 已按长度降序）"""
    for k in keys:
        if path == k or path.startswith(k + "\\") or path.startswith(k + "/"):
            return k
    return None


def annotate(data, reg_path=None, diff_path=None):
    reg = _load(reg_path or REG_FILE)
    diff = _load(diff_path or DIFF_FILE)
    dirs = {_norm(k): v for k, v in (reg.get("dirs") or {}).items()}
    dir_keys = sorted(dirs, key=len, reverse=True)
    new_keys = sorted({_norm(x) for x in diff.get("new", [])}, key=len, reverse=True)
    res_keys = sorted({_norm(x) for x in diff.get("resurrected", [])}, key=len, reverse=True)
    stats = {"new": 0, "resurrected": 0, "activity": 0, "known": 0}
    now = time.time()

    for section in ("top5", "green", "yellow", "red"):
        for it in data.get(section) or []:
            if not isinstance(it, dict):
                continue
            p = it.get("path")
            if not p:
                continue
            np = _norm(p)
            if _ancestor(np, res_keys):
                it["history"] = "resurrected"
                stats["resurrected"] += 1
            elif _ancestor(np, new_keys):
                it["history"] = "new"
                stats["new"] += 1
            else:
                it.pop("history", None)

            k = _ancestor(np, dir_keys)
            if k:
                stats["known"] += 1
                m = dirs[k].get("mtime") or 0
                if m:
                    it["last_active"] = time.strftime("%Y-%m-%d", time.localtime(m))
                    it["days_idle"] = max(0, round((now - m) / 86400))
                    stats["activity"] += 1
                    continue
            it.pop("last_active", None)
            it.pop("days_idle", None)
    return stats
