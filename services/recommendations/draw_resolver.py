"""Resuelve tanda interna (tarde/tardía/noche) desde parámetros UI o API."""
from __future__ import annotations

from models import get_lottery


def resolve_prediction_draw(
    lottery_id: int,
    *,
    draw_name: str = "",
    sorteo: str = "",
    sorteo_time: str = "",
) -> tuple[str | None, dict | None, str | None]:
    """
    Devuelve (draw_name_resuelto, lottery, error).
    Acepta draw_name interno, etiqueta de horario (6:00 PM) o sorteo alias.
    """
    from analysis import _resolve_draw_name_for_lottery

    lottery = get_lottery(lottery_id)
    if not lottery:
        return None, None, "Lotería no encontrada."

    label = (draw_name or sorteo or sorteo_time or "").strip()
    if not label:
        return None, lottery, "sorteo o draw_name requerido."

    resolved = _resolve_draw_name_for_lottery(lottery, label)
    if not resolved:
        return None, lottery, f"No se pudo resolver sorteo: {label}"

    return resolved, lottery, None
