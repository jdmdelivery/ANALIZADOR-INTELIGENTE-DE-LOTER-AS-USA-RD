"""Autoaprendizaje con historial de cambios de pesos (máx. 5% por ciclo)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from models import get_connection

from services.precision.constants import MAX_WEIGHT_DELTA
from services.recommendations.constants import DEFAULT_WEIGHTS, WEIGHT_MAX, WEIGHT_MIN
from services.recommendations.scoring import normalize_weights


def tune_weights_after_evaluation() -> dict:
    """Ajusta pesos según precisión reciente; registra historial."""
    conn = get_connection()
    updated: list[str] = []
    try:
        since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        rows = conn.execute(
            """SELECT game_family,
                      AVG(hit_percentage) as avg_pct,
                      AVG(position_hits) as avg_pos,
                      COUNT(*) as n
               FROM backtest_results
               WHERE evaluated_at >= ? AND hit_percentage IS NOT NULL
               GROUP BY game_family HAVING n >= 3""",
            (since,),
        ).fetchall()

        for row in rows:
            family = row["game_family"] or "quiniela_rd"
            old_weights = _load_weights(conn, family)
            new_weights = dict(old_weights)
            avg_pct = float(row["avg_pct"] or 0)

            if avg_pct >= 70:
                new_weights["freq_25"] = _bump(old_weights["freq_25"], +MAX_WEIGHT_DELTA * 0.6)
                new_weights["trend_10"] = _bump(old_weights["trend_10"], +MAX_WEIGHT_DELTA * 0.4)
            elif avg_pct < 40:
                new_weights["delay"] = _bump(old_weights["delay"], +MAX_WEIGHT_DELTA * 0.5)
                new_weights["freq_25"] = _bump(old_weights["freq_25"], -MAX_WEIGHT_DELTA * 0.3)

            new_weights = normalize_weights(new_weights)
            if new_weights == old_weights:
                continue

            conn.execute(
                """INSERT INTO recommendation_weights (game_family, weights_json, updated_at)
                   VALUES (?,?,?)
                   ON CONFLICT(game_family) DO UPDATE SET
                   weights_json=excluded.weights_json, updated_at=excluded.updated_at""",
                (family, json.dumps(new_weights), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.execute(
                """INSERT INTO precision_weight_history
                   (game_family, old_weights_json, new_weights_json, avg_hit_percentage, reason, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    family,
                    json.dumps(old_weights),
                    json.dumps(new_weights),
                    round(avg_pct, 2),
                    f"auto_cycle avg_pct={avg_pct:.1f}",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            updated.append(family)
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "updated_families": updated}


def _bump(value: float, delta: float) -> float:
    return max(WEIGHT_MIN, min(WEIGHT_MAX, value + delta))


def _load_weights(conn, family: str) -> dict:
    row = conn.execute(
        "SELECT weights_json FROM recommendation_weights WHERE game_family = ?",
        (family,),
    ).fetchone()
    if row and row["weights_json"]:
        try:
            return normalize_weights(json.loads(row["weights_json"]))
        except Exception:
            pass
    return dict(DEFAULT_WEIGHTS)


def get_weight_history(limit: int = 50) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM precision_weight_history
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
