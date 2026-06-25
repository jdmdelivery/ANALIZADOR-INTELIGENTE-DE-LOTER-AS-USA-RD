"""Dashboard y estadísticas de precisión — lectura con caché."""
from __future__ import annotations

import json
from datetime import datetime

from models import get_connection, parse_numbers, row_to_dict

from services.precision.analytics import (
    build_snapshot,
    get_lottery_intelligence,
    status_display,
    status_from_pct,
)
from services.precision.cache import get_cached, invalidate, set_cached
from services.precision.constants import HISTORY_LIMITS, STATUS_ICONS, STATUS_LABELS
from services.precision.evaluator import evaluate_all_pending


def get_dashboard(*, force_refresh: bool = False) -> dict:
    if not force_refresh:
        cached = get_cached()
        if cached:
            return cached

    evaluate_all_pending(limit=80)
    conn = get_connection()
    try:
        snapshot = build_snapshot(conn)
        rankings = _legacy_rankings(conn)
        snapshot["rankings"] = rankings
        best = _pick_best_worst(snapshot)
        snapshot["kpis"].update(best)
        snapshot["total"] = snapshot["kpis"].get("total_evaluated", 0)
        snapshot["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return set_cached(snapshot)
    finally:
        conn.close()


def _pick_best_worst(snapshot: dict) -> dict:
    lot_table = snapshot.get("lottery_table") or []
    with_data = [x for x in lot_table if x.get("recommendations", 0) > 0]
    best_lot = max(with_data, key=lambda x: x.get("precision_pct") or 0)["lottery_name"] if with_data else None
    worst_lot = min(with_data, key=lambda x: x.get("precision_pct") or 0)["lottery_name"] if with_data else None
    alg = snapshot.get("algorithm_ranking") or []
    return {
        "best_lottery": best_lot,
        "worst_lottery": worst_lot,
        "best_algorithm": alg[0]["label"] if alg else None,
        "worst_algorithm": alg[-1]["label"] if len(alg) > 1 else None,
    }


def get_history(limit: int = 100, offset: int = 0) -> dict:
    limit = min(max(int(limit), 1), 5000)
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT b.*, l.name as lottery_name, l.country, l.type as lottery_type,
                      r.algorithm_version, r.confidence_label, r.confidence,
                      r.created_at as rec_created_at, r.game_type
               FROM backtest_results b
               JOIN lotteries l ON l.id = b.lottery_id
               LEFT JOIN recommendation_runs r ON r.id = b.recommendation_run_id
               ORDER BY b.evaluated_at DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        items = []
        for row in rows:
            d = row_to_dict(row)
            status = d.get("status_label") or status_from_pct(d.get("hit_percentage"))
            d["status_icon"] = STATUS_ICONS.get(status, "")
            d["status_text"] = STATUS_LABELS.get(status, status)
            d["predicted_list"] = parse_numbers(d.get("predicted_numbers"))
            d["actual_list"] = parse_numbers(d.get("actual_numbers"))
            d["eval_date"] = (d.get("evaluated_at") or "")[:10]
            d["eval_time"] = (d.get("evaluated_at") or "")[11:19]
            d["confidence"] = d.get("confidence_label") or d.get("confidence") or "—"
            items.append(d)
        total = conn.execute("SELECT COUNT(*) as c FROM backtest_results").fetchone()["c"]
        return {"ok": True, "items": items, "total": total, "limit": limit, "offset": offset}
    finally:
        conn.close()


def get_compare_detail(evaluation_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT b.*, l.name as lottery_name, l.country, l.type as lottery_type,
                      r.payload_json, r.algorithm_version, r.factors_json, r.confidence_label
               FROM backtest_results b
               JOIN lotteries l ON l.id = b.lottery_id
               LEFT JOIN recommendation_runs r ON r.id = b.recommendation_run_id
               WHERE b.id = ?""",
            (evaluation_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "message": "Evaluación no encontrada"}
        d = row_to_dict(row)
        detail = {}
        try:
            detail = json.loads(d.get("detail_json") or "{}")
        except Exception:
            pass
        status = d.get("status_label") or status_from_pct(d.get("hit_percentage"))
        predicted = parse_numbers(d.get("predicted_numbers"))
        actual = parse_numbers(d.get("actual_numbers"))
        return {
            "ok": True,
            "evaluation": d,
            "predicted": predicted,
            "actual": actual,
            "predicted_bonus": parse_numbers(d.get("predicted_bonus") or ""),
            "detail": detail,
            "compare_summary": d.get("compare_summary") or "",
            "status_icon": STATUS_ICONS.get(status, ""),
            "status_text": STATUS_LABELS.get(status, status),
            "hit_percentage": d.get("hit_percentage"),
            "position_results": detail.get("position_results", []),
        }
    finally:
        conn.close()


def _legacy_rankings(conn) -> dict:
    best = conn.execute(
        """SELECT b.*, l.name as lottery_name FROM backtest_results b
           JOIN lotteries l ON l.id = b.lottery_id
           WHERE b.hit_percentage IS NOT NULL
           ORDER BY b.hit_percentage DESC LIMIT 20"""
    ).fetchall()
    worst = conn.execute(
        """SELECT b.*, l.name as lottery_name FROM backtest_results b
           JOIN lotteries l ON l.id = b.lottery_id
           WHERE b.hit_percentage IS NOT NULL
           ORDER BY b.hit_percentage ASC LIMIT 20"""
    ).fetchall()
    top_score = conn.execute(
        """SELECT b.*, l.name as lottery_name FROM backtest_results b
           JOIN lotteries l ON l.id = b.lottery_id
           ORDER BY b.score DESC LIMIT 20"""
    ).fetchall()

    def brief(row):
        d = row_to_dict(row)
        st = d.get("status_label") or status_from_pct(d.get("hit_percentage"))
        return {
            "id": d["id"],
            "lottery_name": d.get("lottery_name"),
            "draw_date": d.get("draw_date"),
            "hit_percentage": d.get("hit_percentage"),
            "score": d.get("score"),
            "status_icon": STATUS_ICONS.get(st, ""),
        }

    return {
        "best_hits": [brief(r) for r in best],
        "worst_hits": [brief(r) for r in worst],
        "top_predicted_score": [brief(r) for r in top_score],
    }


def get_rankings(conn=None) -> dict:
    if conn is None:
        return get_dashboard().get("rankings", {})
    return _legacy_rankings(conn)


def run_backtest_summary(days: int = 30) -> dict:
    dash = get_dashboard(force_refresh=True)
    dash["days"] = days
    return dash


__all__ = [
    "get_dashboard",
    "get_history",
    "get_compare_detail",
    "get_lottery_intelligence",
    "get_rankings",
    "run_backtest_summary",
    "invalidate",
    "HISTORY_LIMITS",
]
