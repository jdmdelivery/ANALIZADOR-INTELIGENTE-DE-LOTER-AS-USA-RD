"""Punto de entrada RD — LEIDSA (sin dependencias Illinois)."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
LOG_PREFIX = "[RD]"


def scrape_leidsa_results():
    from services.leidsa_service import scrape_leidsa_results as _scrape

    result = _scrape()
    if result.get("ok"):
        n = len(result.get("results") or result.get("rows") or [])
        logger.info("%s LEIDSA parser OK — resultados encontrados: %s", LOG_PREFIX, n)
        print(f"{LOG_PREFIX} LEIDSA parser OK — resultados encontrados: {n}")
    else:
        logger.warning(
            "%s LEIDSA scrape falló: %s",
            LOG_PREFIX,
            result.get("error") or result.get("message"),
        )
    return result


def refresh_leidsa_now():
    from services.leidsa_service import update_leidsa_now as _update

    return _update()
