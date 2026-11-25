"""用例层：只返回 (status_code, body)，不依赖 Web 框架。

- GET /api/taxonomy/tags/{id}/stats  单标签统计
- GET /api/taxonomy/dicts/{code}/stats  字典级：引用最多 + 零引用列表（供知识管理员清理）
"""
from __future__ import annotations

from taxonomy_stats.aggregate import top_tags, zero_ref_tags
from taxonomy_stats.store import MemoryStore


def handle_tag_stats(store: MemoryStore, tag_id: str) -> tuple[int, dict]:
    if tag_id not in store.tags:
        return 404, {"error": "TAG_NOT_FOUND", "message": "标签不存在：%s" % tag_id}
    stat = store.latest_for(tag_id)
    if stat is None:
        return 404, {"error": "STATS_NOT_READY", "message": "该标签尚无统计结果，等待每日任务"}
    return 200, stat.to_row()


def handle_dict_stats(store: MemoryStore, dict_code: str, limit: int = 10) -> tuple[int, dict]:
    known = {t for t, code in store.tags.items() if code == dict_code}
    if not known:
        return 404, {"error": "DICT_NOT_FOUND", "message": "字典不存在或无标签：%s" % dict_code}
    latest = store.latest_day()
    if latest is None:
        return 404, {"error": "STATS_NOT_READY", "message": "尚无统计结果"}
    rows = [s for s in store.day_rows(latest) if s.dict_code == dict_code]
    return 200, {
        "dict_code": dict_code,
        "stat_date": latest.isoformat(),
        "top_referenced": top_tags(rows, limit),
        "zero_reference": zero_ref_tags(rows),
        "tag_count": len(rows),
    }
