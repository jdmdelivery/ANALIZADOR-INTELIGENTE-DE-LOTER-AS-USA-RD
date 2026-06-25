"""Perfiles de números con score y explicación rica."""
from __future__ import annotations

from services.recommendations.categories import (
    assign_category,
    category_label,
    classify_number,
    frequency_in_window,
    position_frequency,
)
from services.recommendations.explanations import build_rich_explanation
from services.recommendations.scoring import format_score_breakdown, score_number


def build_scored_profiles(
    universe: list[str],
    per_draw: list[list[str]],
    *,
    pad: int = 2,
    window: int = 25,
    weights: dict | None = None,
    dates: list[str] | None = None,
    draw_name: str = "",
    position_freq: dict | None = None,
) -> tuple[dict[str, dict], dict[str, str]]:
    if position_freq is None:
        position_freq = position_frequency(per_draw, 100)

    profiles: dict[str, dict] = {}
    categories: dict[str, str] = {}
    f100 = frequency_in_window(per_draw, min(100, len(per_draw)))

    for num in universe:
        prof = classify_number(num, per_draw, pad=pad, window=window)
        prof["count_100"] = f100.get(num, 0)
        cat = assign_category(prof)
        categories[num] = cat
        s, sexp = score_number(
            num,
            per_draw,
            weights=weights,
            position_freq=position_freq,
            dates=dates,
            draw_name=draw_name,
        )
        prof_with_meta = {
            **prof,
            "category": cat,
            "category_label": category_label(cat),
            "score": s,
            "reason": build_rich_explanation(
                num,
                {**prof, "category": cat},
                s,
                components=sexp.get("components"),
                draw_name=draw_name,
                per_draw=per_draw,
                weekday_meta=sexp.get("weekday_meta"),
            ),
            "score_breakdown": format_score_breakdown(sexp),
            "summary": build_rich_explanation(
                num,
                {**prof, "category": cat},
                s,
                draw_name=draw_name,
                per_draw=per_draw,
                weekday_meta=sexp.get("weekday_meta"),
            ),
        }
        profiles[num] = prof_with_meta

    return profiles, categories
