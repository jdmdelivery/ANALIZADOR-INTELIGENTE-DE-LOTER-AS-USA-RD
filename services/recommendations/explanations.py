"""Explicaciones estructuradas — siempre indican POR QUÉ se recomienda un número."""
from __future__ import annotations

from services.recommendations.categories import category_label, frequency_in_window
from services.recommendations.context_factors import draw_slot_label


def build_rich_explanation(
    number: str,
    profile: dict,
    score: int,
    *,
    components: dict | None = None,
    draw_name: str = "",
    per_draw: list[list[str]] | None = None,
    position: int | None = None,
    weekday_meta: dict | None = None,
) -> str:
    """Plantilla legible: frecuencia, tendencia, atraso, contexto, score."""
    parts: list[str] = []
    per_draw = per_draw or []

    c100 = profile.get("count_100")
    if c100 is None and per_draw:
        c100 = frequency_in_window(per_draw, min(100, len(per_draw))).get(number, 0)
    w100 = min(100, len(per_draw))
    if c100 is not None:
        parts.append(f"salió {c100} veces en últimos {w100} sorteos")

    trend = profile.get("trend")
    cat = profile.get("category")
    if trend == "tendencia" or cat == "tendencia":
        parts.append("está en tendencia positiva")
    elif trend == "caida":
        parts.append("baja en frecuencia reciente")
    elif trend == "sobrecalentado" or cat == "sobrecalentado":
        parts.append("salió muy seguido — posible enfriamiento")

    since = profile.get("draws_since", 0)
    if since >= 2:
        parts.append(f"lleva {since} sorteos sin salir")
    elif since == 0:
        parts.append("salió en el último sorteo")

    if position is not None:
        pos_labels = {0: "1ª", 1: "2ª", 2: "3ª", 3: "4ª"}
        pos_lbl = pos_labels.get(position, f"pos. {position + 1}")
        best_pos = profile.get("best_position")
        if best_pos:
            parts.append(f"históricamente fuerte en posición {best_pos}")
        else:
            parts.append(f"evaluado para posición {pos_lbl}")

    if weekday_meta:
        best_wd = weekday_meta.get("best_weekday")
        target_wd = weekday_meta.get("target_weekday")
        if best_wd and target_wd and best_wd == target_wd:
            parts.append(f"históricamente aparece más los {best_wd}")
        elif best_wd:
            parts.append(f"pico histórico los {best_wd}")

    if draw_name:
        parts.append(f"analizado en {draw_slot_label(draw_name)}")

    if cat and cat not in ("neutral",):
        parts.append(f"categoría: {category_label(cat)}")

    parts.append(f"score {score}")

    if not parts:
        return f"El {number}: comportamiento equilibrado en el histórico (score {score})."

    body = "; ".join(parts)
    return f"El {number} aparece porque: {body}."
