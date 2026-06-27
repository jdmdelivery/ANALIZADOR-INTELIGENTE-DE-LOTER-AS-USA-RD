"""Logs estructurados del analizador de recomendaciones."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
LOG_TAG = "[ANALIZADOR]"


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
    lines = [
        LOG_TAG,
        f"loteria={loteria}",
        f"sorteo={sorteo}",
        f"ultimo_resultado_fecha={ultimo_resultado_fecha}",
        f"cantidad_resultados_usados={cantidad_resultados_usados}",
        f"ultimos_10_resultados={ultimos_10_resultados}",
        f"scores_posicion_1={scores_posicion_1}",
        f"scores_posicion_2={scores_posicion_2}",
        f"scores_posicion_3={scores_posicion_3}",
        f"recomendacion_final={recomendacion_final}",
        f"generado_en={generado_en}",
    ]
    text = "\n".join(lines)
    logger.info(text)
    print(text)
