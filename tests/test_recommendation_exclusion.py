"""Pruebas: no recomendar números del último sorteo ni ventana reciente."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_test_db = os.path.join(tempfile.gettempdir(), "lottery_test_rec_exclude.db")
os.environ["DATABASE_PATH"] = _test_db

from models import init_db, get_lottery_by_slug, upsert_result, format_numbers  # noqa: E402
from analysis import (  # noqa: E402
    RECENT_EXCLUSION_DRAWS,
    _collect_last_draw_numbers,
    _collect_recent_drawn_numbers,
    _find_duplicate_numbers,
    _is_pickable_number,
    _pick_numbers,
    _sanitize_recommendation,
    analizar_loteria_por_tanda,
    generar_jugada_inteligente,
)
from models import get_lottery_config  # noqa: E402


class RecommendationExclusionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_test_db):
            os.remove(_test_db)
        init_db()

    def _seed_pick3_history(self):
        lot = get_lottery_by_slug("rd_loteka")
        if not lot:
            self.skipTest("rd_loteka no en BD de prueba")
        draws = [
            ("1", "2", "3"),
            ("4", "5", "6"),
            ("7", "8", "9"),
            ("1", "4", "7"),
            ("2", "5", "8"),
            ("3", "6", "9"),
            ("0", "1", "2"),
            ("3", "4", "5"),
            ("6", "7", "8"),
            ("9", "0", "1"),
            ("2", "3", "4"),
            ("5", "6", "7"),
        ]
        for i, triple in enumerate(draws):
            upsert_result(
                lot["id"],
                "noche",
                "20:00",
                f"2026-04-{10 + i:02d}",
                format_numbers(list(triple)),
                fuente="test",
            )
        return lot

    def test_last_draw_not_pickable(self):
        lot = self._seed_pick3_history()
        stats = analizar_loteria_por_tanda(lot["id"], "noche")
        self.assertTrue(stats.get("ok"), stats.get("message"))
        last = set(stats.get("last_draw_numbers") or [])
        self.assertTrue(last)
        for n in last:
            self.assertFalse(_is_pickable_number(n, stats))

    def test_recommendation_excludes_last_draw(self):
        lot = self._seed_pick3_history()
        stats = analizar_loteria_por_tanda(lot["id"], "noche")
        cfg = stats.get("_config") or get_lottery_config(lot["type"])
        for _ in range(15):
            picked = _pick_numbers(stats, cfg)
            picked = _sanitize_recommendation(picked, stats, cfg)
            overlap = set(picked) & set(stats.get("last_draw_numbers") or [])
            self.assertEqual(overlap, set(), f"repite último sorteo: {overlap}")
            self.assertEqual(len(picked), len(set(picked)))

    def test_generar_no_last_draw_overlap(self):
        lot = self._seed_pick3_history()
        r = generar_jugada_inteligente(lot["id"], "noche")
        self.assertTrue(r.get("ok"), r.get("message"))
        nums = r.get("generated_numbers") or []
        stats = analizar_loteria_por_tanda(lot["id"], "noche")
        last = set(stats.get("last_draw_numbers") or [])
        self.assertFalse(set(nums) & last)
        self.assertEqual(_find_duplicate_numbers(nums), [])

    def test_recent_window_collection(self):
        per_draw = [["01", "02"], ["03", "04"], ["05", "06"]]
        recent = _collect_recent_drawn_numbers(per_draw, 2)
        self.assertEqual(recent, {"01", "02", "03", "04"})
        self.assertEqual(_collect_last_draw_numbers(per_draw), {"01", "02"})
        self.assertGreaterEqual(RECENT_EXCLUSION_DRAWS, 3)


if __name__ == "__main__":
    unittest.main()
