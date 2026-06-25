"""Factores contextuales: día de la semana y tanda/horario."""
from __future__ import annotations

from collections import Counter
from datetime import datetime

_WEEKDAY_ES = (
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
)


def weekday_name(weekday: int) -> str:
    return _WEEKDAY_ES[weekday % 7]


def parse_draw_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    s = str(date_str).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def weekday_counts_for_number(
    number: str,
    per_draw: list[list[str]],
    dates: list[str],
) -> Counter:
    """Cuántas veces salió el número en cada día de la semana (0=lunes)."""
    counts: Counter = Counter()
    limit = min(len(per_draw), len(dates))
    for i in range(limit):
        if number not in per_draw[i]:
            continue
        dt = parse_draw_date(dates[i])
        if dt:
            counts[dt.weekday()] += 1
    return counts


def score_weekday_factor(
    number: str,
    per_draw: list[list[str]],
    dates: list[str] | None,
) -> tuple[float, dict]:
    """Score 0–100 según afinidad con el próximo día de sorteo (hoy)."""
    meta: dict = {"weekday_counts": {}, "best_weekday": None, "target_weekday": None}
    if not per_draw or not dates:
        return 50.0, meta

    counts = weekday_counts_for_number(number, per_draw, dates)
    if not counts:
        return 40.0, meta

    target = datetime.now().weekday()
    meta["target_weekday"] = weekday_name(target)
    meta["weekday_counts"] = {weekday_name(k): v for k, v in counts.items()}
    best_day, best_count = max(counts.items(), key=lambda x: x[1])
    meta["best_weekday"] = weekday_name(best_day)

    target_count = counts.get(target, 0)
    max_count = max(counts.values()) or 1
    score = (target_count / max_count) * 100 if max_count else 50.0
    if best_day == target and target_count >= 2:
        score = min(100, score + 10)
    return score, meta


def draw_slot_label(draw_name: str) -> str:
    if not draw_name:
        return "esta tanda"
    low = draw_name.lower()
    if low in ("noche", "evening", "night"):
        return "horario noche"
    if low in ("mañana", "manana", "midday", "day", "mediodía", "mediodia"):
        return "horario día"
    if low in ("tarde", "afternoon"):
        return "horario tarde"
    return f"tanda «{draw_name}»"


def score_draw_slot_factor(draw_name: str) -> tuple[float, dict]:
    """Histórico ya filtrado por tanda — factor neutro con metadatos para explicación."""
    label = draw_slot_label(draw_name)
    return 75.0, {"draw_slot_label": label, "draw_name": draw_name}
