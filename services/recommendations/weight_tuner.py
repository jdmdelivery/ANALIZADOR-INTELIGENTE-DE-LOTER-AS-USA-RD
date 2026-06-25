"""Autoajuste simple de pesos según backtesting."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from models import get_connection

from services.recommendations.constants import DEFAULT_WEIGHTS, WEIGHT_MAX, WEIGHT_MIN
from services.recommendations.scoring import normalize_weights


def get_weights_for_family(family: str) -> dict[str, float]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT weights_json FROM recommendation_weights WHERE game_family = ?",
            (family,),
        ).fetchone()
        if row and row["weights_json"]:
            data = json.loads(row["weights_json"])
            return normalize_weights(data)
    except Exception:
        pass
    finally:
        conn.close()
    return dict(DEFAULT_WEIGHTS)


def tune_weights_from_backtests() -> dict:
    """Ajusta pesos: sube factores que correlacionan con más aciertos."""
    conn = get_connection()
    updated: list[str] = []
    try:
        since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        rows = conn.execute(
            """SELECT game_family, AVG(exact_hits) as avg_hits, AVG(position_hits) as avg_pos,
                      COUNT(*) as n
               FROM backtest_results WHERE evaluated_at >= ?
               GROUP BY game_family HAVING n >= 3""",
            (since,),
        ).fetchall()
        for row in rows:
            family = row["game_family"] or "quiniela_rd"
            weights = get_weights_for_family(family)
            avg = float(row["avg_hits"] or 0)
            if avg >= 1.5:
                weights["freq_25"] = min(WEIGHT_MAX, weights["freq_25"] + 0.03)
                weights["trend_10"] = min(WEIGHT_MAX, weights["trend_10"] + 0.02)
                weights["weekday"] = min(WEIGHT_MAX, weights.get("weekday", 0.07) + 0.01)
            elif avg < 0.5:
                weights["delay"] = min(WEIGHT_MAX, weights["delay"] + 0.02)
                weights["weekday"] = max(WEIGHT_MIN, weights.get("weekday", 0.07) - 0.01)
            weights = normalize_weights(weights)
            conn.execute(
                """INSERT INTO recommendation_weights (game_family, weights_json, updated_at)
                   VALUES (?,?,?)
                   ON CONFLICT(game_family) DO UPDATE SET
                   weights_json=excluded.weights_json, updated_at=excluded.updated_at""",
                (
                    family,
                    json.dumps(weights),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            updated.append(family)
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "updated_families": updated}
