"""Tests módulo Historial de Precisión del Analizador."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_test_db = os.path.join(tempfile.gettempdir(), "lottery_test_precision.db")
os.environ["DATABASE_PATH"] = _test_db

from models import init_db, get_lottery_by_slug, upsert_result, format_numbers  # noqa: E402
from services.precision.comparator import compare_recommendation  # noqa: E402
from services.precision.evaluator import on_official_result_saved  # noqa: E402
from services.precision.storage import save_precision_recommendation  # noqa: E402


class PrecisionComparatorTests(unittest.TestCase):
    def test_quiniela_full_hit(self):
        r = compare_recommendation(
            ["47", "46", "28"],
            ["47", "46", "28"],
            game_family="quiniela_rd",
        )
        self.assertEqual(r["hit_percentage"], 100.0)
        self.assertEqual(r["status"], "excelente")
        self.assertTrue(r["detail"]["position_results"][0]["hit"])

    def test_quiniela_partial_hit(self):
        r = compare_recommendation(
            ["47", "46", "55"],
            ["47", "46", "28"],
            game_family="quiniela_rd",
        )
        self.assertAlmostEqual(r["hit_percentage"], 66.7)
        self.assertFalse(r["detail"]["position_results"][2]["hit"])

    def test_pick_exact_and_box(self):
        r = compare_recommendation(
            ["1", "2", "3"],
            ["1", "2", "3"],
            game_family="pick",
        )
        self.assertTrue(r["detail"]["exact_straight"])
        self.assertEqual(r["box_hits"], 3)

        r2 = compare_recommendation(
            ["3", "2", "1"],
            ["1", "2", "3"],
            game_family="pick",
        )
        self.assertFalse(r2["exact_straight"])
        self.assertEqual(r2["box_hits"], 3)

    def test_pick_fireball(self):
        r = compare_recommendation(
            ["1", "2", "3"],
            ["1", "2", "3"],
            predicted_bonus=["5"],
            actual_bonus=["5"],
            game_family="pick",
        )
        self.assertEqual(r["bonus_hits"], 1)
        self.assertTrue(r["detail"]["fireball_hit"])

    def test_powerball_separate(self):
        r = compare_recommendation(
            ["05", "12", "23", "34", "45"],
            ["05", "12", "23", "34", "45"],
            predicted_bonus=["10"],
            actual_bonus=["10"],
            game_family="power_mega",
        )
        self.assertEqual(r["bonus_hits"], 1)
        self.assertIn("special_ball", r["detail"])

    def test_box_hits_multiset(self):
        r = compare_recommendation(
            ["1", "1", "2"],
            ["1", "2", "2"],
            game_family="pick",
        )
        self.assertGreaterEqual(r["box_hits"], 2)


class PrecisionAutoEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_test_db):
            os.remove(_test_db)
        init_db()

    def test_auto_eval_on_result_save(self):
        lot = get_lottery_by_slug("rd_loteka")
        self.assertIsNotNone(lot)
        for i in range(12):
            upsert_result(
                lot["id"],
                "noche",
                "20:00",
                f"2026-04-{10 + i:02d}",
                format_numbers([f"{(i*3)%100:02d}", f"{(i*7)%100:02d}", f"{(i*11)%100:02d}"]),
                fuente="test",
            )

        rec = {
            "ok": True,
            "adapter": "quiniela_rd",
            "game_type": "Quiniela RD",
            "engine": "recommendations_v2",
            "generated_numbers": ["05", "12", "23"],
            "bonus_numbers": [],
            "score": 75,
            "confidence_level": "medio",
            "confidence_label": "Media",
            "history_count": 12,
            "latest_result_date": "2026-04-21",
        }
        run_id = save_precision_recommendation(lot["id"], "noche", "quiniela_rd", rec)
        self.assertIsNotNone(run_id)

        from models import get_connection

        conn = get_connection()
        try:
            conn.execute(
                "UPDATE recommendation_runs SET created_at = ? WHERE id = ?",
                ("2026-04-22 10:00:00", run_id),
            )
            conn.commit()
        finally:
            conn.close()

        actual = format_numbers(["05", "12", "99"])
        rid, _ = upsert_result(
            lot["id"],
            "noche",
            "20:00",
            "2026-05-10",
            actual,
            fuente="test",
        )
        n = on_official_result_saved(lot["id"], "noche", "2026-05-10", rid)
        self.assertGreaterEqual(n, 1)

        from models import get_connection

        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM backtest_results WHERE recommendation_run_id = ?",
                (run_id,),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["position_hits"], 2)
            self.assertIsNotNone(row["hit_percentage"])
            self.assertIsNotNone(row["status_label"])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
