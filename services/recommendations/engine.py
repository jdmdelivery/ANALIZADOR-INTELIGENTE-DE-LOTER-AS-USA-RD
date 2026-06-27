"""Orquestador del motor de recomendaciones — siempre recalcula desde BD."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from itertools import combinations

from models import get_lottery

from services.recommendations.analyzer_log import log_analyzer
from services.recommendations.data_loader import load_draw_history
from services.recommendations.registry import resolve_adapter, resolve_config
from services.recommendations.weight_tuner import get_weights_for_family

DATA_SOURCE_LABEL = "BASE DE DATOS"


def clear_recommendation_cache() -> None:
    """Compatibilidad — ya no hay caché en memoria."""
    return None


def _ensure_country_match(lottery: dict) -> None:
    country = (lottery.get("country") or "").upper()
    if country not in ("USA", "RD"):
        raise ValueError(f"País no soportado para recomendaciones: {country}")


def _format_last_draws(per_draw: list[list[str]], limit: int = 10) -> str:
    chunks = []
    for draw in per_draw[:limit]:
        chunks.append("-".join(draw))
    return " | ".join(chunks)


def _position_top_scores(result: dict) -> tuple[str, str, str]:
    scores = ["", "", ""]
    picks = result.get("position_picks") or []
    for i in range(min(3, len(picks))):
        top = picks[i].get("top_5") or []
        if top:
            scores[i] = str(top[0].get("number", ""))
    if not any(scores):
        for i, part in enumerate((result.get("digit_scores") or [])[:3]):
            scores[i] = str(part.get("number", ""))
    return scores[0], scores[1], scores[2]


def _build_diagnostic(ctx: dict, result: dict, generated_at: str) -> dict:
    rows = ctx.get("rows") or []
    latest_row = rows[0] if rows else {}
    per_draw = ctx.get("per_draw_main") or result.get("_per_draw") or []
    last_dt = ctx.get("latest_result_date") or latest_row.get("draw_date") or ""
    last_time = latest_row.get("draw_time") or ""
    if last_dt and last_time:
        last_label = f"{last_dt} {last_time}"
    else:
        last_label = last_dt or "—"
    return {
        "last_result_used": last_label,
        "last_result_date": last_dt,
        "last_result_time": last_time,
        "draws_analyzed": len(per_draw),
        "recalculated_at": generated_at,
        "source": DATA_SOURCE_LABEL,
        "data_source": DATA_SOURCE_LABEL,
        "from_cache": False,
        "last_10_draws": per_draw[:10],
    }


def _attach_analyzer_metadata(
    result: dict,
    *,
    lottery: dict,
    draw_name: str,
    ctx: dict,
    generated_at: str,
) -> dict:
    per_draw = ctx.get("per_draw_main") or result.get("_per_draw") or []
    rec_nums = result.get("generated_numbers") or result.get("recommended_numbers") or []
    s1, s2, s3 = _position_top_scores(result)
    diag = _build_diagnostic(ctx, result, generated_at)
    latest_row = (ctx.get("rows") or [{}])[0] if ctx.get("rows") else {}
    result["created_at"] = generated_at
    result["engine"] = "recommendations_v2"
    result["from_cache"] = False
    result["data_source"] = DATA_SOURCE_LABEL
    result["analyzer_diagnostic"] = diag
    result["latest_result_date"] = diag.get("last_result_date")
    result["history_count"] = diag.get("draws_analyzed", 0)
    result["draw_name"] = draw_name
    result["sorteo_usado"] = draw_name
    result["fecha_usada"] = diag.get("last_result_date")
    result["hora_usada"] = diag.get("last_result_time")
    result["resultado_usado"] = latest_row.get("numbers") or (
        "-".join(per_draw[0]) if per_draw else []
    )
    result["numeros_recomendados"] = list(rec_nums)
    result["cantidad_resultados_analizados"] = diag.get("draws_analyzed", 0)
    result["fuente"] = DATA_SOURCE_LABEL
    result["cache_usada"] = "NO"
    result["total_resultados_disponibles"] = ctx.get("total_resultados_disponibles", 0)
    result["total_resultados_usados"] = ctx.get("total_resultados_usados") or diag.get("draws_analyzed", 0)
    result["rango_usado"] = ctx.get("rango_usado", "todo")
    result["hash_datos_usados"] = ctx.get("hash_datos_usados", "")
    result["ultimo_resultado_usado"] = diag.get("last_result_used", "")
    if ctx.get("hash_datos_usados"):
        diag["hash_datos_usados"] = ctx["hash_datos_usados"]
        diag["rango_usado"] = ctx.get("rango_usado")
        diag["total_resultados_disponibles"] = ctx.get("total_resultados_disponibles")
        diag["total_resultados_usados"] = ctx.get("total_resultados_usados")

    log_analyzer(
        loteria=lottery.get("name", ""),
        sorteo=draw_name,
        ultimo_resultado_fecha=diag.get("last_result_used", ""),
        cantidad_resultados_usados=diag.get("draws_analyzed", 0),
        ultimos_10_resultados=_format_last_draws(per_draw, 10),
        scores_posicion_1=s1,
        scores_posicion_2=s2,
        scores_posicion_3=s3,
        recomendacion_final=",".join(str(n) for n in rec_nums),
        generado_en=generated_at,
    )
    return result


def generate_recommendation(
    lottery_id: int,
    draw_name: str,
    *,
    force_refresh: bool = True,
    days: int | None = None,
) -> dict:
    """Recalcula siempre desde la base de datos (force_refresh ignorado: siempre fresco)."""
    del force_refresh  # API compat — nunca se usa caché

    from services.recommendations.draw_resolver import resolve_prediction_draw

    resolved, lottery, err = resolve_prediction_draw(lottery_id, draw_name=draw_name)
    if err or not resolved:
        return {"ok": False, "message": err or "Sorteo no válido."}

    result, lottery, config, ctx = _run_adapter(lottery_id, resolved, days=days)
    if not lottery:
        return result if isinstance(result, dict) else {"ok": False, "message": "Lotería no encontrada."}
    if not result.get("ok"):
        return result

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = _attach_analyzer_metadata(
        result,
        lottery=lottery,
        draw_name=resolved,
        ctx=ctx or {},
        generated_at=generated_at,
    )
    return _legacy_compat(result, lottery, config or {})


def _compute_top_pairs(per_draw: list[list[str]], limit: int = 10) -> list[dict]:
    pairs: Counter = Counter()
    for draw in per_draw[:60]:
        if len(draw) < 2:
            continue
        for pair in combinations(sorted(set(draw)), 2):
            pairs[pair] += 1
    return [
        {"pair": list(p), "count": c}
        for p, c in pairs.most_common(limit)
    ]


def build_analysis_stats(lottery_id: int, draw_name: str, max_results=None) -> dict | None:
    """Compatibilidad con analizar_loteria_por_tanda."""
    result, lottery, config, ctx = _run_adapter(lottery_id, draw_name, max_results=max_results)
    if not result:
        return None
    if not result.get("ok"):
        return {
            "ok": False,
            "message": result.get("message", "Histórico insuficiente"),
            "total_results": result.get("history_count", 0),
        }

    per_draw = result.get("_per_draw") or (ctx or {}).get("per_draw_main") or []
    if not per_draw:
        ctx = load_draw_history(lottery_id, draw_name, limit=max_results)
        per_draw = ctx.get("per_draw_main") or []

    all_nums = [n for d in per_draw for n in d]
    last_draw = set(per_draw[0]) if per_draw else set()
    freq = Counter(all_nums)
    f30 = Counter(n for d in per_draw[:30] for n in d)
    f60 = Counter(n for d in per_draw[:60] for n in d)

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
        "top_pairs": _compute_top_pairs(per_draw),
        "recent_trend": {},
        "numbers_together": _compute_top_pairs(per_draw, 5),
        "frequency_30": dict(f30),
        "frequency_60": dict(f60),
        "last_30_count": min(30, len(per_draw)),
        "last_60_count": min(60, len(per_draw)),
        "last_90_count": min(90, len(per_draw)),
        "_per_draw": per_draw,
        "_all_nums": all_nums,
        "_freq": freq,
        "_config": config,
    }


def _run_adapter(lottery_id: int, draw_name: str, max_results=None, days=None):
    lottery = get_lottery(lottery_id)
    if not lottery:
        return {"ok": False, "message": "Lotería no encontrada."}, None, None, None

    _ensure_country_match(lottery)
    ctx = load_draw_history(lottery_id, draw_name, limit=max_results, days=days)
    if not ctx.get("ok"):
        return ctx, lottery, None, ctx

    config = resolve_config(lottery)
    adapter, family = resolve_adapter(lottery)
    ctx["weights"] = get_weights_for_family(family)
    result = adapter.recommend(ctx, config)
    if result.get("ok"):
        result["game_family"] = family
        result["_per_draw"] = ctx.get("per_draw_main")
    return result, lottery, config, ctx


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
