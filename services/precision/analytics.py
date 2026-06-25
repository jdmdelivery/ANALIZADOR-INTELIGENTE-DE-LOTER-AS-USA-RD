"""Agregaciones SQL para el dashboard de precisión."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from models import get_connection, parse_numbers, row_to_dict

from services.precision.constants import (
    FACTOR_LABELS,
    GAME_FAMILY_LABELS,
    HIT_SUCCESS_THRESHOLD,
    STATUS_BAD,
    STATUS_EXCELLENT,
    STATUS_GOOD,
    STATUS_ICONS,
    STATUS_LABELS,
    STATUS_REGULAR,
    WEEKDAY_ES,
)


def status_from_pct(pct: float | None) -> str:
    if pct is None:
        return STATUS_REGULAR
    if pct >= 80:
        return STATUS_EXCELLENT
    if pct >= 60:
        return STATUS_GOOD
    if pct >= 35:
        return STATUS_REGULAR
    return STATUS_BAD


def status_display(pct: float | None) -> dict:
    s = status_from_pct(pct)
    return {"status": s, "icon": STATUS_ICONS[s], "label": STATUS_LABELS[s]}


def _avg_pct(conn, where: str = "", params: tuple = ()) -> float:
    row = conn.execute(
        f"SELECT AVG(hit_percentage) as v FROM backtest_results WHERE hit_percentage IS NOT NULL {where}",
        params,
    ).fetchone()
    return round(float(row["v"] or 0), 2)


def build_snapshot(conn) -> dict:
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    rec_today = conn.execute(
        "SELECT COUNT(*) as c FROM recommendation_runs WHERE date(created_at) = date(?)",
        (today,),
    ).fetchone()["c"]

    total_runs = conn.execute("SELECT COUNT(*) as c FROM recommendation_runs").fetchone()["c"]
    total_eval = conn.execute("SELECT COUNT(*) as c FROM backtest_results").fetchone()["c"]

    hits_today = conn.execute(
        """SELECT COUNT(*) as c FROM backtest_results
           WHERE date(evaluated_at) = date(?) AND hit_percentage >= ?""",
        (today, HIT_SUCCESS_THRESHOLD),
    ).fetchone()["c"]

    precision_today = _avg_pct(
        conn, "AND date(evaluated_at) = date(?)", (today,)
    ) if conn.execute(
        "SELECT COUNT(*) as c FROM backtest_results WHERE date(evaluated_at)=date(?)", (today,)
    ).fetchone()["c"] else 0.0

    precision_7d = _avg_pct(conn, "AND evaluated_at >= ?", (week_ago,))
    precision_30d = _avg_pct(conn, "AND evaluated_at >= ?", (month_ago,))
    precision_hist = _avg_pct(conn)

    last_eval = conn.execute(
        "SELECT MAX(evaluated_at) as m FROM backtest_results"
    ).fetchone()["m"]
    last_rec = conn.execute(
        "SELECT MAX(created_at) as m FROM recommendation_runs"
    ).fetchone()["m"]
    last_updated = max(filter(None, [last_eval, last_rec])) or now.strftime("%Y-%m-%d %H:%M:%S")

    avg_score = conn.execute(
        "SELECT AVG(score) as v FROM backtest_results"
    ).fetchone()["v"]
    avg_score = round(float(avg_score or 0), 2)

    exec_status = status_from_pct(precision_7d or precision_hist)

    return {
        "ok": True,
        "last_updated": last_updated,
        "executive": {
            "status": exec_status,
            "status_icon": STATUS_ICONS[exec_status],
            "status_label": STATUS_LABELS[exec_status],
            "precision_historical": precision_hist,
            "precision_30d": precision_30d,
            "precision_7d": precision_7d,
            "precision_today": precision_today,
        },
        "kpis": {
            "recommendations_today": rec_today,
            "hits_today": hits_today,
            "precision_7d": precision_7d,
            "precision_30d": precision_30d,
            "avg_score": avg_score,
            "total_analyses": total_runs,
            "total_evaluated": total_eval,
        },
        "precision_by_game_type": _precision_by_game_type(conn),
        "lottery_table": _lottery_table(conn),
        "algorithm_ranking": _algorithm_ranking(conn),
        "lottery_rankings": _lottery_rankings(conn),
        "charts": _chart_series(conn),
        "evolution": _evolution_timeline(conn),
        "factor_performance": _factor_performance(conn),
        "learning_insights": _learning_insights(conn),
        "intelligence_answers": _intelligence_answers(conn),
        "stats_limits": _stats_limits(conn),
    }


def _precision_by_game_type(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT game_family,
                  COUNT(*) as n,
                  AVG(hit_percentage) as avg_pct,
                  SUM(CASE WHEN hit_percentage >= ? THEN 1 ELSE 0 END) as hits
           FROM backtest_results
           WHERE game_family IS NOT NULL
           GROUP BY game_family ORDER BY avg_pct DESC""",
        (HIT_SUCCESS_THRESHOLD,),
    ).fetchall()
    out = []
    for r in rows:
        fam = r["game_family"] or "?"
        meta = GAME_FAMILY_LABELS.get(fam, {"icon": "🎲", "label": fam})
        pct = round(float(r["avg_pct"] or 0), 2)
        st = status_display(pct)
        out.append({
            "game_family": fam,
            "icon": meta["icon"],
            "label": meta["label"],
            "evaluations": r["n"],
            "hits": r["hits"],
            "precision_pct": pct,
            **st,
        })
    return out


def _lottery_table(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT l.id, l.name, l.country, l.type,
                  COUNT(b.id) as recommendations,
                  SUM(CASE WHEN b.hit_percentage >= ? THEN 1 ELSE 0 END) as hits,
                  AVG(b.hit_percentage) as avg_pct,
                  AVG(b.score) as avg_score
           FROM lotteries l
           LEFT JOIN backtest_results b ON b.lottery_id = l.id
           WHERE l.active = 1
           GROUP BY l.id
           ORDER BY CASE WHEN avg_pct IS NULL THEN 1 ELSE 0 END, avg_pct DESC, l.name""",
        (HIT_SUCCESS_THRESHOLD,),
    ).fetchall()
    result = []
    for r in rows:
        pct = round(float(r["avg_pct"] or 0), 2) if r["recommendations"] else None
        st = status_display(pct if pct is not None else 0)
        fam = r["type"] or ""
        meta = GAME_FAMILY_LABELS.get(fam.split("_")[0] if fam else "", {})
        result.append({
            "lottery_id": r["id"],
            "lottery_name": r["name"],
            "country": r["country"],
            "game_type": r["type"],
            "game_type_label": meta.get("label", r["type"] or "—"),
            "recommendations": r["recommendations"] or 0,
            "hits": r["hits"] or 0,
            "precision_pct": pct,
            "avg_score": round(float(r["avg_score"] or 0), 2) if r["avg_score"] else None,
            **st,
        })
    return result


def _algorithm_ranking(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT COALESCE(b.game_family, r.adapter, '?') as motor,
                  COUNT(*) as total,
                  SUM(CASE WHEN b.hit_percentage >= ? THEN 1 ELSE 0 END) as hits,
                  AVG(b.hit_percentage) as avg_pct
           FROM backtest_results b
           LEFT JOIN recommendation_runs r ON r.id = b.recommendation_run_id
           GROUP BY motor ORDER BY avg_pct DESC""",
        (HIT_SUCCESS_THRESHOLD,),
    ).fetchall()
    out = []
    for r in rows:
        motor = r["motor"] or "?"
        meta = GAME_FAMILY_LABELS.get(motor, {"icon": "⚙️", "label": motor})
        hits = int(r["hits"] or 0)
        total = int(r["total"] or 0)
        last_hit = conn.execute(
            """SELECT evaluated_at FROM backtest_results
               WHERE COALESCE(game_family, '?') = ? AND hit_percentage >= ?
               ORDER BY evaluated_at DESC LIMIT 1""",
            (motor, HIT_SUCCESS_THRESHOLD),
        ).fetchone()
        last_miss = conn.execute(
            """SELECT evaluated_at FROM backtest_results
               WHERE COALESCE(game_family, '?') = ? AND hit_percentage < ?
               ORDER BY evaluated_at DESC LIMIT 1""",
            (motor, HIT_SUCCESS_THRESHOLD),
        ).fetchone()
        pct = round(float(r["avg_pct"] or 0), 2)
        out.append({
            "motor": motor,
            "label": meta.get("label", motor),
            "icon": meta.get("icon", "⚙️"),
            "precision_pct": pct,
            "hits": hits,
            "errors": total - hits,
            "total": total,
            "last_hit": last_hit["evaluated_at"] if last_hit else None,
            "last_miss": last_miss["evaluated_at"] if last_miss else None,
            **status_display(pct),
            "status_icon": status_display(pct)["icon"],
            "status_label": status_display(pct)["label"],
        })
    return out


def _lottery_rankings(conn) -> dict:
    rows = conn.execute(
        """SELECT l.name, AVG(b.hit_percentage) as avg_pct, COUNT(b.id) as n
           FROM backtest_results b
           JOIN lotteries l ON l.id = b.lottery_id
           GROUP BY l.id HAVING n >= 1
           ORDER BY avg_pct DESC"""
    ).fetchall()
    items = [
        {"name": r["name"], "precision_pct": round(float(r["avg_pct"] or 0), 2), "count": r["n"]}
        for r in rows
    ]
    return {
        "top_10": items[:10],
        "bottom_10": list(reversed(items[-10:])) if len(items) > 10 else list(reversed(items)),
    }


def _chart_series(conn) -> dict:
    daily = conn.execute(
        """SELECT date(evaluated_at) as d,
                  AVG(hit_percentage) as avg_pct,
                  COUNT(*) as n,
                  SUM(CASE WHEN hit_percentage >= ? THEN 1 ELSE 0 END) as hits
           FROM backtest_results WHERE evaluated_at >= date('now', '-90 days')
           GROUP BY d ORDER BY d""",
        (HIT_SUCCESS_THRESHOLD,),
    ).fetchall()
    weekly = conn.execute(
        """SELECT strftime('%Y-W%W', evaluated_at) as w,
                  AVG(hit_percentage) as avg_pct, COUNT(*) as n
           FROM backtest_results WHERE evaluated_at >= date('now', '-365 days')
           GROUP BY w ORDER BY w"""
    ).fetchall()
    monthly = conn.execute(
        """SELECT strftime('%Y-%m', evaluated_at) as m,
                  AVG(hit_percentage) as avg_pct, COUNT(*) as n
           FROM backtest_results GROUP BY m ORDER BY m"""
    ).fetchall()
    rec_daily = conn.execute(
        """SELECT date(created_at) as d, COUNT(*) as n
           FROM recommendation_runs WHERE created_at >= date('now', '-90 days')
           GROUP BY d ORDER BY d"""
    ).fetchall()
    by_lot = conn.execute(
        """SELECT l.name, AVG(b.hit_percentage) as avg_pct, COUNT(*) as n
           FROM backtest_results b JOIN lotteries l ON l.id = b.lottery_id
           GROUP BY l.name ORDER BY avg_pct DESC LIMIT 20"""
    ).fetchall()
    by_alg = conn.execute(
        """SELECT game_family, AVG(hit_percentage) as avg_pct, COUNT(*) as n
           FROM backtest_results WHERE game_family IS NOT NULL GROUP BY game_family"""
    ).fetchall()
    score_hist = conn.execute(
        """SELECT date(evaluated_at) as d, AVG(score) as avg_score, AVG(hit_percentage) as avg_pct
           FROM backtest_results WHERE evaluated_at >= date('now', '-90 days')
           GROUP BY d ORDER BY d"""
    ).fetchall()
    return {
        "precision_daily": [{"label": r["d"], "value": round(r["avg_pct"] or 0, 2), "count": r["n"], "hits": r["hits"]} for r in daily],
        "precision_weekly": [{"label": r["w"], "value": round(r["avg_pct"] or 0, 2), "count": r["n"]} for r in weekly],
        "precision_monthly": [{"label": r["m"], "value": round(r["avg_pct"] or 0, 2), "count": r["n"]} for r in monthly],
        "recommendations_daily": [{"label": r["d"], "value": r["n"]} for r in rec_daily],
        "by_lottery": [{"label": r["name"], "value": round(r["avg_pct"] or 0, 2), "count": r["n"]} for r in by_lot],
        "by_algorithm": [{"label": r["game_family"] or "?", "value": round(r["avg_pct"] or 0, 2), "count": r["n"]} for r in by_alg],
        "score_and_precision": [
            {"label": r["d"], "score": round(r["avg_score"] or 0, 2), "precision": round(r["avg_pct"] or 0, 2)}
            for r in score_hist
        ],
        "hits_daily": [{"label": r["d"], "value": r["hits"]} for r in daily],
    }


def _evolution_timeline(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT strftime('%Y-W%W', evaluated_at) as w,
                  AVG(hit_percentage) as avg_pct, COUNT(*) as n
           FROM backtest_results
           WHERE evaluated_at >= date('now', '-56 days')
           GROUP BY w ORDER BY w"""
    ).fetchall()
    return [
        {"week": i + 1, "label": r["w"], "precision_pct": round(float(r["avg_pct"] or 0), 2), "evaluations": r["n"]}
        for i, r in enumerate(rows)
    ]


def _factor_performance(conn) -> list[dict]:
    """Efectividad estimada por factor según pesos actuales y precisión por familia."""
    rows = conn.execute(
        "SELECT game_family, weights_json FROM recommendation_weights"
    ).fetchall()
    if not rows:
        rows = []
    weight_acc: dict[str, list[float]] = {k: [] for k in FACTOR_LABELS}
    for r in rows:
        fam = r["game_family"]
        pct_row = conn.execute(
            "SELECT AVG(hit_percentage) as v FROM backtest_results WHERE game_family = ?",
            (fam,),
        ).fetchone()
        fam_pct = float(pct_row["v"] or 50)
        try:
            w = json.loads(r["weights_json"] or "{}")
        except Exception:
            w = {}
        for key in FACTOR_LABELS:
            weight_acc[key].append(float(w.get(key, 0.1)) * fam_pct)

    from services.recommendations.constants import DEFAULT_WEIGHTS

    out = []
    for key, label in FACTOR_LABELS.items():
        if weight_acc[key]:
            score = round(sum(weight_acc[key]) / len(weight_acc[key]) * 100, 0)
        else:
            score = round(float(DEFAULT_WEIGHTS.get(key, 0.1)) * 72, 0)
        score = min(100, max(0, int(score)))
        out.append({"factor": key, "label": label, "effectiveness_pct": score})
    out.sort(key=lambda x: -x["effectiveness_pct"])
    return out


def _learning_insights(conn) -> list[dict]:
    insights: list[dict] = []
    try:
        hist = conn.execute(
            """SELECT game_family, old_weights_json, new_weights_json,
                      avg_hit_percentage, reason, created_at
               FROM precision_weight_history ORDER BY created_at DESC LIMIT 8"""
        ).fetchall()
    except Exception:
        hist = []
    for h in hist:
        try:
            old_w = json.loads(h["old_weights_json"] or "{}")
            new_w = json.loads(h["new_weights_json"] or "{}")
        except Exception:
            continue
        for key in FACTOR_LABELS:
            delta = round((new_w.get(key, 0) - old_w.get(key, 0)) * 100, 1)
            if abs(delta) < 0.5:
                continue
            label = FACTOR_LABELS[key]
            if delta > 0:
                insights.append({
                    "type": "up",
                    "icon": "✔",
                    "text": f"{label} funcionó mejor — peso +{delta}% ({h['game_family']})",
                    "at": h["created_at"],
                })
            else:
                insights.append({
                    "type": "down",
                    "icon": "✔",
                    "text": f"{label} perdió precisión — peso {delta}% ({h['game_family']})",
                    "at": h["created_at"],
                })
    if not insights:
        insights.append({
            "type": "info",
            "icon": "ℹ️",
            "text": "El sistema aprenderá cuando haya más evaluaciones comparadas con resultados oficiales.",
            "at": None,
        })
    return insights[:12]


def _intelligence_answers(conn) -> dict:
    """Respuestas a preguntas clave del panel."""
    alg = _algorithm_ranking(conn)
    lot = _lottery_rankings(conn)
    best_alg = alg[0] if alg else None
    best_lot = lot["top_10"][0] if lot.get("top_10") else None
    worst_lot = lot["bottom_10"][0] if lot.get("bottom_10") else None

    by_type = _precision_by_game_type(conn)
    best_type = by_type[0] if by_type else None

    weekday_rows = conn.execute(
        """SELECT CAST(strftime('%w', draw_date) AS INTEGER) as wd,
                  AVG(hit_percentage) as avg_pct, COUNT(*) as n
           FROM backtest_results WHERE draw_date IS NOT NULL
           GROUP BY wd HAVING n >= 2 ORDER BY avg_pct DESC"""
    ).fetchall()
    best_wd = None
    if weekday_rows:
        wd = int(weekday_rows[0]["wd"])
        best_wd = {"day": WEEKDAY_ES[wd % 7], "precision_pct": round(float(weekday_rows[0]["avg_pct"] or 0), 2)}

    slot_rows = conn.execute(
        """SELECT draw_name, AVG(hit_percentage) as avg_pct, COUNT(*) as n
           FROM backtest_results GROUP BY draw_name HAVING n >= 2
           ORDER BY avg_pct DESC LIMIT 1"""
    ).fetchone()
    best_slot = None
    if slot_rows:
        best_slot = {
            "draw_name": slot_rows["draw_name"],
            "precision_pct": round(float(slot_rows["avg_pct"] or 0), 2),
        }

    factors = _factor_performance(conn)
    top_factor = factors[0] if factors else None

    return {
        "best_algorithm": best_alg,
        "worst_algorithm": alg[-1] if len(alg) > 1 else None,
        "best_lottery": best_lot,
        "worst_lottery": worst_lot,
        "best_analysis_type": best_type,
        "best_weekday": best_wd,
        "best_draw_slot": best_slot,
        "top_contributing_factor": top_factor,
    }


def _stats_limits(conn) -> dict:
    from services.precision.constants import HISTORY_LIMITS

    out = {}
    for n in HISTORY_LIMITS:
        row = conn.execute(
            """SELECT COUNT(*) as c, AVG(hit_percentage) as avg_pct, AVG(score) as avg_score
               FROM (SELECT hit_percentage, score FROM backtest_results
                     ORDER BY evaluated_at DESC LIMIT ?)""",
            (n,),
        ).fetchone()
        out[str(n)] = {
            "count": row["c"] or 0,
            "avg_hit_percentage": round(float(row["avg_pct"] or 0), 2),
            "avg_score": round(float(row["avg_score"] or 0), 2),
        }
    return out


def get_lottery_intelligence(lottery_id: int) -> dict:
    conn = get_connection()
    try:
        lot = conn.execute(
            "SELECT * FROM lotteries WHERE id = ?", (lottery_id,)
        ).fetchone()
        if not lot:
            return {"ok": False, "message": "Lotería no encontrada"}
        lot = row_to_dict(lot)

        stats = conn.execute(
            """SELECT COUNT(*) as n,
                      AVG(hit_percentage) as avg_pct,
                      AVG(score) as avg_score,
                      SUM(CASE WHEN hit_percentage >= ? THEN 1 ELSE 0 END) as hits
               FROM backtest_results WHERE lottery_id = ?""",
            (HIT_SUCCESS_THRESHOLD, lottery_id),
        ).fetchone()

        top10 = conn.execute(
            """SELECT * FROM backtest_results WHERE lottery_id = ?
               ORDER BY hit_percentage DESC LIMIT 10""",
            (lottery_id,),
        ).fetchall()

        recent_hits = conn.execute(
            """SELECT * FROM backtest_results WHERE lottery_id = ?
               AND hit_percentage >= ? ORDER BY evaluated_at DESC LIMIT 10""",
            (lottery_id, HIT_SUCCESS_THRESHOLD),
        ).fetchall()

        recent_miss = conn.execute(
            """SELECT * FROM backtest_results WHERE lottery_id = ?
               AND hit_percentage < ? ORDER BY evaluated_at DESC LIMIT 10""",
            (lottery_id, HIT_SUCCESS_THRESHOLD),
        ).fetchall()

        algo = conn.execute(
            """SELECT r.algorithm_version, r.adapter, COUNT(*) as n
               FROM recommendation_runs r WHERE r.lottery_id = ?
               GROUP BY r.algorithm_version, r.adapter ORDER BY n DESC LIMIT 1""",
            (lottery_id,),
        ).fetchone()

        errors = _frequent_errors(conn, lottery_id)

        pct = round(float(stats["avg_pct"] or 0), 2) if stats["n"] else None
        return {
            "ok": True,
            "lottery": lot,
            "stats": {
                "evaluations": stats["n"] or 0,
                "hits": stats["hits"] or 0,
                "precision_pct": pct,
                "avg_score": round(float(stats["avg_score"] or 0), 2) if stats["avg_score"] else None,
                **status_display(pct or 0),
            },
            "algorithm": {
                "version": algo["algorithm_version"] if algo else None,
                "adapter": algo["adapter"] if algo else None,
            },
            "top_10": [_eval_brief(r) for r in top10],
            "recent_hits": [_eval_brief(r) for r in recent_hits],
            "recent_misses": [_eval_brief(r) for r in recent_miss],
            "frequent_errors": errors,
        }
    finally:
        conn.close()


def _frequent_errors(conn, lottery_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT position_hits, COUNT(*) as n FROM backtest_results
           WHERE lottery_id = ? AND hit_percentage < ?
           GROUP BY position_hits ORDER BY n DESC LIMIT 5""",
        (lottery_id, HIT_SUCCESS_THRESHOLD),
    ).fetchall()
    return [
        {"description": f"Fallos con {r['position_hits']} aciertos posicionales", "count": r["n"]}
        for r in rows
    ]


def _eval_brief(row) -> dict:
    d = row_to_dict(row)
    status = d.get("status_label") or status_from_pct(d.get("hit_percentage"))
    return {
        "id": d["id"],
        "draw_date": d.get("draw_date"),
        "evaluated_at": d.get("evaluated_at"),
        "predicted": d.get("predicted_numbers"),
        "actual": d.get("actual_numbers"),
        "hit_percentage": d.get("hit_percentage"),
        "score": d.get("score"),
        "status_icon": STATUS_ICONS.get(status, ""),
    }
