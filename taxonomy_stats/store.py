"""存储边界：标签、引用事实、统计结果。

统计结果按 (tag_id, stat_date) 唯一。写入用「先删该日全部、再整批插入」的替换语义，
这样重复运行同一个 stat_date 一定得到同一份数据，不会累积重复行（AC-3 的结构性保证）。
"""
from __future__ import annotations

import copy
from datetime import date

from taxonomy_stats.models import TagRef, TagStat


class MemoryStore:
    def __init__(self) -> None:
        self.tags: dict[str, str] = {}                 # tag_id -> dict_code
        self.refs: list[TagRef] = []
        self.stats: dict[tuple[str, str], TagStat] = {}  # (tag_id, iso_date) -> stat

    # --- 写入事实 -------------------------------------------------------
    def add_tag(self, tag_id: str, dict_code: str) -> None:
        self.tags[tag_id] = dict_code

    def add_ref(self, ref: TagRef) -> None:
        self.refs.append(ref)

    # --- 统计结果 -------------------------------------------------------
    def replace_day(self, stat_date: date, rows: dict[str, TagStat]) -> None:
        key_date = stat_date.isoformat()
        stale = [k for k in self.stats if k[1] == key_date]
        for k in stale:
            del self.stats[k]
        for tag_id, stat in rows.items():
            self.stats[(tag_id, key_date)] = copy.deepcopy(stat)

    def day_rows(self, stat_date: date) -> list[TagStat]:
        key_date = stat_date.isoformat()
        return [copy.deepcopy(s) for k, s in sorted(self.stats.items()) if k[1] == key_date]

    def latest_for(self, tag_id: str) -> TagStat | None:
        hits = [(k[1], s) for k, s in self.stats.items() if k[0] == tag_id]
        if not hits:
            return None
        return copy.deepcopy(max(hits, key=lambda x: x[0])[1])

    def latest_day(self) -> date | None:
        if not self.stats:
            return None
        return max(date.fromisoformat(k[1]) for k in self.stats)
