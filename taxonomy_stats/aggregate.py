"""统计口径：纯函数，不碰存储。

为什么要做成纯函数：AC-1 要求「统计结果与样例数据的手工计数一致」，只有把口径与存储解耦，
这条才能用手算的数字直接验，而不是"跑一遍看看像不像"。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from taxonomy_stats.models import SOURCES, TagRef, TagStat, window_start


def aggregate(
    refs: list[TagRef],
    tags: dict[str, str],
    stat_date: date,
    days: int = 30,
) -> dict[str, TagStat]:
    """按 tag_id 汇总。tags 是 {tag_id: dict_code}，未出现在 tags 里的引用不计数（脏数据不放大）。"""
    start = window_start(stat_date, days)
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {s: 0 for s in SOURCES})
    new_30d: dict[str, int] = defaultdict(int)

    for ref in refs:
        if ref.tag_id not in tags:
            continue
        counts[ref.tag_id][ref.source] += 1
        if ref.created_at >= start:
            new_30d[ref.tag_id] += 1

    out: dict[str, TagStat] = {}
    for tag_id, dict_code in tags.items():
        c = counts[tag_id] or {s: 0 for s in SOURCES}
        out[tag_id] = TagStat(
            tag_id=tag_id,
            dict_code=dict_code,
            stat_date=stat_date,
            counts=dict(c),
            total=sum(c.values()),
            new_30d=new_30d[tag_id],
        )
    return out


def top_tags(stats: list[TagStat], limit: int = 10) -> list[dict]:
    """引用最多：按 total 降序，同分按 tag_id 升序（保证结果稳定，重复运行不变形）。"""
    ranked = sorted(stats, key=lambda s: (-s.total, s.tag_id))
    return [{"tag_id": s.tag_id, "total": s.total} for s in ranked[:limit] if s.total > 0]


def zero_ref_tags(stats: list[TagStat]) -> list[str]:
    """零引用标签：total == 0，按 tag_id 升序。"""
    return sorted(s.tag_id for s in stats if s.total == 0)
