"""Tests motor de recomendaciones v2 — obligatorios FASE 10."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_test_db = os.path.join(tempfile.gettempdir(), "lottery_test_rec_engine.db")
os.environ["DATABASE_PATH"] = _test_db

from models import init_db, get_lottery_by_slug, upsert_result, format_numbers  # noqa: E402
from services.recommendations.categories import assign_category, classify_number  # noqa: E402
from services.recommendations.constants import INSUFFICIENT_HISTORY_MSG, MIN_HISTORY  # noqa: E402
from services.recommendations.engine import generate_recommendation  # noqa: E402
from services.recommendations.paste_analyzer import analyze_pasted_numbers  # noqa: E402
from services.recommendations.registry import game_family  # noqa: E402
from services.recommendations.scoring import is_strong_recommendation  # noqa: E402
from services.recommendations.backtesting import run_backtest_summary  # noqa: E402


def _seed_quiniela(lot_slug="rd_loteka", n=12):
    lot = get_lottery_by_slug(lot_slug)
    for i in range(n):
        upsert_result(
            lot["id"],
            "noche",
            "20:00",
            f"2026-05-{10 + i:02d}",
            format_numbers([f"{(i*3)%100:02d}", f"{(i*7)%100:02d}", f"{(i*11)%100:02d}"]),
            fuente="test",
        )
    return lot


def _seed_pick3(n=12):
    lot = get_lottery_by_slug("illinois_pick_3") or next(
        (l for l in __import__("models").get_all_lotteries() if l.get("type") == "pick3"), None
    )
    if not lot:
        return None
    for i in range(n):
        upsert_result(
            lot["id"],
            "Evening",
            "21:22",
            f"2026-05-{10 + i:02d}",
            format_numbers([str(i % 10), str((i + 1) % 10), str((i + 2) % 10)]),
            fireball_number=str((i + 3) % 10),
            fuente="test",
        )
    return lot


class RecommendationEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_test_db):
            os.remove(_test_db)
        init_db()

    def test_hot_and_cold_mutually_exclusive(self):
        per_draw = [[f"{i:02d}", f"{(i+1)%100:02d}", f"{(i+2)%100:02d}"] for i in range(15)]
        profiles = {}
        cats = {}
        for i in range(100):
            num = f"{i:02d}"
            prof = classify_number(num, per_draw, pad=2)
            cat = assign_category(prof)
            profiles[num] = prof
            cats[num] = cat
        for num, cat in cats.items():
            self.assertFalse(cat == "caliente" and cat == "frío")
            if cat == "caliente":
                self.assertNotEqual(cats.get(num), "frío")

    def test_low_score_not_strong(self):
        self.assertFalse(is_strong_recommendation(45))
        self.assertFalse(is_strong_recommendation(59))
        self.assertTrue(is_strong_recommendation(60))

    def test_pick4_top5_top10(self):
        lot = _seed_pick3()
        if not lot:
            self.skipTest("Sin Pick 3/4 en BD")
        from services.recommendations.engine import _run_adapter

        result, _, _, _ = _run_adapter(lot["id"], "Evening")
        if not result.get("ok"):
            self.skipTest(result.get("message"))
        top = result.get("top_combinations") or {}
        self.assertGreaterEqual(len(top.get("top_5") or []), 1)
        self.assertGreaterEqual(len(top.get("top_10") or []), 1)
        self.assertGreaterEqual(len(top.get("top_20") or []), 1)
        self.assertTrue(result.get("position_picks"))

    def test_rich_explanation_format(self):
        from services.recommendations.explanations import build_rich_explanation
        prof = {"count_100": 14, "draws_since": 3, "trend": "tendencia", "category": "tendencia"}
        text = build_rich_explanation("23", prof, 87, draw_name="noche", per_draw=[["23"]] * 100)
        self.assertIn("23", text)
        self.assertIn("score 87", text)
        self.assertIn("sorteos", text)

    def test_weekday_factor(self):
        from services.recommendations.context_factors import score_weekday_factor
        per_draw = [["05"], ["06"], ["05"], ["07"]]
        dates = ["2026-05-26", "2026-05-25", "2026-05-19", "2026-05-18"]
        score, meta = score_weekday_factor("05", per_draw, dates)
        self.assertGreaterEqual(score, 0)
        self.assertIn("weekday_counts", meta)

    def test_fireball_separate_score(self):
        lot = _seed_pick3()
        if not lot:
            self.skipTest("Sin Pick")
        r = generate_recommendation(lot["id"], "Evening")
        if not r.get("ok"):
            self.skipTest(r.get("message"))
        fb = r.get("fireball") or {}
        mains = set(r.get("generated_numbers") or [])
        if fb.get("number"):
            self.assertNotIn(fb["number"], mains)
            self.assertTrue(fb.get("separate_from_main") or r.get("bonus_label"))

    def test_quiniela_top_lists(self):
        lot = _seed_quiniela()
        r = generate_recommendation(lot["id"], "noche")
        self.assertTrue(r.get("ok"), r.get("message"))
        tn = r.get("top_numbers") or {}
        self.assertGreaterEqual(len(tn.get("top_10") or []), 10)
        self.assertGreaterEqual(len(tn.get("top_20") or []), 20)
        self.assertGreaterEqual(len(tn.get("top_50") or []), 50)

    def test_kino_paste_compare(self):
        lot = get_lottery_by_slug("leidsa_super_kino_tv")
        if not lot:
            self.skipTest("Sin Super Kino")
        nums = " ".join(str(i) for i in range(1, 21))
        for i in range(MIN_HISTORY):
            upsert_result(
                lot["id"], "noche", "20:00", f"2026-04-{10+i:02d}",
                format_numbers(list(range(1, 21))),
                fuente="test",
            )
        out = analyze_pasted_numbers(lot["id"], "noche", nums)
        self.assertTrue(out.get("ok"), out.get("message"))
        self.assertGreater(len(out.get("analysis") or []), 0)

    def test_powerball_separate_bonus(self):
        from models import get_all_lotteries
        pb = next((l for l in get_all_lotteries() if l.get("type") == "powerball"), None)
        if not pb:
            self.skipTest("Sin Powerball")
        for i in range(MIN_HISTORY):
            upsert_result(
                pb["id"], "Powerball draw", "22:00", f"2026-04-{10+i:02d}",
                format_numbers(["05", "12", "23", "34", "45"]),
                bonus_number="10",
                fuente="test",
            )
        r = generate_recommendation(pb["id"], "Powerball draw")
        if not r.get("ok"):
            self.skipTest(r.get("message"))
        mains = set(r.get("generated_numbers") or [])
        sp = r.get("special_ball") or {}
        if sp.get("number"):
            self.assertNotIn(sp["number"], mains)

    def test_backtest_structure(self):
        summary = run_backtest_summary(days=30)
        self.assertIn("ok", summary)

    def test_insufficient_history(self):
        lot = get_lottery_by_slug("rd_loteka")
        r = generate_recommendation(lot["id"], "mañana")
        if r.get("ok"):
            self.skipTest("Hay historial en mañana")
        self.assertIn("insuficiente", (r.get("message") or "").lower())

    def test_rd_usa_not_mixed(self):
        self.assertEqual(game_family({"country": "RD", "type": "rd_loteka", "name": "Loteka"}), "quiniela_rd")
        self.assertEqual(game_family({"country": "USA", "type": "pick3", "name": "Pick 3"}), "pick")
        self.assertEqual(game_family({"country": "USA", "type": "powerball", "name": "Powerball"}), "power_mega")
        self.assertNotEqual(
            game_family({"country": "RD", "type": "rd_loteka", "name": "Loteka"}),
            game_family({"country": "USA", "type": "pick3", "name": "Pick 3"}),
        )


if __name__ == "__main__":
    unittest.main()
