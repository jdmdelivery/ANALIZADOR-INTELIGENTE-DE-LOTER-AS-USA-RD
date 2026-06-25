"""Pruebas historial LEIDSA (drawResults)."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_test_db = os.path.join(tempfile.gettempdir(), "lottery_test_leidsa_hist.db")
os.environ["DATABASE_PATH"] = _test_db

from models import init_db, get_lottery_by_slug  # noqa: E402
from services.leidsa_config import LEIDSA_HISTORY_GAMES  # noqa: E402
from services.leidsa_history import (  # noqa: E402
    discover_latest_draw_ids,
    parse_draw_results_history,
    build_results_url,
)

SAMPLE_DRAW_RESULTS = (
    'drawResults":[{"gameDrawId":"1_100","gameFamilyName":"Loto",'
    '"drawTime":"2026-05-24T01:00:00Z","results":{"drawnValues":[{"drawnValues":[1,2,3,4,5,6]}]}},'
    '{"gameDrawId":"1_99","gameFamilyName":"Loto",'
    '"drawTime":"2026-05-20T01:00:00Z","results":{"drawnValues":[{"drawnValues":[7,8,9,10,11,12]}]}}]'
).replace('"', '\\"')


class LeidsaHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_test_db):
            os.remove(_test_db)
        init_db()

    def test_history_games_config(self):
        self.assertGreaterEqual(len(LEIDSA_HISTORY_GAMES), 6)
        for g in LEIDSA_HISTORY_GAMES:
            self.assertIn("path", g)
            self.assertIn("slug", g)

    def test_parse_draw_results(self):
        html = f"<html>{SAMPLE_DRAW_RESULTS}</html>"
        rows = parse_draw_results_history(
            html, "Loto", days=365, limit=10, slug="leidsa_loto_mas"
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["numeros"], [1, 2, 3, 4, 5, 6])

    def test_discover_draw_ids_live(self):
        ids = discover_latest_draw_ids()
        if ids:
            self.assertIn("Loto", ids)
            url = build_results_url(LEIDSA_HISTORY_GAMES[0], ids)
            self.assertIn("leidsa.com/results", url)

    def test_update_ok_when_partial_saved(self):
        from unittest.mock import patch
        from services.leidsa_history import fetch_all_leidsa_history, update_leidsa_history

        good = {
            "ok": True,
            "rows": [{"lottery": "leidsa_loto_mas", "draw": "noche", "fecha_rd": "2026-06-01", "numeros": [1, 2, 3, 4, 5, 6], "draw_time": "21:00"}],
            "url": "https://www.leidsa.com/results/Leidsa/Loto/1_1",
            "status_code": 200,
            "error": None,
        }
        bad = {"ok": False, "rows": [], "url": "https://www.leidsa.com/x", "status_code": 403, "error": "HTTP 403"}

        with patch("services.leidsa_history.fetch_leidsa_game_history", side_effect=[good, bad, bad, bad, bad, bad]):
            with patch("services.leidsa_history.save_leidsa_rows") as save:
                save.return_value = {"inserted": 2, "updated": 0, "skipped": 0, "errors": []}
                out = fetch_all_leidsa_history(days=30, save=True, use_cache=False)
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("partial"))
        self.assertEqual(out.get("inserted"), 2)

    def test_update_fails_when_all_games_empty(self):
        from unittest.mock import patch
        from services.leidsa_history import update_leidsa_history

        empty = {"ok": False, "rows": [], "url": "https://www.leidsa.com/x", "status_code": 403, "error": "HTTP 403"}
        with patch("services.leidsa_history.fetch_all_leidsa_history") as fetch_all:
            fetch_all.return_value = {
                "ok": False,
                "results_found": 0,
                "inserted": 0,
                "updated": 0,
                "games": [{"name": "Loto Más", "ok": False, "error": "HTTP 403"}],
                "error": "HTTP 403",
            }
            out = update_leidsa_history(days=30)
        self.assertFalse(out.get("ok"))
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
