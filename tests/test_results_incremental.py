"""Pruebas de sincronización incremental/backfill e idempotencia."""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_test_db = os.path.join(tempfile.gettempdir(), "lottery_test_incremental_rd.db")
os.environ["DATABASE_PATH"] = _test_db

from models import init_db, get_lottery_by_slug, upsert_result, count_results_for_lottery  # noqa: E402
from services.leidsa_service import update_leidsa_game_incremental  # noqa: E402
from services.actualizar_resultados import actualizar_resultados  # noqa: E402


class IncrementalResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_test_db):
            os.remove(_test_db)
        init_db()

    def setUp(self):
        # Estado base consistente por prueba
        lot = get_lottery_by_slug("leidsa_super_kino_tv")
        self.assertIsNotNone(lot)
        self.lottery_id = lot["id"]
        upsert_result(
            self.lottery_id,
            "noche",
            "20:00",
            "2026-08-16",
            ["01"] * 20,
            confirmed=1,
            fuente="test",
        )

    def test_upsert_result_is_idempotent_when_same_row(self):
        _, first = upsert_result(
            self.lottery_id,
            "noche",
            "20:00",
            "2026-08-10",
            ["02"] * 20,
            confirmed=1,
            fuente="test",
        )
        _, second = upsert_result(
            self.lottery_id,
            "noche",
            "20:00",
            "2026-08-10",
            ["02"] * 20,
            confirmed=1,
            fuente="test",
        )
        self.assertEqual(first, "inserted")
        self.assertEqual(second, "ignored")

    def test_incremental_without_new_dates_returns_no_new(self):
        before = count_results_for_lottery(self.lottery_id, "noche")
        out = update_leidsa_game_incremental("leidsa_super_kino_tv", lookback_days=90)
        after = count_results_for_lottery(self.lottery_id, "noche")
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("status"), "no_new")
        self.assertEqual(out.get("inserted"), 0)
        self.assertEqual(out.get("updated"), 0)
        self.assertEqual(before, after)

    def test_incremental_range_uses_ignored_on_second_pass(self):
        fake_rows = [
            {
                "lottery": "leidsa_super_kino_tv",
                "draw": "noche",
                "fecha_rd": "2026-08-01",
                "draw_time": "20:00",
                "numeros": list(range(1, 21)),
                "fuente": "test",
                "estado": "publicado",
            },
            {
                "lottery": "leidsa_super_kino_tv",
                "draw": "noche",
                "fecha_rd": "2026-08-02",
                "draw_time": "20:00",
                "numeros": list(range(2, 22)),
                "fuente": "test",
                "estado": "publicado",
            },
        ]

        def _fake_sync(*_args, **_kwargs):
            from services.leidsa_service import save_leidsa_rows

            batch = save_leidsa_rows(fake_rows)
            return {
                "ok": True,
                "rows": fake_rows,
                "results_found": len(fake_rows),
                "inserted": batch.get("inserted", 0),
                "updated": batch.get("updated", 0),
                "ignored": batch.get("ignored", 0),
                "parser": "test",
                "error": None,
            }

        with patch("services.leidsa_history.sync_leidsa_game_history_range", side_effect=_fake_sync):
            first = update_leidsa_game_incremental(
                "leidsa_super_kino_tv",
                fecha_desde="2026-08-01",
                fecha_hasta="2026-08-02",
            )
            second = update_leidsa_game_incremental(
                "leidsa_super_kino_tv",
                fecha_desde="2026-08-01",
                fecha_hasta="2026-08-02",
            )

        self.assertEqual(first.get("inserted"), 2)
        self.assertEqual(second.get("inserted"), 0)
        self.assertGreaterEqual(second.get("ignored", 0), 2)

    def test_backfill_wrapper_rd_calls_range_mode(self):
        with patch(
            "services.rd_results_service.actualizar_rd_loteria_rango",
            return_value={"ok": True, "range_mode": True, "inserted": 0, "updated": 0},
        ) as mocked:
            out = actualizar_resultados(
                "2026-01-01",
                "2026-08-16",
                "LEIDSA Super Kino TV",
                pais="RD",
            )
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("range_mode"))
        mocked.assert_called_once()


if __name__ == "__main__":
    unittest.main()
