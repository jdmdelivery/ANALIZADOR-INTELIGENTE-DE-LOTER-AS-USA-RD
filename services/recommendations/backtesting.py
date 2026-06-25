"""Backtesting y persistencia de recomendaciones."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from models import format_numbers, get_connection, parse_numbers


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
            exact = len(set(predicted) & set(actual))
            pos_hits = sum(1 for i, n in enumerate(predicted) if i < len(actual) and n == actual[i])
            box_hits = exact
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
    evaluate_pending_backtests()
    conn = get_connection()
    try:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = conn.execute(
            """SELECT b.*, l.name as lottery_name, l.country
               FROM backtest_results b
               JOIN lotteries l ON l.id = b.lottery_id
               WHERE b.evaluated_at >= ?""",
            (since,),
        ).fetchall()
        if not rows:
            return {
                "ok": True,
                "message": "Sin datos de backtesting aún.",
                "days": days,
                "total": 0,
            }

        total = len(rows)
        avg_exact = sum(r["exact_hits"] for r in rows) / total
        avg_pos = sum(r["position_hits"] for r in rows) / total
        by_lottery: dict[str, list] = {}
        by_family: dict[str, list] = {}
        for r in rows:
            by_lottery.setdefault(r["lottery_name"], []).append(r["exact_hits"])
            by_family.setdefault(r["game_family"] or "?", []).append(r["exact_hits"])

        def _avg(d: dict) -> dict:
            return {k: round(sum(v) / len(v), 2) for k, v in d.items()}

        best_lot = max(by_lottery.items(), key=lambda x: sum(x[1]) / len(x[1]))[0] if by_lottery else None
        worst_lot = min(by_lottery.items(), key=lambda x: sum(x[1]) / len(x[1]))[0] if by_lottery else None
        best_family = max(by_family.items(), key=lambda x: sum(x[1]) / len(x[1]))[0] if by_family else None

        return {
            "ok": True,
            "days": days,
            "total": total,
            "avg_exact_hits": round(avg_exact, 2),
            "avg_position_hits": round(avg_pos, 2),
            "precision_by_lottery": _avg(by_lottery),
            "precision_by_family": _avg(by_family),
            "best_lottery": best_lot,
            "worst_lottery": worst_lot,
            "best_game_family": best_family,
        }
    finally:
        conn.close()
