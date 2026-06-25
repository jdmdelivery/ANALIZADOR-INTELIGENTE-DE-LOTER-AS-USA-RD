"""Persistencia enriquecida de recomendaciones y evaluaciones."""
from __future__ import annotations

import json
from datetime import datetime

from models import format_numbers, get_connection, get_lottery, parse_numbers

from services.precision.cache import invalidate as invalidate_precision_cache
from services.precision.constants import ALGORITHM_VERSION


def save_precision_recommendation(
    lottery_id: int,
    draw_name: str,
    family: str,
    result: dict,
) -> int | None:
    """Guarda snapshot completo al generar recomendación."""
    lottery = get_lottery(lottery_id)
    if not lottery:
        return None

    factors = {}
    for num, prof in (result.get("number_profiles") or {}).items():
        if isinstance(prof, dict) and prof.get("score") is not None:
            factors[num] = {
                "score": prof.get("score"),
                "category": prof.get("category"),
            }
            break
    weights = None
    digit_scores = result.get("digit_scores") or []
    if digit_scores:
        factors["digit_scores"] = digit_scores[:10]
    payload = result.get("_weights") or result.get("weights")
    if not payload and result.get("engine"):
        pass
    try:
        from services.recommendations.weight_tuner import get_weights_for_family
        weights = get_weights_for_family(family)
    except Exception:
        weights = {}

    now = datetime.now()
    created_at = now.strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO recommendation_runs
               (lottery_id, draw_name, game_family, adapter, payload_json,
                primary_numbers, bonus_numbers, score, confidence, history_count,
                latest_result_date, created_at,
                country, lottery_name, game_type, algorithm_version,
                factors_json, confidence_label, evaluation_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                lottery_id,
                draw_name,
                family,
                result.get("adapter"),
                json.dumps(result, ensure_ascii=False, default=str)[:80000],
                format_numbers(result.get("generated_numbers") or []),
                format_numbers(result.get("bonus_numbers") or []),
                float(result.get("score") or 0),
                result.get("confidence_level"),
                int(result.get("history_count") or result.get("total_results") or 0),
                result.get("latest_result_date"),
                created_at,
                lottery.get("country"),
                lottery.get("name"),
                result.get("game_type") or lottery.get("type"),
                result.get("engine") or ALGORITHM_VERSION,
                json.dumps({"weights": weights, "factors": factors}, ensure_ascii=False),
                result.get("confidence_label") or result.get("confidence_level"),
                "pending",
            ),
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        return None
    finally:
        conn.close()


def save_precision_evaluation(
    run_id: int,
    lottery_id: int,
    draw_name: str,
    family: str,
    comparison: dict,
    *,
    predicted_numbers: str,
    predicted_bonus: str,
    actual_numbers: str,
    actual_bonus: str,
    result_id: int,
    draw_date: str,
    predicted_score: float,
) -> int | None:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO backtest_results
               (recommendation_run_id, lottery_id, draw_name, game_family,
                predicted_numbers, actual_numbers, actual_bonus,
                exact_hits, position_hits, box_hits, score, draw_date, evaluated_at,
                predicted_bonus, bonus_hits, partial_hits, hit_percentage,
                achieved_score, status_label, detail_json, result_id, compare_summary)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                lottery_id,
                draw_name,
                family,
                predicted_numbers,
                actual_numbers,
                actual_bonus,
                comparison["exact_hits"],
                comparison["position_hits"],
                comparison["box_hits"],
                predicted_score,
                draw_date,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                predicted_bonus,
                comparison["bonus_hits"],
                comparison["partial_hits"],
                comparison["hit_percentage"],
                comparison["achieved_score"],
                comparison["status"],
                json.dumps(comparison.get("detail") or {}, ensure_ascii=False),
                result_id,
                comparison.get("compare_summary", ""),
            ),
        )
        conn.execute(
            "UPDATE recommendation_runs SET evaluation_status = 'evaluated' WHERE id = ?",
            (run_id,),
        )
        conn.commit()
        invalidate_precision_cache()
        return cur.lastrowid
    except Exception:
        return None
    finally:
        conn.close()


def is_run_evaluated(run_id: int) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM backtest_results WHERE recommendation_run_id = ? LIMIT 1",
            (run_id,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()
