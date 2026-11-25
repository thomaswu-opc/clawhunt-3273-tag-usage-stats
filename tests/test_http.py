"""HTTP 层用例：需要 fastapi + httpx；缺失时整类跳过，不影响验收用例跑绿。"""
from __future__ import annotations

import unittest

from tests.test_acceptance import STAT_DATE, build_store

try:
    from fastapi.testclient import TestClient

    HAVE_HTTP = True
except Exception:  # noqa: BLE001
    HAVE_HTTP = False


@unittest.skipUnless(HAVE_HTTP, "需要 fastapi + httpx")
class HttpLayer(unittest.TestCase):
    def setUp(self):
        from taxonomy_stats.routes import create_app
        from taxonomy_stats.service import run_daily

        store = build_store()
        run_daily(store, STAT_DATE)
        self.client = TestClient(create_app(store))

    def test_tag_stats_endpoint(self):
        r = self.client.get("/api/taxonomy/tags/T3/stats")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["total"], 2)
        self.assertEqual(r.json()["counts"]["capability_card"], 1)

    def test_dict_stats_endpoint(self):
        r = self.client.get("/api/taxonomy/dicts/industry/stats")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["zero_reference"], ["T5"])
        self.assertEqual(body["top_referenced"][0]["tag_id"], "T1")

    def test_unknown_tag_404(self):
        r = self.client.get("/api/taxonomy/tags/NOPE/stats")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["error"], "TAG_NOT_FOUND")


if __name__ == "__main__":
    unittest.main(verbosity=2)
