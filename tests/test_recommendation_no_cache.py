"""Recomendaciones siempre frescas — sin caché ni reutilización."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_test_db = os.path.join(tempfile.gettempdir(), "lottery_test_rec_nocache.db")
os.environ["DATABASE_PATH"] = _test_db

from models import format_numbers, get_lottery_by_slug, init_db, parse_numbers, upsert_result  # noqa: E402
from services.recommendations.engine import (  # noqa: E402
    DATA_SOURCE_LABEL,
    generate_recommendation,
)
from services.recommendations.data_loader import load_draw_history  # noqa: E402


def _seed_quiniela(n=12):
    lot = get_lottery_by_slug("rd_loteka")
    for i in range(n):
        upsert_result(
            lot["id"],
            "noche",
            "20:00" if i % 2 == 0 else "21:00",
            f"2026-05-{10 + i:02d}",
            format_numbers([f"{(i * 3) % 100:02d}", f"{(i * 7) % 100:02d}", f"{(i * 11) % 100:02d}"]),
            fuente="test",
        )
    return lot


class RecommendationNoCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_test_db):
            os.remove(_test_db)
        init_db()

    def test_never_from_cache(self):
        lot = _seed_quiniela(12)
        r1 = generate_recommendation(lot["id"], "noche")
        r2 = generate_recommendation(lot["id"], "noche")
        self.assertTrue(r1.get("ok"))
        self.assertTrue(r2.get("ok"))
        self.assertFalse(r1.get("from_cache"))
        self.assertFalse(r2.get("from_cache"))
        self.assertEqual(r1.get("data_source"), DATA_SOURCE_LABEL)
        diag = r2.get("analyzer_diagnostic") or {}
        self.assertEqual(diag.get("source"), DATA_SOURCE_LABEL)

    def test_uses_latest_result_after_insert(self):
        lot = _seed_quiniela(12)
        before = generate_recommendation(lot["id"], "noche")
        upsert_result(
            lot["id"],
            "noche",
            "22:30",
            "2099-12-31",
            format_numbers(["99", "98", "97"]),
            fuente="test",
        )
        after = generate_recommendation(lot["id"], "noche")
        self.assertEqual(after.get("analyzer_diagnostic", {}).get("last_result_date"), "2099-12-31")
        self.assertNotEqual(
            before.get("analyzer_diagnostic", {}).get("last_result_date"),
            after.get("analyzer_diagnostic", {}).get("last_result_date"),
        )

    def test_sql_orders_by_date_and_time_desc(self):
        lot = _seed_quiniela(12)
        upsert_result(
            lot["id"],
            "noche",
            "12:00",
            "2099-06-01",
            format_numbers(["44", "55", "66"]),
            fuente="test",
        )
        upsert_result(
            lot["id"],
            "noche",
            "23:59",
            "2099-06-02",
            format_numbers(["11", "22", "33"]),
            fuente="test",
        )
        from models import get_results_for_analysis
        rows = get_results_for_analysis(lot["id"], "noche", limit=5)
        first_nums = parse_numbers(rows[0].get("numbers"))
        self.assertEqual(first_nums, ["11", "22", "33"])

    def test_has_analyzer_log_fields(self):
        lot = _seed_quiniela(12)
        r = generate_recommendation(lot["id"], "noche")
        diag = r.get("analyzer_diagnostic") or {}
        self.assertIn("last_result_used", diag)
        self.assertIn("draws_analyzed", diag)
        self.assertIn("recalculated_at", diag)
        self.assertGreaterEqual(diag.get("draws_analyzed", 0), 12)


if __name__ == "__main__":
    unittest.main()
