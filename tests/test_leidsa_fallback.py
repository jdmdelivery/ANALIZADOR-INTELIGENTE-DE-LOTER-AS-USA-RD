"""Pruebas cadena fallback LEIDSA."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_test_db = os.path.join(tempfile.gettempdir(), "lottery_test_leidsa_fallback.db")
os.environ["DATABASE_PATH"] = _test_db

import models  # noqa: E402
from models import get_lottery_by_slug, init_db, upsert_result  # noqa: E402
from services import leidsa_service  # noqa: E402
from services.leidsa_fallback import orchestrator  # noqa: E402
from services.leidsa_fallback.enloteria_parser import parse_enloteria_html  # noqa: E402
from services.leidsa_fallback.orchestrator import scrape_leidsa_with_fallbacks  # noqa: E402

SAMPLE_OFFICIAL_HTML = (
    '{\\"gameId\\":{\\"gameFamilyName\\":\\"Quiniela Pale\\",\\"gameProvider\\":\\"Leidsa\\"}'
    ',\\"slug\\":\\"leidsa-quiniela-pale\\"'
    ',\\"previousDrawDetails\\":{\\"drawId\\":\\"5_1\\",\\"drawnValues\\":[12,34,56],'
    '\\"drawTimestamp\\":\\"2026-05-24T20:55:00Z\\"}'
)

ENLOTERIA_HTML = """
<div class="result-card">Leidsa Miércoles 24 de junio, 2026 8:50PM 88 28 70</div>
<div class="result-card">Leidsa Domingo 21 de junio, 2026 3:50PM 70 33 82</div>
"""

DEBUG_DIR = Path(ROOT) / "debug" / "leidsa_fallback"


class LeidsaFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_test_db):
            os.remove(_test_db)
        init_db()

    def test_official_403_tries_enloteria(self):
        def fake_fetch_rd(url, source, **kwargs):
            if source == "enloteria":
                return {"ok": True, "html": ENLOTERIA_HTML, "status_code": 200}
            return {"ok": False, "html": "", "status_code": 404, "error": "not used"}

        with patch(
            "services.leidsa_fallback.orchestrator._fetch_official",
            return_value={"ok": False, "status_code": 403, "error": "HTTP 403", "html": ""},
        ), patch(
            "services.leidsa_fallback.orchestrator._fetch_rd",
            side_effect=fake_fetch_rd,
        ):
            out = scrape_leidsa_with_fallbacks()

        self.assertTrue(out["ok"])
        self.assertEqual(out["fuente_usada"], "enloteria")
        self.assertEqual(out["fuente_label"], "EnLoteria")
        self.assertGreater(len(out["results"]), 0)

    def test_does_not_save_empty(self):
        models.seed_leidsa_lotteries()
        lot = get_lottery_by_slug("leidsa_quiniela_pale")
        with models.get_db() as conn:
            before = conn.execute(
                "SELECT COUNT(*) AS c FROM lottery_results WHERE lottery_id=?",
                (lot["id"],),
            ).fetchone()["c"]

        with patch.object(
            leidsa_service,
            "scrape_leidsa_results",
            return_value={
                "ok": True,
                "results": [],
                "rows": [],
                "parser": "test",
            },
        ):
            result = leidsa_service.update_leidsa_now()

        self.assertFalse(result["ok"])
        self.assertTrue(result.get("live_failed"))
        with models.get_db() as conn:
            after = conn.execute(
                "SELECT COUNT(*) AS c FROM lottery_results WHERE lottery_id=?",
                (lot["id"],),
            ).fetchone()["c"]
        self.assertEqual(before, after)

    def test_stops_on_first_success(self):
        calls = {"official": 0, "enloteria": 0, "ldus": 0}

        def fake_official(url):
            calls["official"] += 1
            return {"ok": True, "html": SAMPLE_OFFICIAL_HTML, "status_code": 200}

        def fake_rd(url, source, **kwargs):
            if source == "enloteria":
                calls["enloteria"] += 1
            if source == "loteriasdominicanas_us":
                calls["ldus"] += 1
            return {"ok": True, "html": ENLOTERIA_HTML, "status_code": 200}

        with patch(
            "services.leidsa_fallback.orchestrator._fetch_official",
            side_effect=fake_official,
        ), patch(
            "services.leidsa_fallback.orchestrator._fetch_rd",
            side_effect=fake_rd,
        ):
            out = scrape_leidsa_with_fallbacks()

        self.assertTrue(out["ok"])
        self.assertEqual(out["fuente_usada"], "leidsa_official")
        self.assertEqual(calls["official"], 1)
        self.assertEqual(calls["enloteria"], 0)
        self.assertEqual(calls["ldus"], 0)

    def test_all_fail_cache_no_false_success(self):
        models.seed_leidsa_lotteries()
        lot = get_lottery_by_slug("leidsa_loto_pool")
        upsert_result(lot["id"], "noche", "21:00", "2026-05-20", '["09","10"]', fuente="leidsa.com")

        with patch.object(
            leidsa_service,
            "scrape_leidsa_results",
            return_value={
                "ok": False,
                "error": "HTTP 403",
                "errors": ["LEIDSA.com: HTTP 403", "EnLoteria: HTTP 403"],
                "status_code": 403,
            },
        ):
            result = leidsa_service.update_leidsa_now()

        self.assertFalse(result["ok"])
        self.assertTrue(result.get("live_failed"))
        self.assertTrue(result.get("used_db_fallback"))
        self.assertIn("últimos resultados guardados", result["message"].lower())

    def test_usa_not_touched(self):
        """La cadena fallback no importa módulos USA."""
        import services.leidsa_fallback.orchestrator as orch_mod

        source_text = Path(orch_mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("scrapers_usa", source_text)
        self.assertNotIn("illinois", source_text.lower())
        self.assertNotIn("usa_refresh", source_text)

    def test_enloteria_parser_quiniela(self):
        rows = parse_enloteria_html(ENLOTERIA_HTML)
        self.assertGreaterEqual(len(rows), 1)
        slugs = {r["lottery"] for r in rows}
        self.assertIn("leidsa_quiniela_pale", slugs)
        self.assertTrue(all(r.get("numeros") for r in rows))

    def test_parsers_on_debug_html_if_present(self):
        if not DEBUG_DIR.exists():
            self.skipTest("debug/leidsa_fallback no disponible")
        from services.leidsa_fallback.loteriasdominicanas_us_parser import (
            parse_loteriasdominicanas_us_html,
        )
        from services.leidsa_fallback.nacionalloteria_parser import parse_nacionalloteria_html
        from services.leidsa_fallback.yelu_parser import parse_yelu_html

        ldus = DEBUG_DIR / "ldus.html"
        if ldus.exists():
            rows = parse_loteriasdominicanas_us_html(ldus.read_text(encoding="utf-8", errors="ignore"))
            self.assertGreater(len(rows), 0)
        nacional = DEBUG_DIR / "nacional.html"
        if nacional.exists():
            rows = parse_nacionalloteria_html(nacional.read_text(encoding="utf-8", errors="ignore"))
            self.assertGreater(len(rows), 0)
        yelu = DEBUG_DIR / "yelu.html"
        if yelu.exists():
            rows = parse_yelu_html(yelu.read_text(encoding="utf-8", errors="ignore"))
            self.assertGreater(len(rows), 0)


if __name__ == "__main__":
    unittest.main()
