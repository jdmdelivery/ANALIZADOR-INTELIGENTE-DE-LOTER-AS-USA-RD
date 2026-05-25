"""Pruebas recomendación LEIDSA por cantidad y duplicados."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_test_db = os.path.join(tempfile.gettempdir(), "lottery_test_leidsa_rec.db")
os.environ["DATABASE_PATH"] = _test_db

from models import init_db, get_lottery_by_slug, upsert_result, format_numbers  # noqa: E402
from services.leidsa_config import (  # noqa: E402
    resolve_leidsa_recommendation_config,
    LEIDSA_RECOMMENDATION_CONFIG,
)
from analysis import (  # noqa: E402
    _find_duplicate_numbers,
    _pick_numbers,
    _resolve_analysis_config,
    debug_leidsa_recommendation,
    generar_jugada_inteligente,
)


class LeidsaRecommendationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_test_db):
            os.remove(_test_db)
        init_db()
        lot = get_lottery_by_slug("leidsa_super_kino_tv")
        assert lot
        nums = format_numbers([1, 4, 8, 16, 17, 19, 21, 23, 26, 27, 29, 34, 51, 55, 61, 62, 66, 68, 69, 70])
        for i in range(12):
            upsert_result(
                lot["id"], "noche", "20:00",
                f"2026-05-{10 + i:02d}",
                nums,
                fuente="leidsa.com",
            )

    def test_config_super_kino(self):
        cfg = resolve_leidsa_recommendation_config("LEIDSA Super Kino TV", "leidsa_super_kino_tv")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg["count"], 10)
        self.assertEqual(cfg["max"], 80)
        self.assertFalse(cfg["allow_repeat"])

    def test_pick_no_duplicates(self):
        cfg = resolve_leidsa_recommendation_config("LEIDSA Super Kino TV", "leidsa_super_kino_tv")
        stats = {
            "_freq": {},
            "_all_nums": [],
            "hot_numbers": [],
            "cold_numbers": [],
            "overdue_numbers": [],
            "number_profiles": {},
            "recent_trend": {},
            "numbers_together": [],
            "repeated_combinations": [],
        }
        picked = _pick_numbers(stats, cfg)
        self.assertEqual(len(picked), 10)
        self.assertEqual(len(picked), len(set(picked)))
        self.assertEqual(_find_duplicate_numbers(picked), [])

    def test_generar_super_kino_count(self):
        lot = get_lottery_by_slug("leidsa_super_kino_tv")
        r = generar_jugada_inteligente(lot["id"], "noche")
        self.assertTrue(r.get("ok"), r.get("message"))
        nums = r.get("generated_numbers") or []
        self.assertEqual(len(nums), 10)
        self.assertEqual(r.get("recommend_count"), 10)
        self.assertEqual(_find_duplicate_numbers(nums), [])

    def test_debug_endpoint_payload(self):
        d = debug_leidsa_recommendation("LEIDSA Super Kino TV", "8:00 PM")
        self.assertIn("recommend_count", d)
        self.assertIn("duplicates_found", d)
        self.assertIn("history_count", d)
        if d.get("ok"):
            self.assertEqual(len(d.get("numbers") or []), 10)
            self.assertEqual(d.get("duplicates_found"), [])


if __name__ == "__main__":
    unittest.main()
