"""Descarga de historial RD/LEIDSA por fuente (30 / 90 días)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from models import get_all_lotteries
from services.lottery_normalize import find_lottery_in_list, normalize_lottery_name
from services.rd_lottery_config import get_rd_lottery_config, iter_enabled_conectate_configs

logger = logging.getLogger(__name__)

# Estado última ejecución (debug / UI)
_LAST_RUN: dict[str, Any] = {}


def _cutoff_date(days: int) -> str:
    return (datetime.now() - timedelta(days=max(1, days))).strftime("%Y-%m-%d")


def _record_run(source: str, days: int, result: dict) -> None:
    global _LAST_RUN
    _LAST_RUN = {
        "source": source,
        "days_requested": days,
        "ok": result.get("ok"),
        "imported": result.get("imported", result.get("inserted", 0)),
        "updated": result.get("updated", 0),
        "dates_found": result.get("dates_found", []),
        "total_saved": result.get("imported", 0) + result.get("updated", 0),
        "last_error": result.get("error") or (result.get("errors") or [None])[0],
        "supports_full_history": result.get("supports_full_history", True),
        "only_today_warning": result.get("only_today_warning"),
        "message": result.get("message"),
        "finished_at": datetime.now().isoformat(),
        "details": result.get("details"),
    }


def fetch_history_for_source(
    source: str,
    days: int = 90,
    lottery_name: str | None = None,
) -> dict[str, Any]:
    """
    Trae historial de una fuente.
    - conectate + lottery_name: una lotería RD
    - leidsa: todos los juegos LEIDSA
    - leidsa_game: un juego por nombre (resuelve slug)
    """
    source_key = (source or "").strip().lower().replace("-", "_")
    days = int(days or 90)

    try:
        if source_key in ("leidsa", "leidsa_com"):
            from services.leidsa_history import fetch_all_leidsa_history

            out = fetch_all_leidsa_history(days=days, save=True)
            out["source"] = "leidsa"
            out["supports_full_history"] = True
            out["imported"] = out.get("inserted", 0)
            fechas = set()
            for g in out.get("games") or []:
                pass
            out["message"] = (
                f"Historial LEIDSA: {days} días revisados, "
                f"{out.get('imported', 0)} nuevos, {out.get('updated', 0)} actualizados "
                f"({out.get('results_found', 0)} sorteos encontrados)."
            )
            _record_run("leidsa", days, out)
            return out

        if source_key == "leidsa_game" and lottery_name:
            from services.leidsa_config import LEIDSA_HISTORY_GAMES
            from services.leidsa_history import fetch_leidsa_game_history, save_leidsa_rows

            game = None
            for g in LEIDSA_HISTORY_GAMES:
                if g["name"] == lottery_name or g["slug"] in (lottery_name or ""):
                    game = g
                    break
            if not game:
                out = {"ok": False, "message": f"Juego LEIDSA no encontrado: {lottery_name}"}
                _record_run(source_key, days, out)
                return out
            res = fetch_leidsa_game_history(game, days=days, limit=120)
            rows = res.get("rows") or []
            batch = save_leidsa_rows(rows) if rows else {"inserted": 0, "updated": 0}
            out = {
                "ok": bool(rows),
                "source": "leidsa_game",
                "imported": batch.get("inserted", 0),
                "updated": batch.get("updated", 0),
                "results_found": len(rows),
                "supports_full_history": True,
                "message": (
                    f"{game['name']}: {days} días, {len(rows)} sorteos, "
                    f"{batch.get('inserted', 0)} nuevos, {batch.get('updated', 0)} actualizados."
                ),
            }
            _record_run(source_key, days, out)
            return out

        if source_key == "conectate" and lottery_name:
            from services.new_lotteries import is_new_rd_lottery

            lot = find_lottery_in_list(get_all_lotteries(), lottery_name, "RD")
            if lot and is_new_rd_lottery(lot):
                from scrapers.conectate_rd import import_conectate_lottery_bulk_style

                out = import_conectate_lottery_bulk_style(lottery_name, days_back=days)
                out["scraper"] = "conectate_rd_bulk"
            else:
                from scrapers.conectate_rd import import_conectate_lottery_history

                out = import_conectate_lottery_history(lottery_name, days=days)
                out["scraper"] = "conectate_rd_history"
            out["source"] = "conectate"
            _record_run(f"conectate:{lottery_name}", days, out)
            return out

        out = {"ok": False, "message": f"Fuente desconocida o sin lotería: {source}"}
        _record_run(source_key, days, out)
        return out
    except Exception as exc:
        logger.exception("fetch_history_for_source %s", source)
        out = {"ok": False, "error": str(exc), "message": str(exc)}
        _record_run(source_key, days, out)
        return out


def fetch_all_rd_history(days: int = 90) -> dict[str, Any]:
    """LEIDSA (90d drawResults) + todas las loterías Conectate habilitadas."""
    days = int(days or 90)
    total_imported = 0
    total_updated = 0
    errors: list[str] = []
    details: list[dict] = []
    dates_union: set[str] = set()
    only_today_sources: list[str] = []

    leidsa_out = fetch_history_for_source("leidsa", days=days)
    details.append({"name": "LEIDSA (todos los juegos)", **leidsa_out})
    if leidsa_out.get("ok"):
        total_imported += leidsa_out.get("imported", leidsa_out.get("inserted", 0))
        total_updated += leidsa_out.get("updated", 0)
    else:
        errors.append(leidsa_out.get("message") or "LEIDSA: error temporal")

    # Loterías nuevas: import masivo estilo original (sin tocar las viejas)
    try:
        from scrapers.conectate_rd import import_conectate_rd_new_lotteries_only

        new_out = import_conectate_rd_new_lotteries_only(days_back=days)
        details.append({"name": "Loterías nuevas (FL/King/NY)", **new_out})
        if new_out.get("ok"):
            total_imported += new_out.get("imported", 0)
            total_updated += new_out.get("updated", 0)
            for d in new_out.get("dates_found") or []:
                dates_union.add(d)
        else:
            errors.append(new_out.get("message") or "Error en loterías nuevas")
    except Exception as exc:
        errors.append(f"Loterías nuevas: {exc}")

    # Loterías viejas: solo historial incremental (misma lógica que ya tenían datos)
    from services.new_lotteries import is_new_rd_lottery

    refreshed: set[str] = set()
    for _label, cfg in iter_enabled_conectate_configs():
        db_name = cfg["db_names"][0]
        key = normalize_lottery_name(db_name)
        if key in refreshed:
            continue
        refreshed.add(key)
        lot = find_lottery_in_list(get_all_lotteries(active_only=True), db_name, "RD")
        if not lot or is_new_rd_lottery(lot):
            continue
        try:
            out = fetch_history_for_source("conectate", days=days, lottery_name=lot["name"])
            details.append({"name": lot["name"], **out})
            if out.get("ok"):
                total_imported += out.get("imported", 0)
                total_updated += out.get("updated", 0)
                for d in out.get("dates_found") or []:
                    dates_union.add(d)
                if out.get("only_today_warning"):
                    only_today_sources.append(lot["name"])
            else:
                errors.append(f"Error temporal en {lot['name']}: {out.get('message', 'error')}")
        except Exception as exc:
            errors.append(f"Error temporal en {db_name}: {exc}")

    saved = total_imported + total_updated
    msg = (
        f"Historial actualizado: {days} días revisados, "
        f"{saved} resultados guardados ({total_imported} nuevos, {total_updated} actualizados)."
    )
    if only_today_sources:
        msg += f" Aviso: solo día actual en: {', '.join(only_today_sources[:5])}."

    result = {
        "ok": bool(saved) or bool(leidsa_out.get("ok")) or any(d.get("ok") for d in details),
        "status": "updated" if saved else "no_new",
        "message": msg,
        "imported": total_imported,
        "updated": total_updated,
        "days": days,
        "dates_found": sorted(dates_union, reverse=True)[:60],
        "errors": errors,
        "details": details,
        "only_today_warning": only_today_sources,
        "supports_full_history": not only_today_sources,
        "leidsa_ok": bool(leidsa_out.get("ok")),
    }
    _record_run("all_rd", days, result)
    return result


def get_last_history_run() -> dict[str, Any]:
    return dict(_LAST_RUN)


def debug_history_status() -> dict[str, Any]:
    """GET /debug/history"""
    last = get_last_history_run()
    from models import count_results_by_lottery

    by_lot = count_results_by_lottery()
    rd_rows = [r for r in by_lot if r.get("country") == "RD"]
    return {
        "ok": True,
        "last_run": last,
        "rd_lotteries_in_db": rd_rows,
        "total_rd_results": sum(int(r.get("total") or 0) for r in rd_rows),
    }
