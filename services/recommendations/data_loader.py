"""Carga histórico por lotería/tanda — principales y bonus separados."""
from __future__ import annotations

from models import get_lottery, get_results_for_analysis, parse_numbers

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
        "latest_result_time": rows[0].get("draw_time") if rows else None,
    }
