"""Smoke tests: DB, login y endpoints principales."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_test_db = os.path.join(tempfile.gettempdir(), "lottery_test_smoke.db")
os.environ["DATABASE_PATH"] = _test_db
os.environ["SECRET_KEY"] = "x" * 32
os.environ["INITIAL_ADMIN_PASSWORD"] = "SmokeTestAdmin99!"

import models  # noqa: E402

models.DATABASE = _test_db
from app import app  # noqa: E402
from models import init_db  # noqa: E402


class SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_test_db):
            os.remove(_test_db)
        init_db()

    def setUp(self):
        from auth import login_manager

        login_manager.session_protection = None
        self.client = app.test_client()

    def _login_admin(self):
        res = self.client.post(
            "/login",
            data={"username": "jdmcashnow", "password": "SmokeTestAdmin99!"},
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200, "Login admin falló en smoke test")
        return res

    def test_init_db_idempotent(self):
        init_db()
        init_db()

    def test_login_redirects_index(self):
        res = self._login_admin()
        self.assertEqual(res.status_code, 200)

    def test_index_requires_auth(self):
        res = self.client.get("/")
        self.assertIn(res.status_code, (302, 401))

    def test_index_ok_when_logged_in(self):
        self._login_admin()
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)

    def test_api_lotteries_json(self):
        self._login_admin()
        res = self.client.get("/api/lotteries")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIsInstance(data.get("lotteries"), list)

    def test_debug_system_admin_only(self):
        res = self.client.get("/debug/system")
        self.assertIn(res.status_code, (302, 401, 403))
        self._login_admin()
        res = self.client.get("/debug/system")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json().get("ok"))

    def test_api_actualizar_resultados_routes_exist(self):
        """POST /api/resultados/actualizar y alias actualizar-ahora (no 404)."""
        for path in ("/api/resultados/actualizar", "/api/resultados/actualizar-ahora"):
            res = self.client.post(path, json={"country": "USA"})
            self.assertNotEqual(
                res.status_code,
                404,
                f"{path} devolvió 404 — ruta no registrada",
            )
            self.assertIn(res.status_code, (401, 403), path)

        self._login_admin()
        with patch("services.actualizar_resultados.actualizar_resultados_usa") as mock_usa:
            mock_usa.return_value = {"ok": True, "message": "OK", "saved_count": 0}
            for path in ("/api/resultados/actualizar", "/api/resultados/actualizar-ahora"):
                res = self.client.post(
                    path,
                    json={"country": "USA", "state": "Illinois", "refresh_all_usa": True},
                )
                self.assertEqual(res.status_code, 200, path)
                data = res.get_json()
                self.assertTrue(data.get("ok"), data)
                mock_usa.assert_called_once()
                mock_usa.reset_mock()


if __name__ == "__main__":
    unittest.main()
