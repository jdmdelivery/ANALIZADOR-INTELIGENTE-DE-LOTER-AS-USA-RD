"""Pruebas análisis USA — sin loops infinitos en Pick 3/4."""

import os
import sys
import tempfile
import time
import unittest
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_test_db = os.path.join(tempfile.gettempdir(), "lottery_test_usa_analysis.db")
os.environ["DATABASE_PATH"] = _test_db

from analysis import (  # noqa: E402
    _fallback_unique_numbers,
    _resolve_analysis_config,
    _sanitize_recommendation,
    es_combinacion_valida_illinois_lotto,
    es_combinacion_valida_pick4,
    generar_jugada_inteligente,
)
from models import init_db, get_all_lotteries, get_draw_times, get_lottery_config  # noqa: E402


class UsaAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_test_db):
            os.remove(_test_db)
        init_db()

    def test_fallback_unique_numbers_no_infinite_loop(self):
        t0 = time.time()
        out = _fallback_unique_numbers(["1", "2"], ["1", "2"], 5, 1)
        elapsed = time.time() - t0
        self.assertLess(elapsed, 1.0)
        self.assertLessEqual(len(out), 5)

    def test_pick3_generar_jugada_completes(self):
        usa_lots = [l for l in get_all_lotteries() if l.get("type") == "pick3" and l.get("country") == "USA"]
        if not usa_lots:
            self.skipTest("Sin lotería Pick 3 USA en BD de prueba")
        lot = usa_lots[0]
        draws = get_draw_times(lot["id"])
        if not draws:
            self.skipTest("Sin horarios Pick 3")
        draw = draws[0]["draw_name"]
        t0 = time.time()
        result = generar_jugada_inteligente(lot["id"], draw)
        elapsed = time.time() - t0
        self.assertLess(elapsed, 5.0, "Pick 3 análisis no debe colgarse")
        if result.get("ok"):
            self.assertEqual(len(result.get("generated_numbers") or []), 3)

    def test_sanitize_allow_repeat_pick3(self):
        stats = {
            "last_draw_numbers": set(),
            "excluded_recent_numbers": set(),
            "number_profiles": {},
            "_per_draw": [],
            "_freq": Counter(),
            "hot_numbers": ["1", "4", "7"],
            "cold_numbers": ["0", "2"],
            "overdue_numbers": ["3", "5"],
        }
        cfg = {"count": 3, "min": 0, "max": 9, "allow_repeat": True, "max_repeat_per_number": 2, "min_unique": 2, "pad": 1}
        t0 = time.time()
        out = _sanitize_recommendation(["1", "1", "1"], stats, cfg)
        elapsed = time.time() - t0
        self.assertLess(elapsed, 1.0)
        self.assertEqual(len(out), 3)
        self.assertGreater(len(set(out)), 1)

    def test_es_combinacion_valida_pick4(self):
        self.assertFalse(es_combinacion_valida_pick4(["7", "7", "7", "7"]))
        self.assertFalse(es_combinacion_valida_pick4(["3", "3", "3", "3"]))
        self.assertFalse(es_combinacion_valida_pick4(["7", "7", "7", "1"]))
        self.assertFalse(es_combinacion_valida_pick4(["1", "2"]))
        self.assertTrue(es_combinacion_valida_pick4(["7", "1", "4", "0"]))
        self.assertTrue(es_combinacion_valida_pick4(["3", "9", "5", "2"]))
        self.assertTrue(es_combinacion_valida_pick4(["7", "7", "1", "4"]))

    def test_pick4_variety_not_all_same(self):
        usa_lots = [l for l in get_all_lotteries() if l.get("type") == "pick4" and l.get("country") == "USA"]
        if not usa_lots:
            self.skipTest("Sin Pick 4 USA")
        lot = usa_lots[0]
        draws = get_draw_times(lot["id"])
        if not draws:
            self.skipTest("Sin horarios Pick 4")
        for _ in range(20):
            result = generar_jugada_inteligente(lot["id"], draws[0]["draw_name"])
            if not result.get("ok"):
                continue
            nums = result.get("generated_numbers") or []
            bonus = result.get("generated_bonus")
            self.assertEqual(len(nums), 4, nums)
            self.assertTrue(es_combinacion_valida_pick4(nums), f"Inválido: {nums}")
            self.assertGreater(len(set(nums)), 1, f"Demasiado repetitivo: {nums}")
            self.assertLessEqual(max(Counter(nums).values()), 2, f"Más de 2 repeticiones: {nums}")
            self.assertGreaterEqual(len(set(nums)), 3, f"Menos de 3 únicos: {nums}")
            if bonus and nums:
                dominant = Counter(nums).most_common(1)[0][0]
                self.assertNotEqual(bonus, dominant, f"Bonus = dominante: {nums} + {bonus}")
            self.assertEqual(result.get("duplicates_found"), [])

    def test_illinois_lotto_config_max_50(self):
        cfg = get_lottery_config("lotto")
        self.assertEqual(cfg["max"], 50)
        self.assertEqual(cfg["count"], 6)

    def test_es_combinacion_valida_illinois_lotto(self):
        self.assertFalse(es_combinacion_valida_illinois_lotto(["12", "52", "49", "19", "50", "44"]))
        self.assertFalse(es_combinacion_valida_illinois_lotto(["51", "02", "03", "04", "05", "06"]))
        self.assertFalse(es_combinacion_valida_illinois_lotto(["01", "02", "03", "04", "05"]))
        self.assertTrue(es_combinacion_valida_illinois_lotto(["12", "49", "19", "50", "44", "01"]))

    def test_illinois_lotto_resolve_config(self):
        lot = {"name": "Illinois Lotto", "country": "USA", "type": "lotto"}
        cfg = _resolve_analysis_config(lot)
        self.assertEqual(cfg["max"], 50)
        self.assertEqual(cfg["count"], 6)
        pb = {"name": "Powerball", "country": "USA", "type": "powerball"}
        self.assertEqual(_resolve_analysis_config(pb)["max"], 69)


if __name__ == "__main__":
    unittest.main()
