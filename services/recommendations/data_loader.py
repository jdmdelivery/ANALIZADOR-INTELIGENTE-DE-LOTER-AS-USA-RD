"""Carga histórico por lotería/tanda — principales y bonus separados."""
from __future__ import annotations

from models import get_lottery, get_results_for_analysis, parse_numbers
from services.recommendations.analyzer_log import log_analisis
from services.recommendations.constants import MIN_HISTORY

USA_MAX_RESULTS = 100


def _split_row_numbers(row: dict, lottery_type: str) -> tuple[list[str], list[str]]:
    main = parse_numbers(row.get("main_numbers") or row.get("numbers"))
    bonus: list[str] = []
    if row.get("bonus_numbers"):
        bonus = parse_numbers(row["bonus_numbers"])
    elif row.get("bonus_number"):
        bonus = parse_numbers(row["bonus_number"])
    elif row.get("fireball_number"):
        bonus = [str(row["fireball_number"])]
    return main, bonus


def _format_last_draws(rows: list[dict], per_draw: list[list[str]], limit: int = 10) -> str:
    parts = []
    for i, draw in enumerate(per_draw[:limit]):
        dd = rows[i].get("draw_date") if i < len(rows) else ""
        tt = rows[i].get("draw_time") if i < len(rows) else ""
        parts.append(f"{dd} {tt}: {'-'.join(draw)}")
    return " | ".join(parts)


def load_draw_history(
    lottery_id: int,
    draw_name: str,
    *,
    limit: int | None = None,
) -> dict:
    lottery = get_lottery(lottery_id)
    if not lottery:
        return {"ok": False, "message": "Lotería no encontrada."}

    if limit is None and lottery.get("country") == "USA":
        limit = USA_MAX_RESULTS

    rows = get_results_for_analysis(lottery_id, draw_name, limit=limit)
    per_draw_main: list[list[str]] = []
    per_draw_bonus: list[list[str]] = []
    dates: list[str] = []

    for row in rows:
        main, bonus = _split_row_numbers(row, lottery.get("type", ""))
        if main:
            per_draw_main.append(main)
            per_draw_bonus.append(bonus)
            dates.append(row.get("draw_date") or "")

    latest_row = rows[0] if rows else {}
    last_label = ""
    if latest_row:
        last_label = f"{latest_row.get('draw_date', '')} {latest_row.get('draw_time', '')}".strip()

    log_analisis(
        loteria=lottery.get("name", ""),
        sorteo=draw_name,
        ultimos_10=_format_last_draws(rows, per_draw_main, 10),
        ultimo_resultado=last_label or "—",
        numeros_calculados="",
        cache_usada="NO",
    )

    if len(per_draw_main) < MIN_HISTORY:
        return {
            "ok": False,
            "message": (
                f"No hay resultados suficientes para esta tanda ({draw_name}). "
                f"Se encontraron {len(per_draw_main)}; se requieren al menos {MIN_HISTORY}."
            ),
            "history_count": len(per_draw_main),
            "min_required": MIN_HISTORY,
            "lottery": lottery,
            "draw_name": draw_name,
            "rows": rows,
            "latest_result_date": dates[0] if dates else None,
            "latest_result_time": latest_row.get("draw_time") if latest_row else None,
        }

    return {
        "ok": True,
        "lottery": lottery,
        "draw_name": draw_name,
        "rows": rows,
        "per_draw_main": per_draw_main,
        "per_draw_bonus": per_draw_bonus,
        "dates": dates,
        "total_results": len(per_draw_main),
        "latest_result_date": dates[0] if dates else None,
        "latest_result_time": latest_row.get("draw_time") if latest_row else None,
        "latest_result_numbers": per_draw_main[0] if per_draw_main else [],
    }
