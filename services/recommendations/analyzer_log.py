"""Logs estructurados del analizador de recomendaciones."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
LOG_TAG = "[ANALIZADOR]"
ANALISIS_TAG = "[ANALISIS]"


def log_analisis(
    *,
    loteria: str = "",
    sorteo: str = "",
    ultimos_10: str = "",
    ultimo_resultado: str = "",
    numeros_calculados: str = "",
    cache_usada: str = "NO",
) -> None:
    lines = [
        f"{ANALISIS_TAG} loteria seleccionada: {loteria}",
        f"{ANALISIS_TAG} sorteo seleccionado: {sorteo}",
        f"{ANALISIS_TAG} últimos 10 resultados usados: {ultimos_10 or '—'}",
        f"{ANALISIS_TAG} último resultado usado: {ultimo_resultado or '—'}",
        f"{ANALISIS_TAG} números calculados: {numeros_calculados or '—'}",
        f"{ANALISIS_TAG} cache usada: {cache_usada}",
    ]
    text = "\n".join(lines)
    logger.info(text)
    print(text)


def log_analyzer(
    *,
    loteria: str = "",
    sorteo: str = "",
    ultimo_resultado_fecha: str = "",
    cantidad_resultados_usados: int | str = "",
    ultimos_10_resultados: str = "",
    scores_posicion_1: str = "",
    scores_posicion_2: str = "",
    scores_posicion_3: str = "",
    recomendacion_final: str = "",
    generado_en: str = "",
) -> None:
    log_analisis(
        loteria=loteria,
        sorteo=sorteo,
        ultimos_10=ultimos_10_resultados,
        ultimo_resultado=ultimo_resultado_fecha,
        numeros_calculados=recomendacion_final,
        cache_usada="NO",
    )
    lines = [
        LOG_TAG,
        f"loteria={loteria}",
        f"sorteo={sorteo}",
        f"cantidad_resultados_usados={cantidad_resultados_usados}",
        f"scores_posicion_1={scores_posicion_1}",
        f"scores_posicion_2={scores_posicion_2}",
        f"scores_posicion_3={scores_posicion_3}",
        f"generado_en={generado_en}",
    ]
    text = "\n".join(lines)
    logger.info(text)
