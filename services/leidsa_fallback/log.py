"""Logs estructurados [LEIDSA FALLBACK]."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
LOG_TAG = "[LEIDSA FALLBACK]"


def log_leidsa_fallback(
    *,
    fuente: str = "",
    url: str = "",
    status: str | int = "",
    tiempo: str | float = "",
    juego: str = "",
    resultados_encontrados: int | str = "",
    nuevos: int | str = "",
    actualizados: int | str = "",
    error: str | None = None,
) -> None:
    lines = [
        LOG_TAG,
        f"fuente: {fuente}",
        f"url: {url}",
        f"status: {status}",
        f"tiempo: {tiempo}s" if tiempo != "" else "tiempo:",
        f"juego: {juego}",
        f"resultados_encontrados: {resultados_encontrados}",
        f"nuevos: {nuevos}",
        f"actualizados: {actualizados}",
        f"error: {error or ''}",
    ]
    text = "\n".join(lines)
    if error:
        logger.error(text)
    else:
        logger.info(text)
    print(text)
