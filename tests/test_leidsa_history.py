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


if __name__ == "__main__":
    unittest.main()
