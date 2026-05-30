"""
Actualización Lucky Day Lotto — fuentes dedicadas + fallback ILN + caché.
No afecta otras loterías USA.
"""
from __future__ import annotations

import logging
import time

from models import count_results_for_lottery, get_all_lotteries

logger = logging.getLogger(__name__)
LOG = "[USA SCRAPER]"
LOTTERY_NAME = "Lucky Day Lotto"

SOURCE_LABELS = {
    "illinoislottery": "Illinois Lottery",
    "lotteryusa": "LotteryUSA",
    "illinoislotterynumbers": "IllinoisLotteryNumbers",
    "cache_json": "Cache Local",
    "cache": "Cache Local",
    "database": "Cache Local",
}


def _is_lucky_day_request(loteria: str | None) -> bool:
    return (loteria or "").strip().lower() == LOTTERY_NAME.lower()


def _saved(res: dict) -> bool:
    return int(res.get("imported") or 0) + int(res.get("updated") or 0) > 0


def _illinois_live_ok(res: dict) -> bool:
    if not res or not res.get("ok"):
        return False
    if res.get("from_cache"):
        return False
    if res.get("status") == "hub_unreachable":
        return False
    if res.get("hub_error"):
        return False
    live_status = res.get("live_status_code")
    if live_status and int(live_status) >= 400:
        return False
    return True


def _count_lucky_day_db() -> int:
    for lot in get_all_lotteries(active_only=True):
        if lot.get("country") != "USA":
            continue
        if lot["name"].lower() == LOTTERY_NAME.lower():
            return count_results_for_lottery(lot["id"])
    return 0


def _record(sources: list, key: str, res: dict, url: str = "") -> None:
    sources.append({
        "fuente": key,
        "fuente_label": SOURCE_LABELS.get(key, key),
        "ok": bool(res.get("ok")),
        "status_code": res.get("status_code"),
        "elapsed": res.get("elapsed"),
        "sorteos": res.get("rows_parsed") or 0,
        "imported": res.get("imported", 0),
        "updated": res.get("updated", 0),
        "error": (res.get("errors") or [res.get("message") or res.get("error")])[0]
        if not res.get("ok")
        else None,
        "url": url or res.get("url") or "",
    })


def _log_fuente(label: str) -> None:
    logger.info("%s Lucky Day Lotto | Fuente usada: %s", LOG, label)


def _import_lucky_day_cache() -> dict:
    from scrapers.cache.usa_results_cache import load_results_snapshot
    from services.resultados.illinois_scraper import _import_rows_grouped

    snap = load_results_snapshot()
    rows = [
        r for r in (snap.get("resultados") or [])
        if (r.get("lottery_name") or "").lower() == LOTTERY_NAME.lower()
    ]
    if not rows:
        return {"ok": False, "message": "Sin caché JSON para Lucky Day Lotto"}

    imported, updated, errors, _ = _import_rows_grouped(rows)
    fuente = snap.get("fuente") or "cache"
    return {
        "ok": imported + updated > 0 or bool(rows),
        "imported": imported,
        "updated": updated,
        "errors": errors,
        "fuente": fuente,
        "fuente_label": SOURCE_LABELS.get("cache_json", "Cache Local"),
        "cache": True,
        "saved": imported + updated,
        "rows_parsed": len(rows),
        "message": f"Caché local Lucky Day ({imported} nuevos, {updated} actualizados).",
    }


def _success(res: dict, *, fuente_key: str, warning: bool = False, cache: bool = False) -> dict:
    label = res.get("fuente_label") or SOURCE_LABELS.get(fuente_key, fuente_key)
    _log_fuente(label)
    out = {
        **res,
        "ok": True,
        "pais": "US",
        "parser": "lucky_day_multi",
        "fuente": fuente_key,
        "fuente_label": label,
        "fuente_usada": label,
        "warning": warning or cache,
        "cache": cache,
        "lottery_name": LOTTERY_NAME,
    }
    if cache:
        out["mensaje"] = res.get("message") or "Mostrando resultados guardados (caché local)."
    elif warning:
        out["mensaje"] = res.get("message") or f"Fuente principal falló. Se usó {label}."
    else:
        out["mensaje"] = res.get("message") or "Resultados actualizados correctamente"
    out["message"] = out["mensaje"]
    return out


def actualizar_lucky_day_lotto() -> dict:
    """
    1. Illinois Lottery (oficial)
    2. LotteryUSA (fuente actual en Render si Illinois falla)
    3. IllinoisLotteryNumbers.net
    4. Caché JSON
    5. BD (nunca error si hay datos)
    """
    sources_tried: list[dict] = []
    errors: list[str] = []
    t0 = time.monotonic()
    illinois: dict = {}

    logger.info("%s === Lucky Day Lotto — inicio actualización dedicada ===", LOG)

    # 1 — Illinois Lottery
    try:
        from scrapers.illinois_scraper import import_illinois_lottery_now

        illinois = import_illinois_lottery_now(LOTTERY_NAME)
        illinois["elapsed"] = round(time.monotonic() - t0, 2)
        _record(sources_tried, "illinoislottery", illinois, "https://www.illinoislottery.com/results-hub")
        if illinois.get("ok") and _illinois_live_ok(illinois) and _saved(illinois):
            return _success(illinois, fuente_key="illinoislottery")
        if not illinois.get("ok"):
            errors.append(illinois.get("message") or "Illinois Lottery falló")
        else:
            errors.append(illinois.get("message") or "Illinois sin datos en vivo para Lucky Day")
    except Exception as exc:
        logger.exception("%s Lucky Day Illinois error", LOG)
        errors.append(str(exc))

    # 2 — LotteryUSA (fuente actual alternativa)
    logger.info("%s Lucky Day — probando LotteryUSA", LOG)
    try:
        from scrapers.lotteryusa_scraper import import_lotteryusa_results

        usa = import_lotteryusa_results(LOTTERY_NAME)
        _record(sources_tried, "lotteryusa", usa)
        if usa.get("ok") and (_saved(usa) or int(usa.get("rows_parsed") or 0) > 0):
            return _success(usa, fuente_key="lotteryusa", warning=not _illinois_live_ok(illinois))
        if usa.get("message"):
            errors.append(usa["message"])
    except Exception as exc:
        logger.exception("%s Lucky Day LotteryUSA error", LOG)
        errors.append(str(exc))

    # 3 — IllinoisLotteryNumbers.net
    logger.info("%s Lucky Day — probando IllinoisLotteryNumbers.net", LOG)
    try:
        from scrapers.illinoislotterynumbers_luckyday import import_iln_luckyday_results

        iln = import_iln_luckyday_results()
        _record(sources_tried, "illinoislotterynumbers", iln)
        if iln.get("ok") and (_saved(iln) or int(iln.get("rows_parsed") or 0) > 0):
            return _success(iln, fuente_key="illinoislotterynumbers", warning=True)
        if iln.get("message"):
            errors.append(iln["message"])
    except Exception as exc:
        logger.exception("%s Lucky Day ILN error", LOG)
        errors.append(str(exc))

    # 4 — Caché JSON
    logger.info("%s Lucky Day — probando caché JSON local", LOG)
    try:
        cached = _import_lucky_day_cache()
        _record(sources_tried, "cache_json", cached)
        if cached.get("ok") and int(cached.get("saved") or 0) > 0:
            return _success(cached, fuente_key="cache_json", cache=True)
    except Exception as exc:
        logger.exception("%s Lucky Day caché JSON error", LOG)
        errors.append(str(exc))

    # 5 — BD
    saved_db = _count_lucky_day_db()
    if saved_db > 0:
        _log_fuente("Cache Local")
        return {
            "ok": True,
            "pais": "US",
            "parser": "lucky_day_multi",
            "fuente": "database",
            "fuente_label": "Cache Local",
            "fuente_usada": "Cache Local",
            "warning": True,
            "cache": True,
            "saved_count": saved_db,
            "imported": 0,
            "updated": 0,
            "sources_tried": sources_tried,
            "errors": errors[:10],
            "mensaje": "Mostrando resultados guardados (última actualización en BD).",
            "message": "Mostrando resultados guardados (última actualización en BD).",
        }

    logger.error("%s Lucky Day — todas las fuentes fallaron", LOG)
    return {
        "ok": False,
        "pais": "US",
        "lottery_name": LOTTERY_NAME,
        "sources_tried": sources_tried,
        "errors": errors,
        "message": errors[0] if errors else "No se pudo actualizar Lucky Day Lotto",
    }
