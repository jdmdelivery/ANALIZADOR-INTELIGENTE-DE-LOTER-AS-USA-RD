"""Dashboard y estadísticas de precisión — lectura de datos ya evaluados."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from models import get_connection, parse_numbers, row_to_dict

from services.precision.constants import HISTORY_LIMITS, STATUS_ICONS, STATUS_LABELS
from services.precision.evaluator import evaluate_all_pending


def get_dashboard() -> dict:
    evaluate_all_pending(limit=100)
    conn = get_connection()
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        rec_today = conn.execute(
            "SELECT COUNT(*) as c FROM recommendation_runs WHERE date(created_at) = date(?)",
            (today,),
        ).fetchone()["c"]

        hits_today = conn.execute(
            "SELECT COUNT(*) as c FROM backtest_results WHERE date(evaluated_at) = date(?) AND hit_percentage >= 60",
            (today,),
        ).fetchone()["c"]

        hits_week = conn.execute(
            "SELECT COUNT(*) as c FROM backtest_results WHERE evaluated_at >= ? AND hit_percentage >= 60",
            (week_ago,),
        ).fetchone()["c"]

        hits_month = conn.execute(
            "SELECT COUNT(*) as c FROM backtest_results WHERE evaluated_at >= ? AND hit_percentage >= 60",
            (month_ago,),
        ).fetchone()["c"]

        evaluated = conn.execute(
            "SELECT COUNT(*) as c, AVG(hit_percentage) as avg_pct, AVG(score) as avg_score FROM backtest_results"
        ).fetchone()

        by_lottery = _avg_group(conn, "lottery_name", "l.name", join_lotteries=True)
        by_family = _avg_group(conn, "game_family", "b.game_family")

        best_lot = _best_worst(by_lottery, best=True)
        worst_lot = _best_worst(by_lottery, best=False)
        best_alg = _best_worst(by_family, best=True)
        worst_alg = _best_worst(by_family, best=False)

        return {
            "ok": True,
            "recommendations_today": rec_today,
            "hits_today": hits_today,
            "hits_this_week": hits_week,
            "hits_this_month": hits_month,
            "total_evaluated": evaluated["c"] or 0,
            "avg_hit_percentage": round(evaluated["avg_pct"] or 0, 2),
            "avg_predicted_score": round(evaluated["avg_score"] or 0, 2),
            "overall_precision": round(evaluated["avg_pct"] or 0, 2),
            "best_lottery": best_lot,
            "worst_lottery": worst_lot,
            "best_algorithm": best_alg,
            "worst_algorithm": worst_alg,
            "precision_by_lottery": by_lottery,
            "precision_by_algorithm": by_family,
            "charts": _chart_series(conn),
            "rankings": get_rankings(conn),
            "stats_limits": {str(n): _count_evaluated(conn, n) for n in HISTORY_LIMITS},
        }
    finally:
        conn.close()


def get_history(limit: int = 100, offset: int = 0) -> dict:
    limit = min(max(int(limit), 1), 5000)
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT b.*, l.name as lottery_name, l.country,
                      r.algorithm_version, r.confidence_label, r.created_at as rec_created_at
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
            status = d.get("status_label") or "regular"
            d["status_icon"] = STATUS_ICONS.get(status, "")
            d["status_text"] = STATUS_LABELS.get(status, status)
            d["predicted_list"] = parse_numbers(d.get("predicted_numbers"))
            d["actual_list"] = parse_numbers(d.get("actual_numbers"))
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
                      r.payload_json, r.algorithm_version, r.factors_json
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
        status = d.get("status_label") or "regular"
        return {
            "ok": True,
            "evaluation": d,
            "predicted": parse_numbers(d.get("predicted_numbers")),
            "actual": parse_numbers(d.get("actual_numbers")),
            "predicted_bonus": parse_numbers(d.get("predicted_bonus") or ""),
            "detail": detail,
            "compare_summary": d.get("compare_summary") or "",
            "status_icon": STATUS_ICONS.get(status, ""),
            "status_text": STATUS_LABELS.get(status, status),
            "hit_percentage": d.get("hit_percentage"),
        }
    finally:
        conn.close()


def get_rankings(conn=None) -> dict:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        best = conn.execute(
            """SELECT b.*, l.name as lottery_name FROM backtest_results b
               JOIN lotteries l ON l.id = b.lottery_id
               WHERE b.hit_percentage IS NOT NULL
               ORDER BY b.hit_percentage DESC, b.achieved_score DESC LIMIT 20"""
        ).fetchall()
        worst = conn.execute(
            """SELECT b.*, l.name as lottery_name FROM backtest_results b
               JOIN lotteries l ON l.id = b.lottery_id
               WHERE b.hit_percentage IS NOT NULL
               ORDER BY b.hit_percentage ASC, b.achieved_score ASC LIMIT 20"""
        ).fetchall()
        top_score = conn.execute(
            """SELECT b.*, l.name as lottery_name FROM backtest_results b
               JOIN lotteries l ON l.id = b.lottery_id
               ORDER BY b.score DESC LIMIT 20"""
        ).fetchall()
        return {
            "best_hits": [_row_summary(r) for r in best],
            "worst_hits": [_row_summary(r) for r in worst],
            "top_predicted_score": [_row_summary(r) for r in top_score],
        }
    finally:
        if own:
            conn.close()


def _row_summary(row) -> dict:
    d = row_to_dict(row)
    status = d.get("status_label") or "regular"
    return {
        "id": d["id"],
        "lottery_name": d.get("lottery_name"),
        "draw_date": d.get("draw_date"),
        "hit_percentage": d.get("hit_percentage"),
        "score": d.get("score"),
        "status_icon": STATUS_ICONS.get(status, ""),
        "predicted": d.get("predicted_numbers"),
        "actual": d.get("actual_numbers"),
    }


def _avg_group(conn, alias: str, field: str, join_lotteries: bool = False) -> dict:
    if join_lotteries:
        sql = f"""SELECT l.name as lottery_name, AVG(b.hit_percentage) as avg_pct, COUNT(*) as n
                  FROM backtest_results b JOIN lotteries l ON l.id = b.lottery_id
                  WHERE b.hit_percentage IS NOT NULL GROUP BY l.name HAVING n >= 1"""
    else:
        sql = f"""SELECT b.game_family, AVG(b.hit_percentage) as avg_pct, COUNT(*) as n
                  FROM backtest_results b
                  WHERE b.hit_percentage IS NOT NULL GROUP BY b.game_family HAVING n >= 1"""
    rows = conn.execute(sql).fetchall()
    out = {}
    for r in rows:
        key = r["lottery_name"] if join_lotteries else (r["game_family"] or "?")
        out[key] = round(float(r["avg_pct"] or 0), 2)
    return out


def _best_worst(d: dict, *, best: bool) -> str | None:
    if not d:
        return None
    if best:
        return max(d.items(), key=lambda x: x[1])[0]
    return min(d.items(), key=lambda x: x[1])[0]


def _chart_series(conn) -> dict:
    daily = conn.execute(
        """SELECT date(evaluated_at) as d, AVG(hit_percentage) as avg_pct, COUNT(*) as n
           FROM backtest_results WHERE evaluated_at >= date('now', '-90 days')
           GROUP BY date(evaluated_at) ORDER BY d"""
    ).fetchall()
    weekly = conn.execute(
        """SELECT strftime('%Y-W%W', evaluated_at) as w, AVG(hit_percentage) as avg_pct, COUNT(*) as n
           FROM backtest_results WHERE evaluated_at >= date('now', '-365 days')
           GROUP BY w ORDER BY w"""
    ).fetchall()
    monthly = conn.execute(
        """SELECT strftime('%Y-%m', evaluated_at) as m, AVG(hit_percentage) as avg_pct, COUNT(*) as n
           FROM backtest_results GROUP BY m ORDER BY m"""
    ).fetchall()
    by_lot = conn.execute(
        """SELECT l.name, AVG(b.hit_percentage) as avg_pct FROM backtest_results b
           JOIN lotteries l ON l.id = b.lottery_id GROUP BY l.name ORDER BY avg_pct DESC LIMIT 15"""
    ).fetchall()
    by_alg = conn.execute(
        """SELECT game_family, AVG(hit_percentage) as avg_pct FROM backtest_results
           WHERE game_family IS NOT NULL GROUP BY game_family"""
    ).fetchall()
    score_hist = conn.execute(
        """SELECT date(evaluated_at) as d, AVG(score) as avg_score FROM backtest_results
           WHERE evaluated_at >= date('now', '-90 days') GROUP BY d ORDER BY d"""
    ).fetchall()
    return {
        "by_day": [{"label": r["d"], "value": round(r["avg_pct"] or 0, 2), "count": r["n"]} for r in daily],
        "by_week": [{"label": r["w"], "value": round(r["avg_pct"] or 0, 2), "count": r["n"]} for r in weekly],
        "by_month": [{"label": r["m"], "value": round(r["avg_pct"] or 0, 2), "count": r["n"]} for r in monthly],
        "by_lottery": [{"label": r["name"], "value": round(r["avg_pct"] or 0, 2)} for r in by_lot],
        "by_algorithm": [{"label": r["game_family"] or "?", "value": round(r["avg_pct"] or 0, 2)} for r in by_alg],
        "score_history": [{"label": r["d"], "value": round(r["avg_score"] or 0, 2)} for r in score_hist],
    }


def _count_evaluated(conn, limit: int) -> dict:
    row = conn.execute(
        """SELECT COUNT(*) as c, AVG(hit_percentage) as avg_pct, AVG(score) as avg_score
           FROM (SELECT hit_percentage, score FROM backtest_results ORDER BY evaluated_at DESC LIMIT ?)""",
        (limit,),
    ).fetchone()
    return {
        "count": row["c"] or 0,
        "avg_hit_percentage": round(row["avg_pct"] or 0, 2),
        "avg_score": round(row["avg_score"] or 0, 2),
    }
