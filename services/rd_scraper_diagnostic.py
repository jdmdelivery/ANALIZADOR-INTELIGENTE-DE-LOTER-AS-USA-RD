"""Estado y diagnóstico de scrapers RD — solo República Dominicana."""
from __future__ import annotations

import time
from datetime import datetime

from models import count_results_for_lottery, get_all_lotteries, get_max_draw_date

_LAST_RUNS: dict[str, dict] = {}

SCRAPER_DEFS = [
    {
        "key": "conectate_api",
        "nombre": "Conectate API (Kiskoo)",
        "parser": "kiskoo_nuxt / nuxt-sessions-v2",
        "tipo": "api",
    },
    {
        "key": "conectate_primary",
        "nombre": "Conectate.com.do (HTML)",
        "parser": "nuxt_draw_pages + game-block",
        "tipo": "html",
    },
    {
        "key": "conectate",
        "nombre": "Conectate Hub (fallback)",
        "parser": "kiskoo_nuxt + HTML hub",
        "tipo": "html",
    },
    {
        "key": "loteriasdominicanas",
        "nombre": "LoteriasDominicanas.com",
        "parser": "kiskoo_nuxt + HTML",
        "tipo": "html",
    },
    {
        "key": "loteriadominicana",
        "nombre": "LoteriaDominicana.com.do",
        "parser": "HTML tablas + títulos",
        "tipo": "html",
    },
    {
        "key": "enloteria",
        "nombre": "EnLoteria.com",
        "parser": "HTML bloques + títulos",
        "tipo": "html",
    },
    {
        "key": "leidsa",
        "nombre": "LEIDSA.com",
        "parser": "leidsa_service / leidsa_history",
        "tipo": "oficial",
    },
]


def record_scraper_run(key: str, entry: dict) -> None:
    """Registra última ejecución de una fuente (memoria de proceso)."""
    _LAST_RUNS[key] = {
        **entry,
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
    }


def _lottery_db_summary() -> list[dict]:
    rows = []
    for lot in get_all_lotteries(active_only=True):
        if lot.get("country") != "RD":
            continue
        lid = lot["id"]
        rows.append({
            "lottery": lot["name"],
            "sorteos": count_results_for_lottery(lid),
            "ultima_fecha": get_max_draw_date(lid),
        })
    rows.sort(key=lambda r: r["lottery"])
    return rows


def build_scrapers_admin_report(*, probe_live: bool = True) -> dict:
    """Informe completo para /admin/diagnostico-scrapers."""
    from services.rd_results_debug import build_rd_debug_report

    t0 = time.monotonic()
    live = build_rd_debug_report(probe_live=probe_live) if probe_live else {"ok": True, "sources": {}}

    scrapers: list[dict] = []
    active_key = ""
    for defn in SCRAPER_DEFS:
        last = _LAST_RUNS.get(defn["key"], {})
        live_src = None
        if defn["key"] == "conectate_api":
            live_src = live.get("sources", {}).get("conectate_sessions_api")
        elif defn["key"] == "conectate_primary":
            live_src = live.get("sources", {}).get("conectate_hub_parser")
        elif defn["key"] == "conectate":
            live_src = live.get("sources", {}).get("conectate_hub_parser")
        elif defn["key"] == "loteriasdominicanas":
            live_src = live.get("sources", {}).get("loteriasdominicanas_sessions_api")

        ok_live = live_src.get("ok") if live_src else None
        if ok_live and defn["key"] in ("conectate_api", "conectate_primary", "conectate"):
            active_key = active_key or defn["key"]

        scrapers.append({
            **defn,
            "ultima_ejecucion": last.get("recorded_at"),
            "ultimo_ok": last.get("ok") if last else None,
            "ultimo_status": last.get("status_code") or last.get("status"),
            "ultimo_tiempo": last.get("elapsed"),
            "ultimo_error": last.get("error"),
            "ultima_url": last.get("url"),
            "ultimos_sorteos": last.get("sorteos"),
            "ultima_fecha_obtenida": last.get("ultima_fecha"),
            "probe_ok": ok_live,
            "probe_status": live_src.get("status_code") if live_src else None,
            "probe_error": live_src.get("error") if live_src else None,
            "probe_elapsed": live_src.get("elapsed") if live_src else None,
        })

    return {
        "ok": live.get("ok", True),
        "pais": "DO",
        "git_commit": live.get("git_commit"),
        "parser_version": live.get("parser_version"),
        "elapsed_total": round(time.monotonic() - t0, 2),
        "live_probe": live,
        "fuente_activa_sugerida": active_key or "ninguna",
        "scrapers": scrapers,
        "loterias_bd": _lottery_db_summary(),
        "message": live.get("message", ""),
    }
