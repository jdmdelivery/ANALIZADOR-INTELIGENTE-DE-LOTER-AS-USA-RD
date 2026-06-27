"""Rango de días y hash de datos en predicción."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_test_db = os.path.join(tempfile.gettempdir(), "lottery_test_analysis_range.db")
os.environ["DATABASE_PATH"] = _test_db

from datetime import datetime, timedelta

from models import format_numbers, get_lottery_by_slug, init_db, upsert_result  # noqa: E402
from services.recommendations.data_hash import hash_draw_rows  # noqa: E402
from services.recommendations.data_loader import load_draw_history  # noqa: E402
from services.recommendations.engine import generate_recommendation  # noqa: E402


class AnalysisRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_test_db):
            os.remove(_test_db)
        init_db()
        cls.lot = get_lottery_by_slug("rd_nacional")

    def _seed(self, n: int):
        base = datetime.now()
        for i in range(n):
            dd = (base - timedelta(days=i)).strftime("%Y-%m-%d")
            upsert_result(
                self.lot["id"],
                "tarde",
                "14:30",
                dd,
                format_numbers([f"{i:02d}", f"{(i+1)%100:02d}", f"{(i+2)%100:02d}"]),
                fuente="test",
            )

    def test_days_7_limits_draws(self):
        self._seed(20)
        ctx = load_draw_history(self.lot["id"], "tarde", days=7)
        self.assertTrue(ctx["ok"])
        self.assertLessEqual(ctx["total_resultados_usados"], 8)

    def test_hash_changes_on_new_row(self):
        self._seed(12)
        h1 = load_draw_history(self.lot["id"], "tarde", days=365)["hash_datos_usados"]
        upsert_result(
            self.lot["id"], "tarde", "14:30", "2099-12-31",
            format_numbers(["99", "98", "97"]), fuente="test",
        )
        h2 = load_draw_history(self.lot["id"], "tarde", days=365)["hash_datos_usados"]
        self.assertNotEqual(h1, h2)

    def test_different_ranges_can_differ(self):
        self._seed(30)
        r7 = generate_recommendation(self.lot["id"], "tarde", days=7)
        r90 = generate_recommendation(self.lot["id"], "tarde", days=90)
        self.assertTrue(r7.get("ok"))
        self.assertTrue(r90.get("ok"))
        self.assertLessEqual(r7["total_resultados_usados"], 8)
        self.assertGreaterEqual(r90["total_resultados_usados"], 7)
        self.assertNotEqual(r7.get("hash_datos_usados"), r90.get("hash_datos_usados"))


if __name__ == "__main__":
    unittest.main()
