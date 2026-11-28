"""每日统计任务：跑一次，写一天。重复跑同一天，结果必须一模一样。

幂等不是靠"查一下有没有再插"，而是靠**替换语义**：先删该 stat_date 的全部行，再整批写入。
这样即使上次跑到一半失败、或上游引用数据被补录，重跑也能收敛到同一份结果（AC-3）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Protocol

from taxonomy_stats.aggregate import aggregate
from taxonomy_stats.models import TagRef, TagStat


class DailyStore(Protocol):
    """每日任务对存储的依赖面：来源事实 + 按日替换结果 + 读回结果。

    MemoryStore（零依赖口径复现）与 SqlAlchemyStore（PostgreSQL 落库）都满足该协议。
    """

    tags: dict[str, str]
    refs: list[TagRef]

    def replace_day(self, stat_date: date, rows: dict[str, TagStat]) -> None: ...

    def day_rows(self, stat_date: date) -> list[TagStat]: ...


def run_daily(store: DailyStore, stat_date: date, days: int = 30) -> dict:
    """执行一天的统计，返回可直接比对的摘要（用于证明幂等）。

    摘要取自 replace_day() 之后的 day_rows()：持久化实现下是写库再读回的行，
    不是对内存中间结果取哈希，因此 digest 一致也证明落库内容一致。
    """
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
