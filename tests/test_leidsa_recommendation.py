"""Pruebas recomendación LEIDSA por cantidad, ranking y duplicados."""
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
from services.leidsa_config import resolve_leidsa_recommendation_config  # noqa: E402
from analysis import (  # noqa: E402
    _find_duplicate_numbers,
    _pick_numbers,
    analizar_loteria_por_tanda,
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
        nums = format_numbers(
            [1, 4, 8, 16, 17, 19, 21, 23, 26, 27, 29, 34, 51, 55, 61, 62, 66, 68, 69, 70]
        )
        for i in range(12):
            upsert_result(
                lot["id"],
                "noche",
                "20:00",
                f"2026-05-{10 + i:02d}",
                nums,
                fuente="leidsa.com",
            )

    def test_config_super_kino(self):
        cfg = resolve_leidsa_recommendation_config(
            "LEIDSA Super Kino TV",
            "leidsa_super_kino_tv",
        )
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg["count"], 10)
        self.assertEqual(cfg["recommend_count"], 10)
        self.assertEqual(cfg["numbers_per_draw"], 20)
        self.assertTrue(cfg["strict_score_ranking"])
        self.assertEqual(cfg["max"], 80)
        self.assertFalse(cfg["allow_repeat"])

    def test_other_leidsa_config_unchanged(self):
        cfg = resolve_leidsa_recommendation_config("LEIDSA Loto Más", "leidsa_loto_mas")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg["count"], 6)
        self.assertEqual(cfg["min"], 1)
        self.assertEqual(cfg["max"], 49)

    def test_pick_no_duplicates(self):
        cfg = resolve_leidsa_recommendation_config(
            "LEIDSA Super Kino TV",
            "leidsa_super_kino_tv",
        )
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
            "last_draw_numbers": [],
            "excluded_recent_numbers": [],
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
        self.assertEqual(len(set(nums)), 10)
        self.assertEqual(r.get("recommend_count"), 10)
        self.assertEqual(r.get("numbers_per_draw"), 20)
        self.assertEqual(_find_duplicate_numbers(nums), [])
        for n in nums:
            v = int(str(n).lstrip("0") or "0")
            self.assertGreaterEqual(v, 1)
            self.assertLessEqual(v, 80)

    def test_historical_draws_keep_20_numbers(self):
        lot = get_lottery_by_slug("leidsa_super_kino_tv")
        stats = analizar_loteria_por_tanda(lot["id"], "noche")
        self.assertTrue(stats.get("ok"), stats.get("message"))
        per_draw = stats.get("_per_draw") or []
        self.assertTrue(per_draw)
        self.assertTrue(all(len(draw) == 20 for draw in per_draw))

    def test_super_kino_is_deterministic_and_top_ranked(self):
        lot = get_lottery_by_slug("leidsa_super_kino_tv")
        first = generar_jugada_inteligente(lot["id"], "noche")
        second = generar_jugada_inteligente(lot["id"], "noche")
        self.assertTrue(first.get("ok"), first.get("message"))
        self.assertTrue(second.get("ok"), second.get("message"))
        nums1 = first.get("generated_numbers") or []
        nums2 = second.get("generated_numbers") or []
        self.assertEqual(nums1, nums2, "Super Kino debe ser determinístico sin ruido aleatorio")

        ranking = [r.get("number") for r in (first.get("top_numbers", {}).get("top_50") or []) if r.get("number")]
        stats = analizar_loteria_por_tanda(lot["id"], "noche")
        last_draw = set(stats.get("last_draw_numbers") or [])
        filtered = [n for n in ranking if n not in last_draw]
        if len(filtered) < 10:
            filtered = ranking
        self.assertEqual(nums1, filtered[:10], "Debe coincidir con TOP 10 real del ranking")

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
