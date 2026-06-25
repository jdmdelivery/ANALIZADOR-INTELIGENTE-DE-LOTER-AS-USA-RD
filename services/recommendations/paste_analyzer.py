"""Analizar números pegados por el usuario."""
from __future__ import annotations

import re

from services.recommendations.categories import (
    assign_category,
    category_explanation,
    category_label,
    classify_number,
)
from services.recommendations.data_loader import load_draw_history
from services.recommendations.registry import game_family, resolve_adapter, resolve_config
from services.recommendations.scoring import score_number


def parse_pasted_numbers(text: str) -> list[str]:
    if not text or not str(text).strip():
        return []
    raw = re.sub(r"[\s,;|/\\]+", " ", str(text).strip())
    parts = [p for p in raw.split() if p]
    return parts


def validate_numbers_for_config(numbers: list[str], config: dict) -> tuple[list[str], list[str]]:
    pad = int(config.get("pad", 2))
    lo, hi = int(config["min"]), int(config["max"])
    valid: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()
    for raw in numbers:
        try:
            n = str(int(str(raw).lstrip("0") or "0")).zfill(pad)
        except (ValueError, TypeError):
            errors.append(f"Inválido: {raw}")
            continue
        v = int(n)
        if v < lo or v > hi:
            errors.append(f"Fuera de rango ({lo}-{hi}): {n}")
            continue
        if n in seen:
            errors.append(f"Duplicado: {n}")
            continue
        seen.add(n)
        valid.append(n)
    return valid, errors


def analyze_pasted_numbers(lottery_id: int, draw_name: str, pasted: str) -> dict:
    from models import get_lottery

    lottery = get_lottery(lottery_id)
    if not lottery:
        return {"ok": False, "message": "Lotería no encontrada."}

    ctx = load_draw_history(lottery_id, draw_name)
    if not ctx.get("ok"):
        return ctx

    config = resolve_config(lottery)
    parsed = parse_pasted_numbers(pasted)
    if not parsed:
        return {"ok": False, "message": "No se detectaron números en el texto pegado."}

    valid, errors = validate_numbers_for_config(parsed, config)
    if not valid:
        return {"ok": False, "message": "Ningún número válido.", "errors": errors}

    per_draw = ctx["per_draw_main"]
    pad = int(config.get("pad", 2))
    family = game_family(lottery)

    analysis = []
    avoid = []
    hot_list = []
    cold_list = []
    for n in valid:
        prof = classify_number(n, per_draw, pad=pad)
        cat = assign_category(prof)
        score, _ = score_number(n, per_draw)
        entry = {
            "number": n,
            "score": score,
            "category": cat,
            "category_label": category_label(cat),
            "reason": category_explanation(cat, prof),
            "best_position": prof.get("best_position"),
            "draws_since": prof.get("draws_since"),
        }
        analysis.append(entry)
        if cat in ("sobrecalentado", "frío") and score < 40:
            avoid.append(entry)
        if cat in ("caliente", "tendencia", "caliente_atrasado"):
            hot_list.append(entry)
        if cat == "frío":
            cold_list.append(entry)

    analysis.sort(key=lambda x: -x["score"])

    compare = {}
    if family == "kino":
        adapter, _ = resolve_adapter(lottery)
        if hasattr(adapter, "compare_user_list"):
            compare = adapter.compare_user_list(valid, ctx, config)

    from services.recommendations.constants import RECOMMENDATION_DISCLAIMER

    return {
        "ok": True,
        "lottery": lottery.get("name"),
        "country": lottery.get("country"),
        "draw_name": draw_name,
        "parsed_numbers": valid,
        "validation_errors": errors,
        "analysis": analysis,
        "hot_signals": hot_list,
        "cold_signals": cold_list,
        "avoid": avoid,
        "compare": compare,
        "copy_text": _format_copy(analysis, lottery.get("name")),
        "disclaimer": RECOMMENDATION_DISCLAIMER,
    }


def _format_copy(analysis: list[dict], lottery_name: str) -> str:
    lines = [f"Análisis pegado — {lottery_name}"]
    for a in analysis:
        lines.append(
            f"{a['number']}: score {a['score']} — {a['category_label']} — {a['reason']}"
        )
    return "\n".join(lines)
