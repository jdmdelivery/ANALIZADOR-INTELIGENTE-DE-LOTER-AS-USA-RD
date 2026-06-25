"""Diagnóstico fuentes RD (Conectate / Loterías Dominicanas) — no toca USA."""
from __future__ import annotations

import os
import subprocess
import time


def _git_commit_short() -> str:
    sha = os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("GIT_COMMIT") or ""
    if sha:
        return sha[:12]
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return out.decode().strip()
    except Exception:
        return "unknown"


def build_rd_debug_report(*, probe_live: bool = True) -> dict:
    from scrapers.kiskoo_nuxt_parser import (
        CONECTATE_API,
        CONECTATE_PAYLOAD,
        KISKOO_PARSER_VERSION,
        LD_API,
        LD_PAYLOAD,
        fetch_hub_rows,
        fetch_json,
        fetch_sessions,
    )

    report: dict = {
        "ok": True,
        "pais": "DO",
        "git_commit": _git_commit_short(),
        "parser_version": KISKOO_PARSER_VERSION,
        "parser": "kiskoo_nuxt",
        "sources": {},
    }

    if not probe_live:
        report["message"] = "Diagnóstico sin sondeo en vivo (probe=0)."
        return report

    t0 = time.monotonic()

    payload_c = fetch_json(CONECTATE_PAYLOAD, source="diag_conectate_payload")
    sess_c = fetch_sessions(CONECTATE_API, source="diag_conectate_api")
    hub_c = fetch_hub_rows(days=7, source_label="diag_conectate_hub")

    payload_ld = fetch_json(LD_PAYLOAD, source="diag_ld_payload")
    sess_ld = fetch_sessions(LD_API, source="diag_ld_api")
    hub_ld = fetch_hub_rows(
        api_base=LD_API,
        payload_url=LD_PAYLOAD,
        days=7,
        source_label="diag_ld_hub",
    )

    report["sources"]["conectate_payload"] = {
        "url": CONECTATE_PAYLOAD,
        "ok": payload_c.get("ok"),
        "status_code": payload_c.get("status_code"),
        "elapsed": payload_c.get("elapsed"),
        "error": payload_c.get("error"),
    }
    report["sources"]["conectate_sessions_api"] = {
        "url": f"{CONECTATE_API}/conectate/sessions",
        "ok": sess_c.get("ok"),
        "status_code": sess_c.get("status_code"),
        "elapsed": sess_c.get("elapsed"),
        "sessions_count": len(sess_c.get("data") or []) if sess_c.get("ok") else 0,
        "error": sess_c.get("error"),
    }
    report["sources"]["conectate_hub_parser"] = {
        "ok": hub_c.get("ok"),
        "status_code": hub_c.get("status_code"),
        "url": hub_c.get("url"),
        "elapsed": hub_c.get("elapsed"),
        "rows": len(hub_c.get("rows") or []),
        "game_map_size": hub_c.get("game_map_size"),
        "error": hub_c.get("error"),
        "sample_dates": sorted(
            {r.get("draw_date") for r in (hub_c.get("rows") or []) if r.get("draw_date")},
            reverse=True,
        )[:5],
    }
    report["sources"]["loteriasdominicanas_payload"] = {
        "url": LD_PAYLOAD,
        "ok": payload_ld.get("ok"),
        "status_code": payload_ld.get("status_code"),
        "elapsed": payload_ld.get("elapsed"),
        "error": payload_ld.get("error"),
    }
    report["sources"]["loteriasdominicanas_sessions_api"] = {
        "url": f"{LD_API}/conectate/sessions",
        "ok": sess_ld.get("ok"),
        "status_code": sess_ld.get("status_code"),
        "elapsed": sess_ld.get("elapsed"),
        "sessions_count": len(sess_ld.get("data") or []) if sess_ld.get("ok") else 0,
        "error": sess_ld.get("error"),
    }
    report["sources"]["loteriasdominicanas_hub_parser"] = {
        "ok": hub_ld.get("ok"),
        "rows": len(hub_ld.get("rows") or []),
        "error": hub_ld.get("error"),
    }

    live_ok = bool(hub_c.get("ok") and (hub_c.get("rows") or hub_ld.get("rows")))
    report["live_ok"] = live_ok
    report["elapsed_total"] = round(time.monotonic() - t0, 2)
    if not live_ok:
        report["ok"] = False
        errs = []
        for key, src in report["sources"].items():
            if src.get("error"):
                errs.append(f"{key}: {src['error']}")
        report["errors"] = errs
        report["message"] = "Ninguna fuente RD devolvió filas parseables."
    else:
        report["message"] = (
            f"Parser {KISKOO_PARSER_VERSION}: "
            f"Conectate {len(hub_c.get('rows') or [])} filas, "
            f"LD {len(hub_ld.get('rows') or [])} filas."
        )
    return report
