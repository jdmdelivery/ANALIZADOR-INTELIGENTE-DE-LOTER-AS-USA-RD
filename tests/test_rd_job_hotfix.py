from __future__ import annotations

import time

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
