"""Health endpoint (sin autenticación)."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_test_db = os.path.join(tempfile.gettempdir(), "lottery_test_health.db")
os.environ["DATABASE_PATH"] = _test_db
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-health-endpoint")

import models  # noqa: E402

models.DATABASE = _test_db
from app import app  # noqa: E402
from models import init_db  # noqa: E402


class HealthEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_test_db):
            os.remove(_test_db)
        init_db()

    def test_health_returns_200(self):
        client = app.test_client()
        res = client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("status"), "healthy")


if __name__ == "__main__":
    unittest.main()
