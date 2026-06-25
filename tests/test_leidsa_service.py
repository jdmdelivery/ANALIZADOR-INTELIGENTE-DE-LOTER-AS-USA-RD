"""Pruebas módulo LEIDSA (config + servicio)."""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_test_db = os.path.join(tempfile.gettempdir(), "lottery_test_leidsa_v2.db")
os.environ["DATABASE_PATH"] = _test_db

import models  # noqa: E402
from models import init_db, get_lottery_by_slug, upsert_result  # noqa: E402
from services.leidsa_config import LEIDSA_GAMES, build_leidsa_games_dict  # noqa: E402
from services import leidsa_service  # noqa: E402

SAMPLE_HTML = (
    '{\\"gameId\\":{\\"gameFamilyName\\":\\"Quiniela Pale\\",\\"gameProvider\\":\\"Leidsa\\"}'
    ',\\"slug\\":\\"leidsa-quiniela-pale\\"'
    ',\\"previousDrawDetails\\":{\\"drawId\\":\\"5_1\\",\\"drawnValues\\":[12,34,56],'
    '\\"drawTimestamp\\":\\"2026-05-24T20:55:00Z\\"}'
    '{\\"gameId\\":{\\"gameFamilyName\\":\\"Pega3Mas\\",\\"gameProvider\\":\\"Leidsa\\"}'
    ',\\"slug\\":\\"leidsa-pega3mas\\"'
    ',\\"previousDrawDetails\\":{\\"drawId\\":\\"4_1\\",\\"drawnValues\\":[1,2,3],'
    '\\"drawTimestamp\\":\\"2026-05-24T23:55:00Z\\"}'
)


class LeidsaConfigTests(unittest.TestCase):
    def test_config_loads_without_cloudscraper(self):
        self.assertIn("leidsa_quiniela_pale", LEIDSA_GAMES)
        self.assertEqual(len(LEIDSA_GAMES["leidsa_quiniela_pale"]["draws"]), 2)

    def test_schedules_differ_per_game(self):
        qp_times = [d["time"] for d in LEIDSA_GAMES["leidsa_quiniela_pale"]["draws"]]
        p3_times = [d["time"] for d in LEIDSA_GAMES["leidsa_pega3"]["draws"]]
        pool_times = [d["time"] for d in LEIDSA_GAMES["leidsa_loto_pool"]["draws"]]
        self.assertEqual(qp_times, ["2:30 PM", "8:55 PM"])
        self.assertEqual(p3_times, ["3:00 PM", "9:00 PM"])
        self.assertNotEqual(qp_times, pool_times)


class LeidsaServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_test_db):
            os.remove(_test_db)
        init_db()

    def test_safe_response_never_none(self):
        r = leidsa_service._safe_response()
        self.assertIsInstance(r, dict)
        self.assertIn("ok", r)
        self.assertIn("results", r)
        self.assertEqual(r["results"], [])

    def test_scraper_structure(self):
        with patch(
            "services.leidsa_fallback.orchestrator._fetch_official",
            return_value={"ok": True, "html": SAMPLE_HTML, "status_code": 200, "method": "test"},
        ):
            out = leidsa_service.scrape_leidsa_results()
        self.assertTrue(out["ok"])
        self.assertGreater(len(out["results"]), 0)
        self.assertEqual(out["source"], "LEIDSA.com")

    def test_fallback_requests(self):
        with patch(
            "services.leidsa_fallback.leidsa_official_parser.fetch_official_page",
            return_value={"ok": True, "html": SAMPLE_HTML, "status_code": 200, "method": "requests"},
        ):
            out = leidsa_service.scrape_leidsa_results()
        self.assertTrue(out["ok"])

    def test_no_duplicate(self):
        models.seed_leidsa_lotteries()
        lot = get_lottery_by_slug("leidsa_quiniela_pale")
        self.assertIsNotNone(lot)
        _, a1 = upsert_result(lot["id"], "noche", "20:55", "2026-05-24", '["01","02","03"]', fuente="leidsa.com")
        _, a2 = upsert_result(lot["id"], "noche", "20:55", "2026-05-24", '["04","05","06"]', fuente="leidsa.com")
        self.assertEqual(a1, "inserted")
        self.assertEqual(a2, "updated")

    def test_failure_keeps_history(self):
        models.seed_leidsa_lotteries()
        lot = get_lottery_by_slug("leidsa_loto_pool")
        upsert_result(lot["id"], "noche", "21:00", "2026-05-20", '["09","10"]', fuente="leidsa.com")
        with models.get_db() as conn:
            before = conn.execute(
                "SELECT COUNT(*) AS c FROM lottery_results WHERE lottery_id=?",
                (lot["id"],),
            ).fetchone()["c"]
        with patch.object(leidsa_service, "scrape_leidsa_results", return_value=leidsa_service._safe_response(
            ok=False, error="HTTP 403", message="Leidsa no respondió", status_code=403,
        )):
            result = leidsa_service.update_leidsa_now()
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("live_failed"))
        self.assertTrue(result.get("used_db_fallback"))
        with models.get_db() as conn:
            after = conn.execute(
                "SELECT COUNT(*) AS c FROM lottery_results WHERE lottery_id=?",
                (lot["id"],),
            ).fetchone()["c"]
        self.assertEqual(before, after)

    def test_dashboard_for_frontend(self):
        data = leidsa_service.get_leidsa_dashboard()
        self.assertIsInstance(data, dict)
        self.assertIn("board", data)
        self.assertIn("historial", data)
        self.assertIn("debug", data)

    def test_board_only_real_numbers_no_placeholders(self):
        models.seed_leidsa_lotteries()
        lot = get_lottery_by_slug("leidsa_pega3")
        upsert_result(lot["id"], "noche", "21:00", "2099-01-01", '["01","02","03"]', fuente="leidsa.com")
        board = leidsa_service.get_leidsa_real_results_board("2099-01-01")
        self.assertEqual(len(board), 1)
        self.assertTrue(board[0]["numeros"])
        for item in board:
            self.assertNotEqual(item.get("estado"), "pendiente")
            self.assertTrue(item.get("numeros"))

    def test_debug_route_payload(self):
        with patch(
            "services.leidsa_fallback.orchestrator._fetch_official",
            return_value={"ok": True, "html": SAMPLE_HTML, "status_code": 200, "method": "test"},
        ):
            dbg = leidsa_service.debug_leidsa()
        self.assertIn("connection_ok", dbg)
        self.assertIn("results_count", dbg)

    def test_update_response_fields(self):
        with patch.object(leidsa_service, "scrape_leidsa_results", return_value=leidsa_service._safe_response(
            ok=True, results=[{
                "lottery": "leidsa_quiniela_pale",
                "draw": "noche",
                "fecha_rd": "2026-05-24",
                "numeros": [1, 2, 3],
                "draw_time": "20:55",
                "fuente": "leidsa.com",
                "estado": "publicado",
            }],
        )):
            r = leidsa_service.update_leidsa_now()
        self.assertIn("inserted", r)
        self.assertIn("updated", r)
        self.assertIn("skipped", r)


if __name__ == "__main__":
    unittest.main()
