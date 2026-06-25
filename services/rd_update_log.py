"""Logs estructurados [RD UPDATE] — solo República Dominicana."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

LOG_TAG = "[RD UPDATE]"


def log_rd_update(
    *,
    fuente: str = "",
    url: str = "",
    status: str | int | None = "",
    tiempo: str | float | None = "",
    loteria: str = "",
    fecha: str = "",
    resultados: int | str = "",
    guardados: int | str = "",
    actualizados: int | str = "",
    error: str | None = None,
) -> None:
    lines = [
        LOG_TAG,
        f"Fuente: {fuente}",
        f"URL: {url}",
        f"Status: {status}",
        f"Tiempo: {tiempo}s" if tiempo != "" else "Tiempo:",
        f"Lotería: {loteria}",
        f"Fecha: {fecha}",
        f"Resultados encontrados: {resultados}",
        f"Guardados: {guardados}",
        f"Actualizados: {actualizados}",
        f"Error: {error or ''}",
    ]
    if error:
        logger.error("\n".join(lines))
    else:
        logger.info("\n".join(lines))
