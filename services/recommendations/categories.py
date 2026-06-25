"""Categorías: caliente, frío, atrasado, tendencia, sobrecalentado — sin contradicciones."""
from __future__ import annotations

from collections import Counter

TREND_RECENT = 10
TREND_PREVIOUS = 10
TOP_N = 10


def _normalize(n: str, pad: int = 2) -> str:
    try:
        return str(int(str(n).lstrip("0") or "0")).zfill(pad)
    except (ValueError, TypeError):
        return str(n).zfill(pad)


def build_position_draws(per_draw: list[list[str]]) -> list[list[str]]:
    """Por sorteo, números por posición (0=1ra, 1=2da, 2=3ra)."""
    return [list(draw) for draw in per_draw]


def frequency_in_window(per_draw: list[list[str]], window: int) -> Counter:
    c: Counter = Counter()
    for draw in per_draw[:window]:
        for n in draw:
            c[n] += 1
    return c


def position_frequency(per_draw: list[list[str]], window: int = 100) -> dict[int, Counter]:
    pos: dict[int, Counter] = {}
    for draw in per_draw[:window]:
        for i, n in enumerate(draw):
            pos.setdefault(i, Counter())[n] += 1
    return pos


def draws_since_number(per_draw: list[list[str]], number: str) -> int:
    for idx, draw in enumerate(per_draw):
        if number in draw:
            return idx
    return len(per_draw)


def detect_trend(number: str, per_draw: list[list[str]]) -> str | None:
    if len(per_draw) < 6:
        return None
    recent = per_draw[:TREND_RECENT]
    older = per_draw[TREND_RECENT:TREND_RECENT + TREND_PREVIOUS]
    cr = sum(1 for d in recent if number in d)
    co = sum(1 for d in older if number in d) if older else 0
    last5 = sum(1 for d in per_draw[:5] if number in d)
    if last5 >= 3 or cr >= 5:
        return "sobrecalentado"
    if cr > co + 1:
        return "tendencia"
    if co > cr + 1:
        return "caida"
    return None


def classify_number(
    number: str,
    per_draw: list[list[str]],
    *,
    pad: int = 2,
    window: int = 25,
    universe: list[str] | None = None,
) -> dict:
    num = _normalize(number, pad)
    window = min(window, len(per_draw)) or 1
    freq_w = frequency_in_window(per_draw, window)
    count = freq_w.get(num, 0)
    draws_with = sum(1 for d in per_draw[:window] if num in d)
    pct = round((draws_with / window) * 100, 1)
    since = draws_since_number(per_draw, num)
    trend = detect_trend(num, per_draw)

    pos_freq = position_frequency(per_draw, 100)
    best_pos = None
    best_pos_count = 0
    for pos, ctr in pos_freq.items():
        c = ctr.get(num, 0)
        if c > best_pos_count:
            best_pos_count = c
            best_pos = pos

    pos_labels = {0: "1ra", 1: "2da", 2: "3ra", 3: "4ra"}
    pos_label = pos_labels.get(best_pos) if best_pos is not None else None

    return {
        "number": num,
        "count": count,
        "draws_with": draws_with,
        "percentage": pct,
        "draws_since": since,
        "trend": trend,
        "best_position": pos_label,
        "best_position_count": best_pos_count,
        "window": window,
    }


def assign_category(profile: dict, *, hot_threshold_pct: float = 12.0, cold_max_count: int = 1) -> str:
    """
    Un número tiene UNA categoría principal (caliente XOR frío).
    Puede coexistir atrasado + caliente con explicación compuesta.
    """
    if profile.get("trend") == "sobrecalentado":
        return "sobrecalentado"
    if profile.get("trend") == "tendencia":
        return "tendencia"

    count = profile.get("count", 0)
    pct = profile.get("percentage", 0)
    since = profile.get("draws_since", 0)

    is_hot = count >= 2 and pct >= hot_threshold_pct and since >= 1
    is_cold = count <= cold_max_count and since >= 3
    is_overdue = since >= 8

    if is_hot and is_overdue:
        return "caliente_atrasado"
    if is_hot:
        return "caliente"
    if is_cold:
        return "frío"
    if is_overdue:
        return "atrasado"
    if profile.get("trend") == "caida":
        return "frío"
    return "neutral"


def category_label(cat: str) -> str:
    return {
        "caliente": "Caliente",
        "frío": "Frío",
        "atrasado": "Atrasado",
        "tendencia": "Tendencia",
        "sobrecalentado": "Sobrecalentado",
        "caliente_atrasado": "Caliente y atrasado",
        "neutral": "Neutral",
    }.get(cat, cat)


def category_explanation(cat: str, profile: dict) -> str:
    n = profile.get("number", "")
    w = profile.get("window", 25)
    if cat == "caliente_atrasado":
        return (
            f"{n}: fue frecuente en los últimos sorteos ({profile.get('count', 0)} en {w}), "
            f"pero lleva {profile.get('draws_since', 0)} sorteos sin salir."
        )
    if cat == "caliente":
        return f"{n}: alta frecuencia reciente ({profile.get('percentage', 0)}% en {w} sorteos)."
    if cat == "frío":
        return f"{n}: baja frecuencia reciente ({profile.get('count', 0)} apariciones en {w})."
    if cat == "atrasado":
        return f"{n}: lleva {profile.get('draws_since', 0)} sorteos sin salir."
    if cat == "tendencia":
        return f"{n}: sube en frecuencia en los últimos 10 sorteos."
    if cat == "sobrecalentado":
        return f"{n}: salió demasiado seguido — posible riesgo."
    return f"{n}: comportamiento equilibrado en el histórico."


def build_hot_cold_lists(
    profiles: dict[str, dict],
    categories: dict[str, str],
    top_n: int = TOP_N,
) -> tuple[list[dict], list[dict]]:
    hot = []
    cold = []
    for num, prof in profiles.items():
        cat = categories[num]
        enriched = {**prof, "category": cat, "category_label": category_label(cat)}
        if cat in ("caliente", "caliente_atrasado", "sobrecalentado", "tendencia"):
            hot.append(enriched)
        elif cat == "frío":
            cold.append(enriched)
    hot.sort(key=lambda p: (-p.get("count", 0), -p.get("percentage", 0)))
    cold.sort(key=lambda p: (p.get("count", 0), p.get("draws_since", 0)))
    return hot[:top_n], cold[:top_n]


def assert_not_hot_and_cold(categories: dict[str, str]) -> None:
    for num, cat in categories.items():
        if cat == "caliente" and any(
            categories.get(other) == "frío" for other in categories if other == num
        ):
            raise ValueError(f"{num} no puede ser caliente y frío")
