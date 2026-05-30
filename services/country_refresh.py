"""
Actualización de resultados por país — USA y RD completamente aislados.
Nunca mezclar Illinois Hub con LEIDSA/Conectate.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

RD_COUNTRIES = frozenset({"RD", "DO", "REPUBLICA DOMINICANA", "DOM"})
USA_COUNTRIES = frozenset({"USA", "US", "EEUU"})


def normalize_country(country: str) -> str:
    c = (country or "").strip().upper()
    if c in ("DO", "REPUBLICA DOMINICANA", "DOM"):
        return "RD"
    if c in ("US", "EEUU"):
        return "USA"
    return c


def refresh_results(
    country: str,
    state: str | None = None,
    lottery: str | None = None,
    days: int = 30,
    *,
    refresh_all_rd: bool = False,
    refresh_all_usa: bool = False,
) -> dict:
    """Despacha solo al módulo del país indicado."""
    country_up = normalize_country(country)

    if country_up == "RD":
        from services.rd_refresh import refresh_rd_results

        return refresh_rd_results(
            lottery=lottery,
            days=days,
            refresh_all=bool(refresh_all_rd or not lottery),
        )

    if country_up == "USA":
        from services.usa_refresh import refresh_usa_results

        return refresh_usa_results(
            state=state,
            lottery=lottery,
            days=days,
            refresh_all=bool(refresh_all_usa),
        )

    return {
        "ok": False,
        "status": "error",
        "message": f"País no soportado: {country}",
    }
