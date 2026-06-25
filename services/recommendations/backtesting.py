"""Backtesting y persistencia de recomendaciones."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from collections import Counter

from models import format_numbers, get_connection, parse_numbers


def _box_hits(predicted: list[str], actual: list[str]) -> int:
    """Coincidencias tipo box (multiset) para Pick."""
    if not predicted or not actual:
        return 0
    pc = Counter(predicted)
    ac = Counter(actual)
    return sum((pc & ac).values())


def _bonus_hits(predicted_bonus: list[str], actual_bonus: list[str]) -> int:
    if not predicted_bonus or not actual_bonus:
        return 0
    return len(set(predicted_bonus) & set(actual_bonus))


def save_recommendation_run(lottery_id: int, draw_name: str, family: str, result: dict) -> int | None:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO recommendation_runs
               (lottery_id, draw_name, game_family, adapter, payload_json,
                primary_numbers, bonus_numbers, score, confidence, history_count,
                latest_result_date, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                lottery_id,
                draw_name,
                family,
                result.get("adapter"),
                json.dumps(result, ensure_ascii=False, default=str)[:50000],
                format_numbers(result.get("generated_numbers") or []),
                format_numbers(result.get("bonus_numbers") or []),
                float(result.get("score") or 0),
                result.get("confidence_level"),
                int(result.get("history_count") or result.get("total_results") or 0),
                result.get("latest_result_date"),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        return None
    finally:
        conn.close()


def evaluate_pending_backtests() -> int:
    """Compara recomendaciones con sorteos posteriores."""
    conn = get_connection()
    evaluated = 0
    try:
        rows = conn.execute(
            """SELECT r.* FROM recommendation_runs r
               WHERE r.id NOT IN (SELECT recommendation_run_id FROM backtest_results)
               ORDER BY r.created_at DESC LIMIT 200"""
        ).fetchall()
        for row in rows:
            predicted = parse_numbers(row["primary_numbers"])
            if not predicted:
                continue
            actual_row = conn.execute(
                """SELECT * FROM lottery_results
                   WHERE lottery_id = ? AND draw_name = ?
                   AND draw_date > date(?, '-1 day')
                   ORDER BY draw_date ASC LIMIT 1""",
                (row["lottery_id"], row["draw_name"], row["created_at"][:10]),
            ).fetchone()
            if not actual_row:
                continue
            actual = parse_numbers(actual_row["numbers"])
            bonus = parse_numbers(actual_row.get("bonus_number") or actual_row.get("fireball_number") or "")
            predicted_bonus = parse_numbers(row["bonus_numbers"] or "")
            exact = len(set(predicted) & set(actual))
            pos_hits = sum(1 for i, n in enumerate(predicted) if i < len(actual) and n == actual[i])
            box_hits = _box_hits(predicted, actual)
            bonus_hits = _bonus_hits(predicted_bonus, bonus)
            _ = bonus_hits  # reservado para columna futura
            conn.execute(
                """INSERT INTO backtest_results
                   (recommendation_run_id, lottery_id, draw_name, game_family,
                    predicted_numbers, actual_numbers, actual_bonus,
                    exact_hits, position_hits, box_hits, score, draw_date, evaluated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row["id"],
                    row["lottery_id"],
                    row["draw_name"],
                    row["game_family"],
                    row["primary_numbers"],
                    actual_row["numbers"],
                    json.dumps(bonus),
                    exact,
                    pos_hits,
                    box_hits,
                    row["score"],
                    actual_row["draw_date"],
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            evaluated += 1
        conn.commit()
    finally:
        conn.close()
    return evaluated


def run_backtest_summary(days: int = 30) -> dict:
    """Compatibilidad — delega al módulo de precisión."""
    from services.precision.dashboard import get_dashboard

    dash = get_dashboard(force_refresh=True)
    dash["days"] = days
    return dash
