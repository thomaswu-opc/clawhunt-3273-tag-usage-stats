"""三条验收标准的机械验证：手工计数、零引用列表、重复运行不变。"""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from taxonomy_stats import handlers
from taxonomy_stats.aggregate import top_tags
from taxonomy_stats.models import TagRef
from taxonomy_stats.service import run_daily
from taxonomy_stats.store import MemoryStore

STAT_DATE = date(2026, 11, 25)
# 窗口 = 2026-10-27 .. 2026-11-25（含 30 天）


def ts(y, m, d) -> datetime:
    return datetime(y, m, d, 12, 0, tzinfo=timezone.utc)


SAMPLE_TAGS = [("T1", "industry"), ("T2", "industry"), ("T3", "industry"),
               ("T4", "industry"), ("T5", "industry"), ("T6", "service")]

SAMPLE_REFS = [
    ("T1", "company", "c1", ts(2026, 11, 20)),
    ("T1", "company", "c2", ts(2026, 11, 1)),
    ("T1", "supply_demand", "s1", ts(2026, 10, 1)),      # 窗口外
    ("T2", "company", "c3", ts(2026, 9, 15)),            # 窗口外
    ("T3", "supply_demand", "s2", ts(2026, 11, 24)),
    ("T3", "capability_card", "k1", ts(2026, 11, 2)),
    ("T4", "capability_card", "k2", ts(2026, 10, 30)),
    ("T4", "activity", "a1", ts(2026, 11, 10)),
    ("T4", "activity", "a2", ts(2026, 11, 11)),
    ("T6", "activity", "a3", ts(2026, 11, 5)),
]


def seed(store) -> None:
    """给任意 store 灌入同一份样例事实，保证内存/数据库两条路径口径可比。"""
    for tag_id, dict_code in SAMPLE_TAGS:
        store.add_tag(tag_id, dict_code)
    for tag_id, source, ref_id, created in SAMPLE_REFS:
        store.add_ref(TagRef(tag_id=tag_id, source=source, ref_id=ref_id, created_at=created))


def build_store() -> MemoryStore:
    store = MemoryStore()
    seed(store)
    return store


# 手算基线：写死在这里，等于把"人工计数"固化进测试
HAND = {
    #          company supply capability activity  total  new30d
    "T1": dict(counts={"company": 2, "supply_demand": 1, "capability_card": 0, "activity": 0},
               total=3, new_30d=2),
    "T2": dict(counts={"company": 1, "supply_demand": 0, "capability_card": 0, "activity": 0},
               total=1, new_30d=0),
    "T3": dict(counts={"company": 0, "supply_demand": 1, "capability_card": 1, "activity": 0},
               total=2, new_30d=2),
    "T4": dict(counts={"company": 0, "supply_demand": 0, "capability_card": 1, "activity": 2},
               total=3, new_30d=3),
    "T5": dict(counts={"company": 0, "supply_demand": 0, "capability_card": 0, "activity": 0},
               total=0, new_30d=0),
    "T6": dict(counts={"company": 0, "supply_demand": 0, "capability_card": 0, "activity": 1},
               total=1, new_30d=1),
}


class AC1MatchesHandCount(unittest.TestCase):
    def test_ac1_stats_equal_hand_count(self):
        store = build_store()
        run_daily(store, STAT_DATE)
        rows = {r.tag_id: r for r in store.day_rows(STAT_DATE)}
        self.assertEqual(set(rows), set(HAND))
        for tag_id, expected in HAND.items():
            got = rows[tag_id]
            self.assertEqual(got.counts, expected["counts"], "%s 分来源计数不符" % tag_id)
            self.assertEqual(got.total, expected["total"], "%s 总数不符" % tag_id)
            self.assertEqual(got.new_30d, expected["new_30d"], "%s 近30天新增不符" % tag_id)
        self.assertEqual(sum(r.total for r in rows.values()), 10, "总引用数应等于样例引用条数")

    def test_ac1_refs_outside_window_still_count_in_total(self):
        """窗口只影响 new_30d，不影响 total —— 口径容易写反的地方。"""
        store = build_store()
        run_daily(store, STAT_DATE)
        row = {r.tag_id: r for r in store.day_rows(STAT_DATE)}["T2"]
        self.assertEqual((row.total, row.new_30d), (1, 0))


class AC2ZeroReferenceList(unittest.TestCase):
    def test_ac2_zero_reference_tags(self):
        store = build_store()
        run_daily(store, STAT_DATE)
        status, body = handlers.handle_dict_stats(store, "industry")
        self.assertEqual(status, 200)
        self.assertEqual(body["zero_reference"], ["T5"])
        self.assertEqual(body["tag_count"], 5)

    def test_ac2_top_referenced_is_stable_on_ties(self):
        store = build_store()
        run_daily(store, STAT_DATE)
        status, body = handlers.handle_dict_stats(store, "industry")
        self.assertEqual(status, 200)
        self.assertEqual([x["tag_id"] for x in body["top_referenced"]], ["T1", "T4", "T3", "T2"])
        self.assertEqual(body["top_referenced"][0]["total"], 3)


class AC3RerunIsIdempotent(unittest.TestCase):
    def test_ac3_second_run_changes_nothing(self):
        store = build_store()
        first = run_daily(store, STAT_DATE)
        rows_after_first = store.day_rows(STAT_DATE)
        second = run_daily(store, STAT_DATE)
        rows_after_second = store.day_rows(STAT_DATE)

        self.assertEqual(first["digest"], second["digest"], "重复运行 digest 必须一致")
        self.assertEqual(first["row_count"], second["row_count"])
        self.assertEqual(len(store.stats), 6, "不得产生重复行（按 tag_id+stat_date 唯一）")
        self.assertEqual([r.to_row() for r in rows_after_first],
                         [r.to_row() for r in rows_after_second])

    def test_ac3_new_day_does_not_touch_old_day(self):
        store = build_store()
        run_daily(store, STAT_DATE)
        run_daily(store, date(2026, 11, 26))
        self.assertEqual(len(store.day_rows(STAT_DATE)), 6)
        self.assertEqual(len(store.day_rows(date(2026, 11, 26))), 6)
        self.assertEqual(len(store.stats), 12)


class ApiContract(unittest.TestCase):
    def test_tag_stats_200_and_404(self):
        store = build_store()
        run_daily(store, STAT_DATE)
        status, body = handlers.handle_tag_stats(store, "T3")
        self.assertEqual(status, 200)
        self.assertEqual(body["counts"]["supply_demand"], 1)
        self.assertEqual(body["stat_date"], "2026-11-25")
        self.assertEqual(handlers.handle_tag_stats(store, "NOPE")[0], 404)

    def test_stats_not_ready_before_job_runs(self):
        store = build_store()
        self.assertEqual(handlers.handle_tag_stats(store, "T1")[0], 404)
        self.assertEqual(handlers.handle_dict_stats(store, "industry")[0], 404)

    def test_top_tags_limit(self):
        store = build_store()
        run_daily(store, STAT_DATE)
        rows = [r for r in store.day_rows(STAT_DATE) if r.dict_code == "industry"]
        self.assertEqual(len(top_tags(rows, limit=2)), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
