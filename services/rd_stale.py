"""Detección de datos estancados por lotería/sorteo RD."""
from __future__ import annotations

import os
from datetime import datetime

from models import get_all_lotteries, get_draw_times, get_latest_result_date_for_scope
from services.rd_time import today_rd


def _days_since(iso_date: str | None) -> int | None:
    if not iso_date:
        return None
    try:
        d = datetime.strptime(str(iso_date)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (today_rd() - d).days


def _threshold_for_lottery(lottery: dict) -> int:
    base = int(os.environ.get("RD_STALE_THRESHOLD_DAYS", "3"))
    ltype = (lottery.get("type") or "").lower()
    if ltype.startswith("leidsa_"):
        return int(os.environ.get("RD_STALE_THRESHOLD_LEIDSA_DAYS", str(base)))
    return int(os.environ.get("RD_STALE_THRESHOLD_DEFAULT_DAYS", str(base)))


def build_rd_stale_status() -> dict:
    scopes: list[dict] = []
    leidsa_diag = {}
    try:
        from services.leidsa_service import get_leidsa_source_diagnostic

        leidsa_diag = get_leidsa_source_diagnostic() or {}
    except Exception:
        leidsa_diag = {}
    for lot in get_all_lotteries(active_only=True):
        if (lot.get("country") or "").upper() != "RD":
            continue
        threshold = _threshold_for_lottery(lot)
        for draw in get_draw_times(lot["id"], active_only=True):
            latest = get_latest_result_date_for_scope(
                lot["id"],
                draw_name=draw.get("draw_name"),
                draw_time=draw.get("draw_time"),
            )
            age = _days_since(latest)
            stale = age is None or age > threshold
            scopes.append(
                {
                    "lottery_id": lot["id"],
                    "lottery": lot["name"],
                    "lottery_type": lot.get("type"),
                    "draw_name": draw.get("draw_name"),
                    "draw_time": draw.get("draw_time"),
                    "latest_date": latest,
                    "age_days": age,
                    "threshold_days": threshold,
                    "status": "STALE" if stale else "FRESH",
                    "fresh": not stale,
                    "reason": "",
                }
            )
            if stale and (lot.get("type") or "") == "leidsa_super_kino_tv":
                sk = (leidsa_diag.get("super_kino") or {})
                reason = sk.get("reason") or "source_unavailable"
                scopes[-1]["reason"] = reason
                scopes[-1]["fallback_available"] = bool(sk.get("fallback_available"))
                scopes[-1]["source_blocked"] = bool((leidsa_diag.get("leidsa_official") or {}).get("blocked"))
    stale_count = len([s for s in scopes if s["status"] == "STALE"])
    return {
        "ok": True,
        "scopes": scopes,
        "stale_count": stale_count,
        "total_scopes": len(scopes),
        "leidsa_diagnostic": leidsa_diag,
    }
