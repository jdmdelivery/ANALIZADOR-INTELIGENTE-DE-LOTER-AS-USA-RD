"""Tests cadena actualización RD — sin tocar USA."""
from __future__ import annotations

from unittest.mock import patch


def test_needs_fallback_on_403():
    from services.rd_results_service import _needs_fallback

    assert _needs_fallback({"ok": False, "status_code": 403}) is True
    assert _needs_fallback({"ok": True, "status_code": 403}) is True


def test_needs_fallback_ok_when_saved():
    from services.rd_results_service import _needs_fallback

    assert _needs_fallback({"ok": True, "imported": 2, "updated": 0}) is False


def test_needs_fallback_ok_when_rows_no_save():
    from services.rd_results_service import _needs_fallback

    assert _needs_fallback({"ok": True, "rows_found": 5, "imported": 0, "updated": 0}) is False


def test_import_conectate_api_tries_ld_on_403():
    from scrapers.rd_fallback_scrapers import import_conectate_api

    hub_403 = {"ok": False, "status_code": 403, "error": "HTTP 403", "rows": []}
    hub_ok = {
        "ok": True,
        "status_code": 200,
        "rows": [
            {
                "lottery_name": "Gana Más",
                "draw_name": "tarde",
                "draw_date": "2026-06-24",
                "numbers": ["01", "02", "03"],
                "source_url": "https://api.test/sessions",
            }
        ],
        "url": "https://api.test/sessions",
        "elapsed": 0.5,
        "parser": "nuxt-sessions-v2",
    }

    with patch("scrapers.kiskoo_nuxt_parser.fetch_hub_rows", side_effect=[hub_403, hub_ok]):
        with patch("scrapers.rd_fallback_scrapers.save_rd_rows") as save:
            save.return_value = {
                "ok": True,
                "imported": 1,
                "updated": 0,
                "rows_found": 1,
                "rows_saved": 1,
                "errors": [],
            }
            res = import_conectate_api("Gana Más", days=7)

    assert res.get("ok") is True
    assert "Loterías Dominicanas" in (res.get("fuente_label") or "")


def test_fetch_json_uses_rd_http(monkeypatch):
    from scrapers import kiskoo_nuxt_parser as kn

    calls = []

    def fake_fetch(url, **kw):
        calls.append(url)
        return {"ok": True, "data": [], "status_code": 200, "url": url, "elapsed": 0.1}

    monkeypatch.setattr(kn, "fetch_rd_json", fake_fetch)
    out = kn.fetch_json("https://example.com/test.json", source="test")
    assert out["ok"] is True
    assert calls


def test_api_error_json_shape():
    from app import _api_json_error

    payload, status = _api_json_error("fallo", detalle="det", fuente="rd", status=500)
    assert status == 500
    assert payload["ok"] is False
    assert payload["error"] == "fallo"
    assert payload["detalle"] == "det"
    assert payload["fuente"] == "rd"
    assert payload["status"] == 500
