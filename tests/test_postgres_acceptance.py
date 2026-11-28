"""三条验收标准在 SQLAlchemy 2 持久化实现 + 真实 PostgreSQL 16 上重跑。

运行前提：DATABASE_URL 指向一个已执行 `alembic upgrade head` 的 PostgreSQL 16 库。
未设置时整类跳过（内存口径用例仍在 test_acceptance.py 中零依赖可跑）。
这些用例不调用 create_all —— 表必须由迁移建出来，正是评审要求验证的路径。
"""
from __future__ import annotations

import os
import unittest
from datetime import date

from sqlalchemy import delete
from sqlalchemy.orm import Session

from taxonomy_stats import handlers
from taxonomy_stats.service import run_daily
from taxonomy_stats.sqlalchemy_store import SqlAlchemyStore, TagStatRow

from tests.test_acceptance import HAND, STAT_DATE, SAMPLE_TAGS, seed

DB_URL = os.environ.get("DATABASE_URL", "")


@unittest.skipUnless(DB_URL, "需要 DATABASE_URL（已 alembic upgrade head 的 PostgreSQL 16）")
class PostgresAcceptance(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SqlAlchemyStore(DB_URL)
        with Session(self.store.engine) as session:
            with session.begin():
                session.execute(delete(TagStatRow))  # 每个用例从空表开始
        seed(self.store)

    def test_ac1_postgres_matches_hand_count(self):
        result = run_daily(self.store, STAT_DATE)
        rows = {r.tag_id: r for r in self.store.day_rows(STAT_DATE)}
        self.assertEqual(set(rows), set(HAND))
        for tag_id, expected in HAND.items():
            got = rows[tag_id]
            self.assertEqual(got.counts, expected["counts"], "%s 分来源计数不符" % tag_id)
            self.assertEqual(got.total, expected["total"], "%s 总数不符" % tag_id)
            self.assertEqual(got.new_30d, expected["new_30d"], "%s 近30天新增不符" % tag_id)
        self.assertEqual(sum(r.total for r in rows.values()), 10)
        self.assertEqual(result["row_count"], 6)
        self.assertEqual(self.store.row_count(STAT_DATE), 6, "行数应来自真实表")

    def test_ac1_postgres_outside_window_still_counted(self):
        run_daily(self.store, STAT_DATE)
        row = {r.tag_id: r for r in self.store.day_rows(STAT_DATE)}["T2"]
        self.assertEqual((row.total, row.new_30d), (1, 0))

    def test_ac2_postgres_zero_reference_tags(self):
        run_daily(self.store, STAT_DATE)
        status, body = handlers.handle_dict_stats(self.store, "industry")
        self.assertEqual(status, 200)
        self.assertEqual(body["zero_reference"], ["T5"])
        self.assertEqual(body["tag_count"], 5)
        self.assertEqual([x["tag_id"] for x in body["top_referenced"]], ["T1", "T4", "T3", "T2"])
        self.assertEqual(body["top_referenced"][0]["total"], 3)

    def test_ac3_postgres_rerun_is_idempotent(self):
        first = run_daily(self.store, STAT_DATE)
        rows_after_first = [r.to_row() for r in self.store.day_rows(STAT_DATE)]
        second = run_daily(self.store, STAT_DATE)
        rows_after_second = [r.to_row() for r in self.store.day_rows(STAT_DATE)]

        self.assertEqual(first["digest"], second["digest"])
        self.assertEqual(first["row_count"], second["row_count"])
        self.assertEqual(second["row_count"], 6)
        self.assertEqual(rows_after_first, rows_after_second)
        self.assertEqual(self.store.row_count(), 6, "重跑不得插重行（直接查库）")

        run_daily(self.store, date(2026, 11, 26))
        self.assertEqual(self.store.row_count(STAT_DATE), 6)
        self.assertEqual(self.store.row_count(date(2026, 11, 26)), 6)
        self.assertEqual(self.store.row_count(), 12, "跑新的一天不动旧的一天")

    def test_read_handlers_query_table_not_memory(self):
        """新开一个没有任何内存统计的 store，接口仍能读出刚落库的结果。"""
        run_daily(self.store, STAT_DATE)
        fresh = SqlAlchemyStore(DB_URL)
        for tag_id, dict_code in SAMPLE_TAGS:
            fresh.add_tag(tag_id, dict_code)   # 只提供上游标签登记，不提供 refs / stats

        status, body = handlers.handle_tag_stats(fresh, "T1")
        self.assertEqual(status, 200)
        self.assertEqual(body["counts"], HAND["T1"]["counts"])
        self.assertEqual(body["total"], HAND["T1"]["total"])
        status, body = handlers.handle_dict_stats(fresh, "industry")
        self.assertEqual(status, 200)
        self.assertEqual(body["zero_reference"], ["T5"])
        self.assertEqual(body["tag_count"], 5)
        self.assertEqual(handlers.handle_tag_stats(fresh, "NOPE")[0], 404)

    def test_http_endpoints_against_persisted_table(self):
        try:
            from fastapi.testclient import TestClient
        except Exception:  # pragma: no cover
            self.skipTest("需要 fastapi + httpx")
        from taxonomy_stats.routes import create_app

        run_daily(self.store, STAT_DATE)
        client = TestClient(create_app(self.store))
        r = client.get("/api/taxonomy/tags/T3/stats")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["total"], 2)
        r = client.get("/api/taxonomy/dicts/industry/stats")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["zero_reference"], ["T5"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
