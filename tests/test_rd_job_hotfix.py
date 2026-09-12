from __future__ import annotations

import time
import tempfile
import os
from datetime import datetime, timedelta

import requests

from services import rd_results_service as rdsvc
from services.rd_update_jobs import create_job, finish_job, get_job, start_job
from scrapers import rd_http
from scrapers import rd_fallback_scrapers as rdfs
from services import leidsa_service
from services import rd_stale
from services.rd_validation import validate_result


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


def test_source_health_ordering_prefers_recent_success(monkeypatch):
    monkeypatch.setattr(rd_http, "_SOURCE_DISABLED_UNTIL", {})
    monkeypatch.setattr(
        rd_http,
        "_SOURCE_HEALTH",
        {
            "enloteria": {"source": "enloteria", "success": 5, "failure": 0, "avg_latency_ms": 300, "failure_count": 0, "disabled_until": None, "reason": None},
            "loteriadominicana": {"source": "loteriadominicana", "success": 0, "failure": 4, "avg_latency_ms": 9000, "failure_count": 3, "disabled_until": None, "reason": "connect_timeout"},
        },
    )
    ordered = rd_http.rank_sources(["loteriadominicana", "enloteria"])
    assert ordered[0] == "enloteria"


def test_disabled_source_skipped_with_circuit_breaker(monkeypatch):
    class _Sess:
        def get(self, *_a, **_kw):
            raise requests.Timeout("connect timeout")

    monkeypatch.setattr(rd_http, "_SOURCE_DISABLED_UNTIL", {})
    monkeypatch.setattr(rd_http, "_SOURCE_HEALTH", {})
    monkeypatch.setattr(rd_http, "get_rd_session", lambda: _Sess())
    monkeypatch.setattr(rd_http.time, "sleep", lambda *_a, **_kw: None)
    first = rd_http.fetch_rd_url("https://x.test", source="loteriadominicana", retries=1, timeout=(0.05, 0.05))
    second = rd_http.fetch_rd_url("https://x.test", source="loteriadominicana", retries=1, timeout=(0.05, 0.05))
    assert first["ok"] is False
    assert second["ok"] is False
    assert "deshabilitada" in (second.get("error") or "").lower()


def test_stale_result_does_not_satisfy_scope(monkeypatch):
    monkeypatch.setattr(rdsvc, "get_all_lotteries", lambda: [{"id": 1, "name": "Lotería Real", "country": "RD", "type": "rd_loteria_real"}])
    monkeypatch.setattr(rdsvc, "find_lottery_in_list", lambda *_a, **_kw: {"id": 1, "name": "Lotería Real", "country": "RD", "type": "rd_loteria_real"})
    monkeypatch.setattr(rdsvc, "_effective_days_from_last_date", lambda *_a, **_kw: (30, "2026-08-01", "2026-09-12"))
    monkeypatch.setattr(rdsvc, "_stale_threshold_for_lottery", lambda _lot: 3)
    monkeypatch.setattr(rdsvc, "get_max_draw_date", lambda *_a, **_kw: "2026-07-01")
    monkeypatch.setattr(rdsvc, "_run_fallback", lambda *_a, **_kw: {"ok": True, "imported": 1, "updated": 0, "rows_found": 1, "message": "ok"})
    monkeypatch.setattr(rdsvc, "_run_conectate_primary", lambda *_a, **_kw: {"ok": False, "message": "x"})
    monkeypatch.setattr(rdfs, "import_conectate_api", lambda *_a, **_kw: {"ok": False, "message": "x"})
    out = rdsvc.actualizar_rd_loteria("Lotería Real", days=30)
    assert out.get("ok") in (False, True)
    assert any("stale_source_result" in e for e in out.get("errors", []))


def test_current_result_stops_chain(monkeypatch):
    calls = []
    monkeypatch.setattr(rdsvc, "get_all_lotteries", lambda: [{"id": 1, "name": "Lotería Real", "country": "RD", "type": "rd_loteria_real"}])
    monkeypatch.setattr(rdsvc, "find_lottery_in_list", lambda *_a, **_kw: {"id": 1, "name": "Lotería Real", "country": "RD", "type": "rd_loteria_real"})
    monkeypatch.setattr(rdsvc, "_effective_days_from_last_date", lambda *_a, **_kw: (30, "2026-09-10", "2026-09-12"))
    monkeypatch.setattr(rdsvc, "_stale_threshold_for_lottery", lambda _lot: 3)
    monkeypatch.setattr(rdsvc, "get_max_draw_date", lambda *_a, **_kw: "2026-09-12")

    def fake_run(key, *_a, **_kw):
        calls.append(key)
        if key == "enloteria":
            return {"ok": True, "imported": 1, "updated": 0, "rows_found": 1}
        return {"ok": False, "message": "should not be called"}

    monkeypatch.setattr(rdsvc, "_run_fallback", fake_run)
    out = rdsvc.actualizar_rd_loteria("Lotería Real", days=30)
    assert out["ok"] is True
    assert calls[0] == "enloteria"
    assert "loteriadominicana" not in calls


def test_leidsa_super_kino_20_numbers_accepted():
    ok, err = validate_result(
        {
            "lottery_name": "LEIDSA Super Kino TV",
            "draw_name": "noche",
            "draw_date": "2026-09-12",
            "numbers": [f"{n:02d}" for n in range(1, 21)],
        },
        lottery_type="leidsa_super_kino_tv",
    )
    assert ok is True
    assert err == ""


def test_leidsa_official_preferred_over_generic_fallback(monkeypatch):
    monkeypatch.setattr(
        leidsa_service,
        "scrape_leidsa_prefer_official",
        lambda: {
            "ok": True,
            "results": [
                {"lottery": "leidsa_quiniela_pale", "lottery_name": "LEIDSA Quiniela Palé", "draw": "tarde", "fecha_rd": "2026-09-12", "numeros": [1, 2, 3], "draw_time": "14:30", "fuente": "LEIDSA.com"}
            ],
            "parser": "leidsa_official",
            "fuente": "leidsa_official",
            "fuente_label": "LEIDSA.com",
            "latest_date": "2026-09-12",
        },
    )
    monkeypatch.setattr(leidsa_service, "save_leidsa_rows", lambda *_a, **_kw: {"ok": True, "inserted": 1, "updated": 0, "skipped": 0})
    out = leidsa_service.update_leidsa_now()
    assert out["ok"] is True
    assert "LEIDSA.com" in (out.get("message") or "")


def test_second_run_faster_via_circuit_breaker(monkeypatch):
    calls = {"n": 0}

    class _Sess:
        def get(self, *_a, **_kw):
            calls["n"] += 1
            raise requests.Timeout("connect timeout")

    monkeypatch.setattr(rd_http, "_SOURCE_DISABLED_UNTIL", {})
    monkeypatch.setattr(rd_http, "_SOURCE_HEALTH", {})
    monkeypatch.setattr(rd_http, "get_rd_session", lambda: _Sess())
    monkeypatch.setattr(rd_http.time, "sleep", lambda *_a, **_kw: None)
    t0 = time.monotonic()
    rd_http.fetch_rd_url("https://x.test", source="loteriadominicana", retries=2, timeout=(0.05, 0.05))
    d1 = time.monotonic() - t0
    t1 = time.monotonic()
    rd_http.fetch_rd_url("https://x.test", source="loteriadominicana", retries=2, timeout=(0.05, 0.05))
    d2 = time.monotonic() - t1
    assert d2 < d1
    assert calls["n"] == 2


def test_connect_timeout_source_fast_fail_budget(monkeypatch):
    class _Sess:
        def get(self, *_a, **_kw):
            raise requests.Timeout("connect timeout")

    monkeypatch.setattr(rd_http, "_SOURCE_DISABLED_UNTIL", {})
    monkeypatch.setattr(rd_http, "_SOURCE_HEALTH", {})
    monkeypatch.setattr(rd_http, "get_rd_session", lambda: _Sess())
    monkeypatch.setattr(rd_http.time, "sleep", lambda *_a, **_kw: None)
    t0 = time.monotonic()
    out = rd_http.fetch_rd_url("https://x.test", source="loteriadominicana", retries=1, timeout=(0.05, 0.05))
    elapsed = time.monotonic() - t0
    assert out["ok"] is False
    assert elapsed < 1.0


def test_render_simulation_completes_fast_with_alive_source(monkeypatch):
    monkeypatch.setattr(rdsvc, "get_all_lotteries", lambda: [{"id": 1, "name": "Lotería Real", "country": "RD", "type": "rd_loteria_real"}])
    monkeypatch.setattr(rdsvc, "find_lottery_in_list", lambda *_a, **_kw: {"id": 1, "name": "Lotería Real", "country": "RD", "type": "rd_loteria_real"})
    monkeypatch.setattr(rdsvc, "_effective_days_from_last_date", lambda *_a, **_kw: (30, "2026-09-10", "2026-09-12"))
    monkeypatch.setattr(rdsvc, "_stale_threshold_for_lottery", lambda _lot: 3)
    monkeypatch.setattr(rdsvc, "get_max_draw_date", lambda *_a, **_kw: "2026-09-12")

    calls = []

    def fake_run(key, *_a, **_kw):
        calls.append(key)
        if key == "enloteria":
            return {"ok": True, "imported": 1, "updated": 0, "rows_found": 1, "status_code": 200}
        if key == "loteriadominicana":
            return {"ok": False, "error": "ConnectTimeout", "message": "ConnectTimeout"}
        return {"ok": False, "status_code": 403, "message": "HTTP 403"}

    monkeypatch.setattr(rdsvc, "_run_fallback", fake_run)
    t0 = time.monotonic()
    out = rdsvc.actualizar_rd_loteria("Lotería Real", days=30, max_job_seconds=120)
    elapsed = time.monotonic() - t0
    assert out["ok"] is True
    assert out.get("fuente") == "enloteria"
    assert elapsed < 2.0
    assert calls == ["enloteria"]


def test_job_soft_budget_stops_early(monkeypatch):
    monkeypatch.setattr(rdsvc, "SOFT_RD_JOB_SECONDS", 1)
    monkeypatch.setattr(rdsvc, "iter_enabled_conectate_configs", lambda: [("A", {"db_names": ["Lotería Real"]}), ("B", {"db_names": ["Loteka"]})])
    monkeypatch.setattr(rdsvc, "normalize_lottery_name", lambda x: x.lower())
    monkeypatch.setattr(rdsvc, "actualizar_leidsa_multi", lambda **_kw: {"ok": True, "imported": 0, "updated": 0, "sources_tried": []})
    monkeypatch.setattr(rdsvc, "find_lottery_in_list", lambda *_a, **_kw: {"id": 1, "name": "Lotería Real"})
    monkeypatch.setattr(rdsvc, "get_all_lotteries", lambda: [{"id": 1, "name": "Lotería Real", "country": "RD"}])
    monkeypatch.setattr(rdsvc, "get_max_draw_date", lambda *_a, **_kw: "2026-09-12")

    def _lot(*_a, **_kw):
        time.sleep(1.1)
        return {"ok": True, "imported": 1, "updated": 0, "sources_tried": []}

    monkeypatch.setattr(rdsvc, "actualizar_rd_loteria", _lot)
    out = rdsvc.actualizar_rd_todas(days=30, job_id="j-soft", max_job_seconds=120)
    assert out["ok"] is True
    assert any("soft budget" in e for e in out.get("errors", []))


def test_priority_scopes_run_before_soft_budget_break(monkeypatch):
    monkeypatch.setattr(rdsvc, "SOFT_RD_JOB_SECONDS", 1)
    monkeypatch.setattr(rdsvc, "LEIDSA_PRIORITY_BUDGET_SECONDS", 1)
    monkeypatch.setattr(rdsvc, "REAL_PRIORITY_BUDGET_SECONDS", 1)
    monkeypatch.setattr(
        rdsvc,
        "iter_enabled_conectate_configs",
        lambda: [("Real", {"db_names": ["Lotería Real"]}), ("Sec", {"db_names": ["Loteka"]})],
    )
    monkeypatch.setattr(rdsvc, "normalize_lottery_name", lambda x: x.lower())
    monkeypatch.setattr(rdsvc, "find_lottery_in_list", lambda *_a, **_kw: {"id": 1, "name": "Lotería Real"})
    monkeypatch.setattr(rdsvc, "get_all_lotteries", lambda: [{"id": 1, "name": "Lotería Real", "country": "RD"}])
    monkeypatch.setattr(rdsvc, "get_max_draw_date", lambda *_a, **_kw: "2026-09-12")

    calls = []

    def _leidsa(**_kw):
        time.sleep(0.2)
        calls.append("LEIDSA")
        return {"ok": True, "imported": 1, "updated": 0, "sources_tried": []}

    def _lot(db_name, **_kw):
        calls.append(db_name)
        time.sleep(0.9 if db_name == "Lotería Real" else 0.4)
        return {"ok": True, "imported": 1, "updated": 0, "sources_tried": []}

    monkeypatch.setattr(rdsvc, "actualizar_leidsa_multi", _leidsa)
    monkeypatch.setattr(rdsvc, "actualizar_rd_loteria", _lot)
    out = rdsvc.actualizar_rd_todas(days=30, job_id="j-priority", max_job_seconds=120)
    assert "LEIDSA" in calls
    assert "Lotería Real" in calls
    assert out.get("priority_completed") is True
    assert any("soft budget" in e for e in out.get("errors", []))


def test_secondaries_can_be_skipped_after_priority(monkeypatch):
    monkeypatch.setattr(rdsvc, "SOFT_RD_JOB_SECONDS", 1)
    monkeypatch.setattr(
        rdsvc,
        "iter_enabled_conectate_configs",
        lambda: [
            ("Real", {"db_names": ["Lotería Real"]}),
            ("SecA", {"db_names": ["Loteka"]}),
            ("SecB", {"db_names": ["Nacional"]}),
        ],
    )
    monkeypatch.setattr(rdsvc, "normalize_lottery_name", lambda x: x.lower())
    monkeypatch.setattr(rdsvc, "find_lottery_in_list", lambda *_a, **_kw: {"id": 1, "name": "Lotería Real"})
    monkeypatch.setattr(rdsvc, "get_all_lotteries", lambda: [{"id": 1, "name": "Lotería Real", "country": "RD"}])
    monkeypatch.setattr(rdsvc, "get_max_draw_date", lambda *_a, **_kw: "2026-09-12")
    monkeypatch.setattr(rdsvc, "actualizar_leidsa_multi", lambda **_kw: {"ok": True, "imported": 1, "updated": 0, "sources_tried": []})
    seen = []

    def _lot(db_name, **_kw):
        seen.append(db_name)
        time.sleep(0.9 if db_name == "Lotería Real" else 0.4)
        return {"ok": True, "imported": 1, "updated": 0, "sources_tried": []}

    monkeypatch.setattr(rdsvc, "actualizar_rd_loteria", _lot)
    out = rdsvc.actualizar_rd_todas(days=30, job_id="j-soft2", max_job_seconds=120)
    assert seen[0] == "Lotería Real"
    assert any("soft budget" in e for e in out.get("errors", []))


def test_leidsa_priority_sync_fetches_official_once(monkeypatch):
    calls = {"scrape": 0}

    def _scrape():
        calls["scrape"] += 1
        return {
            "ok": True,
            "results": [
                {
                    "lottery": "leidsa_quiniela_pale",
                    "lottery_name": "LEIDSA Quiniela Palé",
                    "draw": "noche",
                    "fecha_rd": "2026-09-11",
                    "numeros": [21, 46, 88],
                    "draw_time": "20:55",
                    "fuente": "LEIDSA.com",
                }
            ],
            "parser": "leidsa_official",
            "latest_date": "2026-09-11",
            "fuente": "leidsa_official",
            "fuente_label": "LEIDSA.com",
        }

    monkeypatch.setattr("services.leidsa_service.scrape_leidsa_prefer_official", _scrape)
    monkeypatch.setattr("services.leidsa_service.save_leidsa_rows", lambda *_a, **_kw: {"ok": True, "inserted": 1, "updated": 0, "ignored": 0, "skipped": 0})
    monkeypatch.setattr("services.leidsa_service._latest_saved_leidsa_date", lambda: "2026-09-11")
    monkeypatch.setattr(
        "services.leidsa_service.sync_priority_games_from_cached_scrape",
        lambda slugs, **_kw: {
            "ok": True,
            "inserted": 1,
            "updated": 0,
            "results_found": 1,
            "games": {slugs[0]: {"latest_date": "2026-09-12", "rows_found": 1}},
        },
    )
    monkeypatch.setattr("models.get_lottery_by_slug", lambda slug: {"id": 1 if slug == "leidsa_quiniela_pale" else 2, "name": slug})
    monkeypatch.setattr(rdsvc, "get_max_draw_date", lambda lid: "2026-06-24" if lid == 2 else "2026-09-12")
    out = rdsvc.actualizar_leidsa_multi(days=30, max_job_seconds=120)
    assert out.get("ok") is True
    assert calls["scrape"] == 1


def test_leidsa_priority_uses_cached_payload_not_incremental_backfill(monkeypatch):
    calls = {"priority": 0}

    monkeypatch.setattr(
        "services.leidsa_service.scrape_leidsa_prefer_official",
        lambda: {
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
            "latest_date": "2026-09-12",
            "fuente": "leidsa_official",
            "fuente_label": "LEIDSA.com",
        },
    )
    monkeypatch.setattr("services.leidsa_service.save_leidsa_rows", lambda *_a, **_kw: {"ok": True, "inserted": 1, "updated": 1, "ignored": 0, "skipped": 0})

    def _priority(slugs, **_kw):
        calls["priority"] += 1
        return {
            "ok": True,
            "inserted": 1,
            "updated": 0,
            "results_found": 1,
            "games": {slugs[0]: {"latest_date": "2026-09-12", "rows_found": 1}},
        }

    monkeypatch.setattr("services.leidsa_service.sync_priority_games_from_cached_scrape", _priority)
    monkeypatch.setattr("models.get_lottery_by_slug", lambda slug: {"id": 1 if slug == "leidsa_quiniela_pale" else 2, "name": slug})
    monkeypatch.setattr(rdsvc, "get_max_draw_date", lambda lid: "2026-06-24" if lid == 2 else "2026-09-12")
    out = rdsvc.actualizar_leidsa_multi(days=30, max_job_seconds=120)
    assert out.get("ok") is True
    assert calls["priority"] == 1


def test_leidsa_recent_upsert_visible_in_latest_query(monkeypatch):
    import models
    from models import get_all_lotteries, get_results, init_db
    from services.leidsa_service import save_leidsa_rows

    tmp_db = os.path.join(tempfile.gettempdir(), "rd_leidsa_latest_query_test.db")
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
    old_db = models.DATABASE
    try:
        monkeypatch.setenv("DATABASE_PATH", tmp_db)
        monkeypatch.setattr(models, "DATABASE", tmp_db)
        init_db()
        lots = {l["name"]: l["id"] for l in get_all_lotteries() if l.get("country") == "RD"}
        rows = [
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
        ]
        out = save_leidsa_rows(rows)
        assert out["ok"] is True

        q_rows = get_results(lots["LEIDSA Quiniela Palé"], limit=1)
        sk_rows = get_results(lots["LEIDSA Super Kino TV"], limit=1)
        assert q_rows and sk_rows
        assert q_rows[0]["draw_date"] == "2026-09-12"
        assert sk_rows[0]["draw_date"] == "2026-09-11"
    finally:
        models.DATABASE = old_db


def test_stale_super_kino_marks_source_unavailable_reason(monkeypatch):
    monkeypatch.setattr(
        rd_stale,
        "get_all_lotteries",
        lambda active_only=True: [
            {"id": 19, "name": "LEIDSA Super Kino TV", "country": "RD", "type": "leidsa_super_kino_tv"}
        ],
    )
    monkeypatch.setattr(
        rd_stale,
        "get_draw_times",
        lambda lottery_id, active_only=True: [{"draw_name": "noche", "draw_time": "20:00"}],
    )
    monkeypatch.setattr(rd_stale, "get_latest_result_date_for_scope", lambda *_a, **_kw: "2026-07-17")
    monkeypatch.setattr(rd_stale, "_threshold_for_lottery", lambda _lot: 3)
    monkeypatch.setattr(
        leidsa_service,
        "get_leidsa_source_diagnostic",
        lambda: {
            "leidsa_official": {"blocked": True},
            "super_kino": {"fallback_available": False, "reason": "source_unavailable"},
        },
    )
    out = rd_stale.build_rd_stale_status()
    assert out["ok"] is True
    scope = out["scopes"][0]
    assert scope["status"] == "STALE"
    assert scope["reason"] == "source_unavailable"
    assert scope["source_blocked"] is True
