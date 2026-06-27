"""Score 0–100 y confianza — pesos configurables por tipo de juego."""
from __future__ import annotations

from collections import Counter

from services.recommendations.constants import (
    ANALYSIS_WINDOWS,
    CONFIDENCE_HIGH_MIN,
    CONFIDENCE_MED_MIN,
    DEFAULT_WEIGHTS,
    STRONG_RECOMMENDATION_MIN,
    WEIGHT_MAX,
    WEIGHT_MIN,
)
from services.recommendations.categories import frequency_in_window
from services.recommendations.context_factors import (
    score_draw_slot_factor,
    score_weekday_factor,
)


def clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def confidence_from_score(score: int) -> tuple[str, str]:
    if score >= CONFIDENCE_HIGH_MIN:
        return "alto", "Alta"
    if score >= CONFIDENCE_MED_MIN:
        return "medio", "Media"
    return "bajo", "Baja"


def is_strong_recommendation(score: int) -> bool:
    return score >= STRONG_RECOMMENDATION_MIN


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    keys = list(DEFAULT_WEIGHTS.keys())
    out = {k: float(weights.get(k, DEFAULT_WEIGHTS[k])) for k in keys}
    for k in out:
        out[k] = max(WEIGHT_MIN, min(WEIGHT_MAX, out[k]))
    total = sum(out.values()) or 1.0
    return {k: v / total for k, v in out.items()}


def _norm_freq(count: int, maximum: int) -> float:
    return (count / maximum) * 100 if maximum else 0.0


def score_number(
    number: str,
    per_draw: list[list[str]],
    *,
    weights: dict[str, float] | None = None,
    position: int | None = None,
    position_freq: dict[int, Counter] | None = None,
    dates: list[str] | None = None,
    draw_name: str = "",
) -> tuple[int, dict]:
    w = normalize_weights(weights or DEFAULT_WEIGHTS)
    explanation: dict = {"weights": w, "components": {}, "weekday_meta": {}, "draw_slot_meta": {}}

    if not per_draw:
        return 0, explanation

    window_freqs: dict[str, Counter] = {}
    for win in ANALYSIS_WINDOWS:
        window_freqs[f"freq_{win}"] = frequency_in_window(per_draw, min(win, len(per_draw)))
    f10 = frequency_in_window(per_draw, min(10, len(per_draw)))

    comps: dict[str, float] = {}
    for win in ANALYSIS_WINDOWS:
        key = f"freq_{win}"
        freq = window_freqs[key]
        c = freq.get(number, 0)
        mx = max(freq.values()) if freq else 1
        comps[key] = _norm_freq(c, mx)

    c10 = f10.get(number, 0)
    max10 = max(f10.values()) if f10 else 1
    comp_trend = _norm_freq(c10, max10)

    since = next((i for i, d in enumerate(per_draw) if number in d), len(per_draw))
    comp_delay = min(100, since * 8) if since >= 2 else since * 20

    older = per_draw[10:20] if len(per_draw) > 10 else []
    co = sum(1 for d in older if number in d)
    cr = sum(1 for d in per_draw[:10] if number in d)
    stability = 50 + (10 if abs(cr - co) <= 1 else -15)
    comp_stability = max(0, min(100, stability))

    ctx = 50
    if position is not None and position_freq and position in position_freq:
        pf = position_freq[position]
        mx = max(pf.values()) if pf else 1
        ctx = _norm_freq(pf.get(number, 0), mx) if mx else 50
    comp_context = ctx

    comp_weekday, weekday_meta = score_weekday_factor(number, per_draw, dates)
    comp_slot, slot_meta = score_draw_slot_factor(draw_name)
    explanation["weekday_meta"] = weekday_meta
    explanation["draw_slot_meta"] = slot_meta

    raw = (
        comps.get("freq_7", 0) * w["freq_7"]
        + comps.get("freq_15", 0) * w["freq_15"]
        + comps.get("freq_25", 0) * w["freq_25"]
        + comps.get("freq_50", 0) * w["freq_50"]
        + comps.get("freq_90", 0) * w["freq_90"]
        + comp_trend * w["trend_10"]
        + comp_delay * w["delay"]
        + comp_stability * w["stability"]
        + comp_context * w["context"]
        + comp_weekday * w["weekday"]
        + comp_slot * w["draw_slot"]
    )
    explanation["components"] = {
        **{k: round(v, 1) for k, v in comps.items()},
        "trend_10": round(comp_trend, 1),
        "delay": round(comp_delay, 1),
        "stability": round(comp_stability, 1),
        "context": round(comp_context, 1),
        "weekday": round(comp_weekday, 1),
        "draw_slot": round(comp_slot, 1),
    }
    explanation["draws_since"] = since
    return clamp_score(raw), explanation


def score_combination(
    numbers: list[str],
    per_draw: list[list[str]],
    *,
    weights: dict[str, float] | None = None,
    position_freq: dict[int, Counter] | None = None,
    dates: list[str] | None = None,
    draw_name: str = "",
) -> tuple[int, list[dict]]:
    parts = []
    total = 0
    for i, n in enumerate(numbers):
        s, exp = score_number(
            n,
            per_draw,
            weights=weights,
            position=i,
            position_freq=position_freq,
            dates=dates,
            draw_name=draw_name,
        )
        parts.append({"number": n, "score": s, "explanation": exp})
        total += s
    avg = total / max(len(numbers), 1)
    pair_bonus = 0
    for draw in per_draw[:30]:
        if all(n in draw for n in numbers):
            pair_bonus += 3
    final = clamp_score(avg + min(pair_bonus, 12))
    return final, parts


def format_score_breakdown(explanation: dict) -> str:
    comps = explanation.get("components") or {}
    w = explanation.get("weights") or {}
    bits = []
    for key, label in (
        ("freq_7", "freq. 7"),
        ("freq_15", "freq. 15"),
        ("freq_25", "freq. 25"),
        ("freq_50", "freq. 50"),
        ("freq_90", "freq. 90"),
        ("trend_10", "tendencia 10"),
        ("delay", "atraso"),
        ("stability", "estabilidad"),
        ("context", "posición"),
        ("weekday", "día semana"),
        ("draw_slot", "tanda"),
    ):
        if key in comps:
            bits.append(f"{label} {comps[key]}% (peso {round(w.get(key, 0)*100)}%)")
    return "; ".join(bits)
