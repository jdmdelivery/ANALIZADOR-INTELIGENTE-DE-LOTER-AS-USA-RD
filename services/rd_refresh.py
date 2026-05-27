"""Actualización resultados RD — LEIDSA + Conectate. Sin Illinois."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
LOG_PREFIX = "[RD]"


def refresh_rd_results(
    lottery: str | None = None,
    days: int = 30,
    refresh_all: bool = False,
) -> dict:
    if refresh_all or not lottery:
        from services.history_fetch import fetch_all_rd_history

        logger.info("%s Actualizando historial RD completo (%s días)", LOG_PREFIX, days)
        return fetch_all_rd_history(days=int(days or 30))

    from importers import refresh_lottery_results_now

    return refresh_lottery_results_now(
        "RD",
        state="",
        lottery=lottery,
        days=days,
        refresh_all_usa=False,
    )
