"""Actualización resultados USA — solo Illinois Hub. Sin LEIDSA/Conectate."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
LOG_PREFIX = "[USA]"


def refresh_usa_results(
    state: str | None = None,
    lottery: str | None = None,
    days: int = 30,
    refresh_all: bool = True,
) -> dict:
    state_low = (state or "Illinois").strip().lower()
    if state_low != "illinois":
        return {
            "ok": False,
            "status": "error",
            "message": "Solo Illinois está soportado para USA en este momento.",
        }

    from models import count_results_for_lottery, get_all_lotteries
    from scrapers_usa.illinois import refresh_usa_illinois

    def _db_fallback(lot_name: str | None) -> dict | None:
        lotteries = get_all_lotteries(active_only=True)
        if lot_name:
            targets = [l for l in lotteries if l.get("country") == "USA" and l["name"] == lot_name]
        else:
            targets = [l for l in lotteries if l.get("country") == "USA"]
        saved = sum(count_results_for_lottery(l["id"]) for l in targets)
        if saved > 0:
            return {
                "ok": True,
                "status": "cached_fallback",
                "used_db_fallback": True,
                "saved_count": saved,
                "message": (
                    "⚠️ No se pudo actualizar ahora, pero se muestran resultados guardados."
                ),
                "imported": 0,
                "updated": 0,
            }
        return None

    try:
        result = refresh_usa_illinois(
            lottery_name=lottery,
            refresh_all=refresh_all or not lottery,
        )
    except Exception as exc:
        logger.exception("%s Illinois error", LOG_PREFIX)
        result = {"ok": False, "message": str(exc), "errors": [str(exc)]}

    if result.get("ok"):
        return result

    fallback = _db_fallback(lottery)
    if fallback:
        fallback["hub_error"] = result.get("message")
        fallback["errors"] = result.get("errors", [])
        return fallback

    result["message"] = result.get(
        "message",
        "⚠️ Illinois Results Hub no respondió. Mostrando últimos resultados guardados.",
    )
    return result
