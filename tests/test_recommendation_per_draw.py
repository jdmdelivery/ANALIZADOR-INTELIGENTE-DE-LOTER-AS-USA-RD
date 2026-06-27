"""Predicción por tanda — último resultado y números distintos por horario."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_test_db = os.path.join(tempfile.gettempdir(), "lottery_test_per_draw_pred.db")
os.environ["DATABASE_PATH"] = _test_db

from analysis import _resolve_draw_name_for_lottery  # noqa: E402
from models import format_numbers, get_lottery_by_slug, init_db, upsert_result  # noqa: E402
from services.recommendations.engine import generate_recommendation  # noqa: E402


class PerDrawPredictionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_test_db):
            os.remove(_test_db)
        init_db()
        cls.lot = get_lottery_by_slug("rd_nacional")

    def _seed_draw(self, draw_name: str, draw_time: str, n: int = 12):
        for i in range(n):
            upsert_result(
                self.lot["id"],
                draw_name,
                draw_time,
                f"2026-04-{10 + i:02d}",
                format_numbers([
                    f"{(i * 3 + ord(draw_name[0])) % 100:02d}",
                    f"{(i * 7 + 11) % 100:02d}",
                    f"{(i * 11 + 22) % 100:02d}",
                ]),
                fuente="test",
            )

    def test_resolve_6pm_to_tardia(self):
        resolved = _resolve_draw_name_for_lottery(self.lot, "6:00 PM")
        self.assertEqual(resolved, "tardía")

    def test_resolve_tardia_accent(self):
        self.assertEqual(_resolve_draw_name_for_lottery(self.lot, "tardía"), "tardía")
        self.assertEqual(_resolve_draw_name_for_lottery(self.lot, "tardia"), "tardía")

    def test_latest_result_differs_by_draw(self):
        self._seed_draw("tarde", "14:30", 12)
        self._seed_draw("tardía", "18:00", 12)
        upsert_result(
            self.lot["id"], "tarde", "14:30", "2199-06-02",
            format_numbers(["01", "02", "03"]), fuente="test",
        )
        upsert_result(
            self.lot["id"], "tardía", "18:00", "2199-06-01",
            format_numbers(["88", "89", "90"]), fuente="test",
        )
        r_tarde = generate_recommendation(self.lot["id"], "tarde")
        r_tardia = generate_recommendation(self.lot["id"], "tardía")
        self.assertTrue(r_tarde.get("ok"))
        self.assertTrue(r_tardia.get("ok"))
        self.assertEqual(r_tarde["hora_usada"], "14:30")
        self.assertEqual(r_tardia["hora_usada"], "18:00")
        self.assertEqual(r_tarde["fecha_usada"], "2199-06-02")
        self.assertEqual(r_tardia["fecha_usada"], "2199-06-01")
        self.assertNotEqual(
            r_tarde.get("numeros_recomendados"),
            r_tardia.get("numeros_recomendados"),
        )

    def test_insufficient_history_per_draw(self):
        self._seed_draw("noche", "21:00", 3)
        r = generate_recommendation(self.lot["id"], "noche")
        self.assertFalse(r.get("ok"))
        self.assertIn("suficientes", (r.get("message") or "").lower())


if __name__ == "__main__":
    unittest.main()
