from __future__ import annotations

import time
import tempfile
import os

import requests

from services import rd_results_service as rdsvc
from services.rd_update_jobs import create_job, finish_job, get_job, start_job
from scrapers import rd_http
from scrapers import rd_fallback_scrapers as rdfs


class _FakeResp:
    def __init__(self, status_code=200, text="ok" * 400, headers=None, url="https://example.test"):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = headers or {"Content-Type": "text/html"}
        self.url = url

    def json(self):
        return {"ok": True}


def test_fetch_rd_url_no_retry_on_403(monkeypatch):
    calls = {"n": 0}

    class _Sess:
        def get(self, *_a, **_kw):
            calls["n"] += 1
            return _FakeResp(status_code=403, text="forbidden")

    monkeypatch.setattr(rd_http, "_SOURCE_DISABLED_UNTIL", {})
    monkeypatch.setattr(rd_http, "get_rd_session", lambda: _Sess())
    out = rd_http.fetch_rd_url("https://x.test", source="conectate", retries=4, timeout=(0.1, 0.1))
    assert out["ok"] is False
    assert out["status_code"] == 403
    assert calls["n"] == 1


def test_fetch_rd_url_retries_once_on_timeout(monkeypatch):
    calls = {"n": 0}

    class _Sess:
        def get(self, *_a, **_kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise requests.Timeout("read timeout")
            return _FakeResp(status_code=200, text="x" * 1000)

    monkeypatch.setattr(rd_http, "_SOURCE_DISABLED_UNTIL", {})
    monkeypatch.setattr(rd_http, "get_rd_session", lambda: _Sess())
    out = rd_http.fetch_rd_url("https://x.test", source="enloteria", retries=3, timeout=(0.1, 0.1))
    assert out["ok"] is True
    assert calls["n"] == 2


def test_circuit_breaker_skips_repeated_blocked_source(monkeypatch):
    calls = {"n": 0}

    class _Sess:
        def get(self, *_a, **_kw):
            calls["n"] += 1
            return _FakeResp(status_code=403, text="forbidden")

    monkeypatch.setattr(rd_http, "_SOURCE_DISABLED_UNTIL", {})
    monkeypatch.setattr(rd_http, "get_rd_session", lambda: _Sess())
    rd_http.fetch_rd_url("https://x.test", source="conectate", retries=3, timeout=(0.1, 0.1))
    out2 = rd_http.fetch_rd_url("https://x.test", source="conectate", retries=3, timeout=(0.1, 0.1))
    assert out2["ok"] is False
    assert "deshabilitada" in (out2.get("error") or "").lower()
    assert calls["n"] == 1


def test_rd_job_finish_marks_failed_when_live_failed_no_new():
    job = create_job({"pais": "RD"})
    start_job(job["job_id"])
    finish_job(
        job["job_id"],
        result={"ok": True, "live_failed": True, "imported": 0, "updated": 0, "errors": ["all down"]},
    )
    done = get_job(job["job_id"])
    assert done
    assert done["status"] == "failed"
    assert done["finished_at"]


def test_actualizar_rd_todas_respects_deadline(monkeypatch):
    monkeypatch.setattr(rdsvc, "iter_enabled_conectate_configs", lambda: [("A", {"db_names": ["Real"]}), ("B", {"db_names": ["Nacional"]})])
    monkeypatch.setattr(rdsvc, "normalize_lottery_name", lambda x: x.lower())
    monkeypatch.setattr(rdsvc, "actualizar_leidsa_multi", lambda **_kw: {"ok": True, "imported": 0, "updated": 0})
    monkeypatch.setattr(rdsvc, "find_lottery_in_list", lambda *_a, **_kw: {"id": 1, "name": "Real"})
    monkeypatch.setattr(rdsvc, "get_all_lotteries", lambda: [{"id": 1, "name": "Real", "country": "RD"}])
    monkeypatch.setattr(rdsvc, "get_max_draw_date", lambda *_a, **_kw: "2026-09-12")
    monkeypatch.setattr(rdsvc, "_deadline_reached", lambda *_a, **_kw: True)

    def _slow(*_a, **_kw):
        time.sleep(0.07)
        return {"ok": False, "message": "down", "imported": 0, "updated": 0}

    monkeypatch.setattr(rdsvc, "actualizar_rd_loteria", _slow)
    out = rdsvc.actualizar_rd_todas(days=30, max_job_seconds=120, job_id="job-x")
    assert any("exceeded maximum execution time" in e for e in out["errors"])


def test_loteriasdominicanas_current_only_does_not_loop_full_range(monkeypatch):
    calls = {"n": 0}

    def _fake_fetch(url, **_kw):
        calls["n"] += 1
        if "date=" in url:
            return {"ok": False, "status_code": 403, "url": url, "html": ""}
        return {"ok": True, "status_code": 200, "url": url, "html": "<html></html>"}

    monkeypatch.setattr(rdfs, "fetch_rd_url", _fake_fetch)
    monkeypatch.setattr(rdfs, "_parse_kiskoo_history", lambda *_a, **_kw: [])
    monkeypatch.setattr(rdfs, "_parse_kiskoo_main", lambda *_a, **_kw: [])
    monkeypatch.setattr(rdfs, "_filter_lottery", lambda rows, *_a, **_kw: rows)
    monkeypatch.setattr(rdfs, "_filter_days", lambda rows, *_a, **_kw: rows)
    monkeypatch.setattr(rdfs, "_dedupe_rows", lambda rows: rows)
    monkeypatch.setattr(rdfs, "save_rd_rows", lambda *_a, **_kw: {"ok": True, "rows_saved": 0, "rows_found": 0, "imported": 0, "updated": 0, "errors": []})
    monkeypatch.setattr(rdfs, "get_rd_lottery_config", lambda *_a, **_kw: {})

    out = rdfs.import_loteriasdominicanas("Lotería Real", days=90)
    assert out["ok"] is True
    # 1 fetch inicial + probes (max 3, con fallback "/") => acotado.
    assert calls["n"] <= 7


def test_cross_source_isolation_and_mutation_safety(monkeypatch):
    import models
    from models import get_all_lotteries, get_results, init_db
    from services.leidsa_service import save_leidsa_rows

    tmp_db = os.path.join(tempfile.gettempdir(), "rd_cross_source_isolation_test.db")
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
    old_db = models.DATABASE
    try:
        monkeypatch.setenv("DATABASE_PATH", tmp_db)
        monkeypatch.setattr(models, "DATABASE", tmp_db)
        init_db()
        lots = {l["name"]: l["id"] for l in get_all_lotteries() if l.get("country") == "RD"}

        row_a = {
            "lottery_name": "Lotería Real",
            "draw_name": "tarde",
            "draw_date": "2026-09-12",
            "numbers": ["32", "76", "06"],
            "source_url": "https://source-a.test",
        }
        row_b = {
            "lottery": "leidsa_quiniela_pale",
            "lottery_name": "LEIDSA Quiniela Palé",
            "draw": "tarde",
            "fecha_rd": "2026-09-12",
            "numeros": [61, 93, 98],
            "draw_time": "14:30",
            "fuente": "LEIDSA.com",
            "estado": "publicado",
        }

        a_out = rdfs.save_rd_rows([row_a], fuente="loteriadominicana", days=7, lottery_name="Lotería Real")
        b_out = save_leidsa_rows([row_b])
        assert a_out["ok"] is True
        assert b_out["ok"] is True

        # Mutar objetos originales no debe alterar lo persistido.
        row_a["numbers"][0] = "99"
        row_b["numeros"][0] = 0

        real_rows = get_results(lots["Lotería Real"], limit=1)
        leidsa_rows = get_results(lots["LEIDSA Quiniela Palé"], limit=1)

        assert real_rows and leidsa_rows
        assert real_rows[0]["numbers"] == "[\"32\", \"76\", \"06\"]"
        assert leidsa_rows[0]["numbers"] == "[\"61\", \"93\", \"98\"]"
        assert (real_rows[0].get("fuente") or "") == "loteriadominicana"
        assert (leidsa_rows[0].get("fuente") or "") == "LEIDSA.com"

        # Verifica no cruce de valores entre fuentes.
        assert real_rows[0]["numbers"] != leidsa_rows[0]["numbers"]
    finally:
        models.DATABASE = old_db
