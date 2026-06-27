"""Logs estructurados para guardado y consulta de resultados."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
LOG_TAG = "[RESULTADOS]"


def log_resultados(
    *,
    fecha_consultada: str = "",
    cantidad_api: int | str = "",
    loteria: str = "",
    sorteo: str = "",
    hora: str = "",
    accion: str = "",
    total_fecha_bd: int | str = "",
    extra: str = "",
) -> None:
    parts = [
        LOG_TAG,
        f"fecha consultada={fecha_consultada}",
        f"cantidad recibida API={cantidad_api}",
    ]
    if loteria:
        parts.append(f"loteria={loteria}")
    if sorteo:
        parts.append(f"sorteo={sorteo}")
    if hora:
        parts.append(f"hora={hora}")
    if accion:
        parts.append(f"guardado/actualizado={accion}")
    if total_fecha_bd != "":
        parts.append(f"total en BD para fecha={total_fecha_bd}")
    if extra:
        parts.append(extra)
    text = " | ".join(parts)
    logger.info(text)
    print(text)
