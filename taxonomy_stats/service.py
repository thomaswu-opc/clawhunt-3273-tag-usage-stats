"""每日统计任务：跑一次，写一天。重复跑同一天，结果必须一模一样。

幂等不是靠"查一下有没有再插"，而是靠**替换语义**：先删该 stat_date 的全部行，再整批写入。
这样即使上次跑到一半失败、或上游引用数据被补录，重跑也能收敛到同一份结果（AC-3）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

from taxonomy_stats.aggregate import aggregate
from taxonomy_stats.models import TagStat
from taxonomy_stats.store import MemoryStore


def run_daily(store: MemoryStore, stat_date: date, days: int = 30) -> dict:
    """执行一天的统计，返回可直接比对的摘要（用于证明幂等）。"""
    rows: dict[str, TagStat] = aggregate(store.refs, store.tags, stat_date, days)
    store.replace_day(stat_date, rows)
    payload = [r.to_row() for r in store.day_rows(stat_date)]
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {
        "stat_date": stat_date.isoformat(),
        "tag_count": len(payload),
        "total_refs": sum(r["total"] for r in payload),
        "row_count": len(payload),
        "digest": digest,
    }
