"""Evaluación automática al publicarse un resultado oficial."""
from __future__ import annotations

from models import get_connection, parse_numbers, row_to_dict

from services.precision.comparator import compare_recommendation, parse_result_row
from services.precision.storage import is_run_evaluated, save_precision_evaluation
from services.precision.weight_learning import tune_weights_after_evaluation


def on_official_result_saved(
    lottery_id: int,
    draw_name: str,
    draw_date: str,
    result_id: int,
) -> int:
    """
    Hook llamado desde upsert_result cuando entra/actualiza un resultado.
    Evalúa recomendaciones pendientes cuyo próximo sorteo es este.
    """
    evaluated = 0
    conn = get_connection()
    try:
        result_row = conn.execute(
            "SELECT * FROM lottery_results WHERE id = ?",
            (result_id,),
        ).fetchone()
        if not result_row:
            return 0
        result = row_to_dict(result_row)
        actual_main, actual_bonus = parse_result_row(result)

        pending = conn.execute(
            """SELECT * FROM recommendation_runs
               WHERE lottery_id = ? AND draw_name = ?
               AND COALESCE(evaluation_status, 'pending') = 'pending'
               ORDER BY created_at ASC""",
            (lottery_id, draw_name),
        ).fetchall()

        for run in pending:
            run_id = run["id"]
            if is_run_evaluated(run_id):
                continue
            if not _is_next_draw_for_run(conn, run, draw_date, result_id):
                continue

            predicted = parse_numbers(run["primary_numbers"])
            predicted_bonus = parse_numbers(run["bonus_numbers"] or "")
            if not predicted:
                continue

            family = run["game_family"] or "quiniela_rd"
            comparison = compare_recommendation(
                predicted,
                actual_main,
                predicted_bonus=predicted_bonus,
                actual_bonus=actual_bonus,
                game_family=family,
            )

            save_precision_evaluation(
                run_id,
                lottery_id,
                draw_name,
                family,
                comparison,
                predicted_numbers=run["primary_numbers"],
                predicted_bonus=run["bonus_numbers"] or "",
                actual_numbers=result.get("numbers") or result.get("main_numbers") or "",
                actual_bonus=__import__("json").dumps(actual_bonus),
                result_id=result_id,
                draw_date=draw_date,
                predicted_score=float(run["score"] or 0),
            )
            evaluated += 1
    finally:
        conn.close()

    if evaluated:
        try:
            tune_weights_after_evaluation()
        except Exception:
            pass
    return evaluated


def _is_next_draw_for_run(conn, run, draw_date: str, result_id: int) -> bool:
    """El resultado debe ser el primer sorteo posterior a la recomendación."""
    created = (run["created_at"] or "")[:10]
    next_row = conn.execute(
        """SELECT id, draw_date FROM lottery_results
           WHERE lottery_id = ? AND draw_name = ?
           AND draw_date >= ?
           ORDER BY draw_date ASC, id ASC LIMIT 1""",
        (run["lottery_id"], run["draw_name"], created),
    ).fetchone()
    if not next_row:
        return False
    return int(next_row["id"]) == int(result_id) and next_row["draw_date"] == draw_date


def evaluate_all_pending(limit: int = 500) -> int:
    """Barrido de seguridad — no recalcula evaluados."""
    conn = get_connection()
    total = 0
    try:
        rows = conn.execute(
            """SELECT r.id, r.lottery_id, r.draw_name, r.created_at
               FROM recommendation_runs r
               WHERE COALESCE(r.evaluation_status, 'pending') = 'pending'
               AND r.id NOT IN (
                   SELECT recommendation_run_id FROM backtest_results
                   WHERE recommendation_run_id IS NOT NULL
               )
               ORDER BY r.created_at ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        for run in rows:
            created = (run["created_at"] or "")[:10]
            actual_row = conn.execute(
                """SELECT id, draw_date FROM lottery_results
                   WHERE lottery_id = ? AND draw_name = ?
                   AND draw_date >= ?
                   ORDER BY draw_date ASC, id ASC LIMIT 1""",
                (run["lottery_id"], run["draw_name"], created),
            ).fetchone()
            if not actual_row:
                continue
            n = on_official_result_saved(
                run["lottery_id"],
                run["draw_name"],
                actual_row["draw_date"],
                actual_row["id"],
            )
            total += n
    finally:
        conn.close()
    return total
