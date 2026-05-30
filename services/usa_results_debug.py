"""Diagnóstico resultados USA — debug Render / fuentes."""
from __future__ import annotations

import logging
import os
import time

from models import count_results_for_lottery, get_all_lotteries, get_max_draw_date

logger = logging.getLogger(__name__)
LOG = "[USA DEBUG]"

ILLINOIS_HUB = "https://www.illinoislottery.com/results-hub"
LOTTERYUSA_HUB = "https://www.lotteryusa.com/illinois/"
LOTTERYPOST_HUB = "https://www.lotterypost.com/results/il"


def _usa_lotteries_summary() -> list[dict]:
    rows = []
    for lot in get_all_lotteries(active_only=True):
        if lot.get("country") != "USA":
            continue
        lid = lot["id"]
        cnt = count_results_for_lottery(lid)
        rows.append({
            "id": lid,
            "nombre": lot["name"],
            "estado": lot.get("state"),
            "cantidad_resultados": cnt,
            "ultima_fecha": get_max_draw_date(lid),
        })
    return rows


def _probe_illinois() -> dict:
    t0 = time.monotonic()
    out = {
        "fuente": "illinoislottery",
        "url": ILLINOIS_HUB,
        "ok": False,
        "status_code": None,
        "elapsed": None,
        "sorteos_encontrados": 0,
        "error": None,
    }
    try:
        from scrapers.usa_http import fetch_url
        from services.resultados.illinois_scraper import parse_results_hub_html

        page = fetch_url(
            ILLINOIS_HUB,
            valid_markers=("results-container",),
            source="illinoislottery",
            min_bytes=1000,
        )
        out["status_code"] = page.get("status_code")
        out["elapsed"] = page.get("elapsed") or round(time.monotonic() - t0, 2)
        out["size"] = page.get("size")
        if not page.get("ok"):
            out["error"] = page.get("error") or page.get("message")
            if "problem loading" in (page.get("html") or "").lower():
                out["error"] = "Illinois: problem loading game data"
            return out
        rows = parse_results_hub_html(page["html"])
        out["sorteos_encontrados"] = len(rows)
        out["ok"] = bool(rows)
        if not rows:
            out["error"] = "Hub accesible pero sin sorteos parseables"
    except Exception as exc:
        logger.exception("%s probe Illinois", LOG)
        out["error"] = str(exc)
        out["elapsed"] = round(time.monotonic() - t0, 2)
    return out


def _probe_lotteryusa() -> dict:
    from scrapers.lotteryusa_scraper import probe_lotteryusa
    return probe_lotteryusa()


def _probe_lotterypost() -> dict:
    from scrapers.lotterypost_scraper import probe_lotterypost
    return probe_lotterypost()


def build_usa_debug_report(*, probe_live: bool = True) -> dict:
    from scrapers.cache.usa_meta import load_last_run
    from scrapers.cache.usa_results_cache import load_results_snapshot

    last = load_last_run()
    snap = load_results_snapshot()
    lotteries = _usa_lotteries_summary()
    total_bd = sum(x["cantidad_resultados"] for x in lotteries)

    report = {
        "ok": True,
        "modulo": "USA",
        "entorno": os.environ.get("RENDER", "local"),
        "render_service": os.environ.get("RENDER_SERVICE_NAME"),
        "fuente_usada": last.get("fuente"),
        "status": last.get("status"),
        "fecha_actualizacion": last.get("fecha_actualizacion"),
        "cantidad_resultados": last.get("cantidad_resultados", total_bd),
        "imported_ultima": last.get("imported", 0),
        "updated_ultima": last.get("updated", 0),
        "cache_usado_ultima": last.get("cache_used"),
        "warning_ultima": last.get("warning"),
        "sources_tried_ultima": last.get("sources_tried", []),
        "fuentes_configuradas": [
            {"orden": 1, "id": "illinoislottery", "url": ILLINOIS_HUB},
            {"orden": 2, "id": "lotteryusa", "url": LOTTERYUSA_HUB},
            {"orden": 3, "id": "lotterypost", "url": LOTTERYPOST_HUB},
        ],
        "bd": {
            "total_resultados": total_bd,
            "por_loteria": lotteries,
        },
        "cache_json": {
            "disponible": bool(snap.get("ok")),
            "fuente": snap.get("fuente"),
            "fecha": snap.get("fecha"),
            "sorteos": snap.get("count") or len(snap.get("resultados") or []),
            "path": snap.get("cache_path"),
        },
        "http_config": {
            "timeout": os.environ.get("USA_FETCH_TIMEOUT", "35"),
            "retries": os.environ.get("USA_FETCH_RETRIES", "4"),
            "user_agent": "Chrome/122 (cloudscraper)",
        },
    }

    if probe_live:
        probes = []
        for fn in (_probe_illinois, _probe_lotteryusa, _probe_lotterypost):
            try:
                probes.append(fn())
            except Exception as exc:
                probes.append({"ok": False, "error": str(exc)})
        report["probe_fuentes"] = probes
        report["probe_ok"] = [p for p in probes if p.get("ok")]

    return report
