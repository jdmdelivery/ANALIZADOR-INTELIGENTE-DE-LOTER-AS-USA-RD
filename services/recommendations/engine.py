"""Orquestador del motor de recomendaciones."""
from __future__ import annotations

import json
from datetime import datetime

from models import create_prediction, get_lottery

from services.recommendations.data_loader import load_draw_history
from services.recommendations.registry import resolve_adapter, resolve_config
from services.recommendations.weight_tuner import get_weights_for_family


def _ensure_country_match(lottery: dict) -> None:
    country = (lottery.get("country") or "").upper()
    if country not in ("USA", "RD"):
        raise ValueError(f"País no soportado para recomendaciones: {country}")


def generate_recommendation(lottery_id: int, draw_name: str) -> dict:
    result, lottery, config = _run_adapter(lottery_id, draw_name)
    if not result.get("ok"):
        return result

    result["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result["engine"] = "recommendations_v2"

    try:
        create_prediction(
            lottery_id,
            draw_name,
            result.get("generated_numbers") or [],
            result.get("analysis_text") or "",
            result.get("confidence_level") or "bajo",
            float(result.get("score") or 0),
        )
        from services.recommendations.backtesting import save_recommendation_run

        save_recommendation_run(lottery_id, draw_name, result.get("game_family", ""), result)
    except Exception:
        pass

    return _legacy_compat(result, lottery, config)


def build_analysis_stats(lottery_id: int, draw_name: str, max_results=None) -> dict | None:
    """Compatibilidad con analizar_loteria_por_tanda."""
    result, lottery, config = _run_adapter(lottery_id, draw_name, max_results=max_results)
    if not result:
        return None
    if not result.get("ok"):
        return {
            "ok": False,
            "message": result.get("message", "Histórico insuficiente"),
            "total_results": result.get("history_count", 0),
        }

    ctx = load_draw_history(lottery_id, draw_name, limit=max_results)
    per_draw = ctx.get("per_draw_main") or []
    from collections import Counter

    all_nums = [n for d in per_draw for n in d]
    last_draw = set(per_draw[0]) if per_draw else set()

    return {
        "ok": True,
        "lottery_id": lottery_id,
        "lottery_name": lottery.get("name"),
        "draw_name": draw_name,
        "total_results": len(per_draw),
        "hot_numbers": result.get("hot_numbers", []),
        "cold_numbers": result.get("cold_numbers", []),
        "overdue_numbers": result.get("overdue_numbers", []),
        "hot_numbers_detail": result.get("hot_numbers_detail", []),
        "cold_numbers_detail": result.get("cold_numbers_detail", []),
        "overdue_numbers_detail": result.get("overdue_numbers_detail", []),
        "number_profiles": result.get("number_profiles", {}),
        "analysis_window": result.get("analysis_window", 25),
        "last_draw_numbers": list(last_draw),
        "excluded_recent_numbers": list(last_draw),
        "recent_exclusion_draws": 5,
        "analysis_basis": result.get("analysis_basis", ""),
        "position_frequency": result.get("position_frequency", {}),
        "top_pairs": [],
        "recent_trend": {},
        "numbers_together": [],
        "frequency_30": {},
        "frequency_60": {},
        "last_30_count": min(30, len(per_draw)),
        "last_60_count": min(60, len(per_draw)),
        "last_90_count": min(90, len(per_draw)),
        "_per_draw": per_draw,
        "_all_nums": all_nums,
        "_freq": Counter(all_nums),
        "_config": config,
    }


def _run_adapter(lottery_id: int, draw_name: str, max_results=None):
    lottery = get_lottery(lottery_id)
    if not lottery:
        return {"ok": False, "message": "Lotería no encontrada."}, None, None

    _ensure_country_match(lottery)
    ctx = load_draw_history(lottery_id, draw_name, limit=max_results)
    if not ctx.get("ok"):
        return ctx, lottery, None

    config = resolve_config(lottery)
    adapter, family = resolve_adapter(lottery)
    ctx["weights"] = get_weights_for_family(family)
    result = adapter.recommend(ctx, config)
    if result.get("ok"):
        result["game_family"] = family
    return result, lottery, config


def analyze_lottery(lottery_id: int, draw_name: str) -> dict:
    return build_analysis_stats(lottery_id, draw_name) or {"ok": False}


def _legacy_compat(result: dict, lottery: dict, config: dict) -> dict:
    """Campos que espera app.js y analysis.py legacy."""
    from services.recommendations.constants import RECOMMENDATION_DISCLAIMER

    out = dict(result)
    out["disclaimer"] = RECOMMENDATION_DISCLAIMER
    out["lottery_name"] = lottery.get("name")
    out["variety_score"] = round(
        len(set(out.get("generated_numbers") or []))
        / max(len(out.get("generated_numbers") or []), 1),
        2,
    )
    if out.get("is_strong_recommendation") is False:
        out["warning"] = out.get("warning") or "Confianza baja — considere como referencia, no jugada fuerte."
    return out
