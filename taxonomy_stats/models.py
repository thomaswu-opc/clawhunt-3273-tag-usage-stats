"""引用来源与统计结果的数据结构。

四个引用来源是工单里点名的：企业（company）、供需条目（supply_demand）、
能力卡（capability_card）、活动（activity）。统计口径固定为「按来源分别计数 + 总数」，
外加「近 30 天新增引用数」—— 后者是给知识管理员判断热度的，不参与总数。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

SOURCES = ("company", "supply_demand", "capability_card", "activity")
WINDOW_DAYS = 30


@dataclass(frozen=True)
class TagRef:
    """一条引用事实：某标签被某个来源的某条业务对象引用了一次。"""

    tag_id: str
    source: str
    ref_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError("unknown_source:%s" % self.source)


@dataclass
class TagStat:
    """taxonomy_tag_stats 的一行：一个标签在一个统计日的结果。"""

    tag_id: str
    dict_code: str
    stat_date: date
    counts: dict[str, int] = field(default_factory=lambda: {s: 0 for s in SOURCES})
    total: int = 0
    new_30d: int = 0

    def to_row(self) -> dict:
        return {
            "tag_id": self.tag_id,
            "dict_code": self.dict_code,
            "stat_date": self.stat_date.isoformat(),
            "counts": dict(self.counts),
            "total": self.total,
            "new_30d": self.new_30d,
        }


def window_start(stat_date: date, days: int = WINDOW_DAYS) -> datetime:
    """近 N 天窗口的起点（含）。stat_date 当天按 UTC 00:00 起算。"""
    base = datetime(stat_date.year, stat_date.month, stat_date.day, tzinfo=timezone.utc)
    return base - timedelta(days=days - 1)
