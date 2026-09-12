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
from services.leidsa_config import LEIDSA_GAMES  # noqa: E402
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

    def test_normalize_lottery_slug_accents(self):
        cases = {
            "Loto": "leidsa_loto_mas",
            "Loto Más": "leidsa_loto_mas",
            "Loto Mas": "leidsa_loto_mas",
            "LotoMas": "leidsa_loto_mas",
            "LEIDSA Loto Más": "leidsa_loto_mas",
            "Super Más": "leidsa_loto_mas",
            "Pega 3 Más": "leidsa_pega3",
            "Quiniela Pale": "leidsa_quiniela_pale",
        }
        for name, expected in cases.items():
            self.assertEqual(
                leidsa_service.normalize_lottery_slug(name),
                expected,
                msg=f"slug for {name!r}",
            )

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
        self.assertIn(a1, ("inserted", "updated"))
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
        with patch.object(leidsa_service, "scrape_leidsa_prefer_official", return_value=leidsa_service._safe_response(
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
        with patch.object(leidsa_service, "scrape_leidsa_prefer_official", return_value=leidsa_service._safe_response(
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

    def test_payload_cache_fetch_once(self):
        calls = {"n": 0}
        cache = {}

        def _fake_scrape():
            calls["n"] += 1
            return {
                "ok": True,
                "results": [{
                    "lottery": "leidsa_quiniela_pale",
                    "lottery_name": "LEIDSA Quiniela Palé",
                    "draw": "tarde",
                    "fecha_rd": "2026-09-12",
                    "numeros": [32, 76, 6],
                    "draw_time": "14:30",
                    "fuente": "LEIDSA.com",
                }],
                "parser": "leidsa_official",
                "fuente": "leidsa_official",
                "fuente_label": "LEIDSA.com",
                "latest_date": "2026-09-12",
            }

        with patch.object(leidsa_service, "scrape_leidsa_prefer_official", side_effect=_fake_scrape), patch.object(
            leidsa_service, "save_leidsa_rows", return_value={"ok": True, "inserted": 1, "updated": 0, "skipped": 0}
        ):
            out1 = leidsa_service.update_leidsa_now(scrape_cache=cache)
            out2 = leidsa_service.update_leidsa_now(scrape_cache=cache)

        self.assertTrue(out1["ok"])
        self.assertTrue(out2["ok"])
        self.assertEqual(calls["n"], 1)

    def test_single_payload_populates_quiniela_and_super_kino(self):
        seen = {"slugs": set()}

        payload = {
            "ok": True,
            "results": [
                {
                    "lottery": "leidsa_quiniela_pale",
                    "lottery_name": "LEIDSA Quiniela Palé",
                    "draw": "tarde",
                    "fecha_rd": "2026-09-12",
                    "numeros": [32, 76, 6],
                    "draw_time": "14:30",
                    "fuente": "LEIDSA.com",
                },
                {
                    "lottery": "leidsa_super_kino_tv",
                    "lottery_name": "LEIDSA Super Kino TV",
                    "draw": "noche",
                    "fecha_rd": "2026-09-11",
                    "numeros": list(range(1, 21)),
                    "draw_time": "20:00",
                    "fuente": "LEIDSA.com",
                },
            ],
            "parser": "leidsa_official",
            "fuente": "leidsa_official",
            "fuente_label": "LEIDSA.com",
            "latest_date": "2026-09-12",
        }

        def _fake_save(rows):
            for r in rows:
                seen["slugs"].add(r.get("lottery"))
            return {"ok": True, "inserted": 2, "updated": 0, "skipped": 0}

        with patch.object(leidsa_service, "scrape_leidsa_prefer_official", return_value=payload), patch.object(
            leidsa_service, "save_leidsa_rows", side_effect=_fake_save
        ):
            out = leidsa_service.update_leidsa_now()

        self.assertTrue(out["ok"])
        self.assertIn("leidsa_quiniela_pale", seen["slugs"])
        self.assertIn("leidsa_super_kino_tv", seen["slugs"])

    def test_utc_timestamp_to_rd_timezone(self):
        self.assertEqual(leidsa_service.utc_to_fecha_rd("2026-09-12T17:00:00Z"), "2026-09-12")
        hh, mm = leidsa_service.utc_to_local_hm("2026-09-12T17:00:00Z")
        self.assertEqual((hh, mm), (13, 0))

    def test_sync_priority_games_from_cached_scrape(self):
        cache = {
            "official_scrape": {
                "ok": True,
                "results": [
                    {
                        "lottery": "leidsa_quiniela_pale",
                        "lottery_name": "LEIDSA Quiniela Palé",
                        "draw": "tarde",
                        "fecha_rd": "2026-09-12",
                        "numeros": [32, 76, 6],
                        "draw_time": "14:30",
                        "fuente": "LEIDSA.com",
                    },
                    {
                        "lottery": "leidsa_super_kino_tv",
                        "lottery_name": "LEIDSA Super Kino TV",
                        "draw": "noche",
                        "fecha_rd": "2026-09-11",
                        "numeros": list(range(1, 21)),
                        "draw_time": "20:00",
                        "fuente": "LEIDSA.com",
                    },
                ],
            }
        }
        with patch.object(
            leidsa_service,
            "save_leidsa_rows",
            return_value={"ok": True, "inserted": 1, "updated": 1, "ignored": 0, "skipped": 0},
        ):
            out = leidsa_service.sync_priority_games_from_cached_scrape(
                slugs=["leidsa_quiniela_pale", "leidsa_super_kino_tv"],
                scrape_cache=cache,
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["results_found"], 2)
        self.assertIn("leidsa_quiniela_pale", out["games"])
        self.assertIn("leidsa_super_kino_tv", out["games"])

    def test_sync_priority_games_can_pull_missing_slug_fast(self):
        cache = {
            "official_scrape": {
                "ok": True,
                "results": [
                    {
                        "lottery": "leidsa_quiniela_pale",
                        "lottery_name": "LEIDSA Quiniela Palé",
                        "draw": "tarde",
                        "fecha_rd": "2026-09-12",
                        "numeros": [32, 76, 6],
                        "draw_time": "14:30",
                        "fuente": "LEIDSA.com",
                    },
                ],
            }
        }

        fake_game = {
            "slug": "leidsa_super_kino_tv",
            "family_name": "KinoTV",
            "path": "KinoTV",
            "draw_id_prefix": "3_",
        }
        fake_html = (
            'drawResults":[{"gameDrawId":"3_200","gameFamilyName":"KinoTV",'
            '"drawTime":"2026-09-11T20:00:00Z","results":{"drawnValues":[{"drawnValues":[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20]}]}}]'
        ).replace('"', '\\"')
        home_html = (
            '{\\"gameId\\":{\\"gameFamilyName\\":\\"KinoTV\\",\\"gameProvider\\":\\"Leidsa\\"}'
            ',\\"currentDrawDetails\\":{\\"drawId\\":\\"3_200\\"}}'
        )
        with patch("services.leidsa_service.save_leidsa_rows", return_value={"ok": True, "inserted": 2, "updated": 0, "ignored": 0, "skipped": 0}), patch("services.leidsa_config.LEIDSA_HISTORY_GAMES", [fake_game]), patch(
            "services.leidsa_http.fetch_leidsa_page",
            side_effect=[
                {"ok": True, "html": home_html},
                {"ok": True, "html": f"<html>{fake_html}</html>"},
            ],
        ), patch("services.leidsa_history.parse_draw_results_history") as parse_mock:
            parse_mock.return_value = [
                {
                    "lottery": "leidsa_super_kino_tv",
                    "lottery_name": "LEIDSA Super Kino TV",
                    "draw": "noche",
                    "fecha_rd": "2026-09-11",
                    "numeros": list(range(1, 21)),
                    "draw_time": "20:00",
                    "fuente": "LEIDSA.com",
                }
            ]
            out = leidsa_service.sync_priority_games_from_cached_scrape(
                slugs=["leidsa_quiniela_pale", "leidsa_super_kino_tv"],
                scrape_cache=cache,
            )

        self.assertTrue(out["ok"])
        self.assertEqual(out["results_found"], 2)
        self.assertEqual(out["games"]["leidsa_super_kino_tv"]["rows_found"], 1)


if __name__ == "__main__":
    unittest.main()
