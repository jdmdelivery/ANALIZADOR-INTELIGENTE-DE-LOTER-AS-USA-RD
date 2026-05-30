"""Debug GET /debug/new-lotteries"""
from __future__ import annotations

from models import get_db, get_max_draw_date
from services.new_lotteries import list_new_rd_lotteries, is_new_rd_lottery


def debug_new_lotteries() -> dict:
    items = []
    for lot in list_new_rd_lotteries(active_only=False):
        with get_db() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS c FROM lottery_results WHERE lottery_id = ?",
                (lot["id"],),
            ).fetchone()["c"]
            date_rows = conn.execute(
                """SELECT draw_date, COUNT(*) AS c FROM lottery_results
                   WHERE lottery_id = ? GROUP BY draw_date ORDER BY draw_date DESC""",
                (lot["id"],),
            ).fetchall()
            last_up = conn.execute(
                """SELECT MAX(updated_at) AS u FROM lottery_results WHERE lottery_id = ?""",
                (lot["id"],),
            ).fetchone()["u"]
            fuentes = conn.execute(
                """SELECT DISTINCT fuente FROM lottery_results WHERE lottery_id = ?""",
                (lot["id"],),
            ).fetchall()

        fechas = [r["draw_date"] for r in date_rows]
        items.append({
            "lottery": lot["name"],
            "lottery_id": lot["id"],
            "type": lot.get("type"),
            "is_new_batch": is_new_rd_lottery(lot),
            "total_results": total,
            "distinct_dates": len(fechas),
            "fechas_encontradas": fechas[:40],
            "last_draw_date": get_max_draw_date(lot["id"]),
            "last_update": last_up,
            "scraper_recommended": "import_conectate_rd_new_lotteries_only / bulk_style",
            "supports_history": len(fechas) >= 10,
            "fuentes": [f["fuente"] for f in fuentes if f["fuente"]],
        })

    return {"ok": True, "new_lotteries": items, "count": len(items)}
