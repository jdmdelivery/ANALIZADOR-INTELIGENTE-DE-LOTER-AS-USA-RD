"""
Actualización Lucky Day Lotto — 7 fuentes + caché BD.
No afecta otras loterías USA.
"""
from __future__ import annotations

import logging
import time

from models import count_results_for_lottery, get_all_lotteries, get_max_draw_date
from services.lottery_dates import max_draw_date_in_rows, recent_cutoff

logger = logging.getLogger(__name__)
LOG = "[USA SCRAPER]"
LOTTERY_NAME = "Lucky Day Lotto"

SOURCE_CHAIN: list[tuple[str, str, str]] = [
    ("illinois_dbg", "import_illinois_dbg_luckyday", "Illinois Lottery DBG"),
    ("illinois_hub", "import_illinois_hub_luckyday", "Illinois Results Hub"),
    ("lotteryusa", "import_lotteryusa_luckyday", "LotteryUSA"),
    ("lotterypost", "import_lotterypost_luckyday_past", "LotteryPost"),
    ("illinoislotterynumbers", "import_iln_luckyday_past", "IllinoisLotteryNumbers"),
    ("lottery_net", "import_lottery_net_luckyday", "Lottery.net"),
]

SOURCE_LABELS = {k: label for k, _, label in SOURCE_CHAIN}
SOURCE_LABELS.update({
    "cache_json": "Cache Local",
    "database": "Cache Local",
})


def _is_lucky_day_request(loteria: str | None) -> bool:
    return (loteria or "").strip().lower() == LOTTERY_NAME.lower()


def _saved(res: dict) -> bool:
    return int(res.get("imported") or 0) + int(res.get("updated") or 0) > 0


def _rows_parsed(res: dict) -> int:
    return int(res.get("rows_parsed") or res.get("rows_found") or 0)


def _lucky_day_lottery_id() -> int | None:
    for lot in get_all_lotteries(active_only=True):
        if lot.get("country") != "USA":
            continue
        if lot["name"].lower() == LOTTERY_NAME.lower():
            return lot["id"]
    return None


def _source_has_fresh_data(res: dict) -> bool:
    """True si importó filas nuevas o las fechas parseadas son más recientes que la BD."""
    if not res or not res.get("ok"):
        return False
    if int(res.get("imported") or 0) > 0:
        return True

    lid = _lucky_day_lottery_id()
    db_max = get_max_draw_date(lid) if lid else ""
    src_max = res.get("latest_date") or max_draw_date_in_rows(res.get("rows") or []) or ""
    if src_max and (not db_max or src_max > db_max):
        return True

    cutoff = recent_cutoff(14)
    if src_max and src_max >= cutoff and _saved(res):
        return True

    # Solo actualizaciones sin fechas nuevas y BD ya al día → no aceptar fuente Illinois/caché
    if int(res.get("updated") or 0) > 0 and db_max and db_max >= recent_cutoff(7):
        return False

    if db_max and src_max and src_max < db_max:
        return False

    return _rows_parsed(res) > 0 and bool(src_max) and src_max >= cutoff


def _source_ok(res: dict) -> bool:
    """Éxito solo si la fuente trae datos frescos o guardó filas nuevas."""
    if not res or not res.get("ok"):
        return False
    return _source_has_fresh_data(res)


def _count_lucky_day_db() -> int:
    for lot in get_all_lotteries(active_only=True):
        if lot.get("country") != "USA":
            continue
        if lot["name"].lower() == LOTTERY_NAME.lower():
            return count_results_for_lottery(lot["id"])
    return 0


def _record(sources: list, key: str, res: dict) -> None:
    sources.append({
        "fuente": key,
        "fuente_label": res.get("fuente_label") or SOURCE_LABELS.get(key, key),
        "ok": bool(res.get("ok")),
        "status_code": res.get("status_code"),
        "elapsed": res.get("elapsed"),
        "sorteos": _rows_parsed(res),
        "imported": res.get("imported", 0),
        "updated": res.get("updated", 0),
        "error": (res.get("errors") or [res.get("message") or res.get("error")])[0]
        if not res.get("ok")
        else None,
        "url": res.get("url") or "",
    })


def _log_fuente(label: str, res: dict) -> None:
    logger.info(
        "%s Lucky Day Lotto | Fuente usada: %s | imp=%s upd=%s sorteos=%s",
        LOG,
        label,
        res.get("imported", 0),
        res.get("updated", 0),
        _rows_parsed(res),
    )


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
    return {
        "ok": imported + updated > 0 or bool(rows),
        "imported": imported,
        "updated": updated,
        "errors": errors,
        "fuente": "cache_json",
        "fuente_label": "Cache Local",
        "cache": True,
        "rows_parsed": len(rows),
        "message": f"Caché local Lucky Day ({imported} nuevos, {updated} actualizados).",
    }


def _success(res: dict, *, fuente_key: str, sources_tried: list, cache: bool = False) -> dict:
    label = res.get("fuente_label") or SOURCE_LABELS.get(fuente_key, fuente_key)
    _log_fuente(label, res)
    live_alt = fuente_key not in ("illinoislottery", "illinois_dbg", "illinois_hub") and not cache
    out = {
        **res,
        "ok": True,
        "pais": "US",
        "parser": "lucky_day_multi",
        "fuente": fuente_key,
        "fuente_label": label,
        "fuente_usada": label,
        "warning": cache,
        "cache": cache,
        "lottery_name": LOTTERY_NAME,
        "sources_tried": sources_tried,
    }
    if cache:
        out["mensaje"] = res.get("message") or "Mostrando resultados guardados (caché local)."
    elif live_alt and _saved(res):
        out["mensaje"] = f"✅ Lucky Day actualizado desde {label} ({res.get('imported', 0)} nuevos, {res.get('updated', 0)} actualizados)."
    elif _saved(res):
        out["mensaje"] = f"✅ {res.get('message') or 'Lucky Day Lotto actualizado correctamente.'}"
    elif _rows_parsed(res) > 0:
        out["mensaje"] = f"✅ Lucky Day al día ({_rows_parsed(res)} sorteos verificados, sin cambios nuevos)."
        out["status"] = "no_new"
    else:
        out["mensaje"] = res.get("message") or "Resultados actualizados."
    out["message"] = out["mensaje"]
    return out


def actualizar_lucky_day_lotto() -> dict:
    """
    Cadena dedicada Lucky Day Lotto:
    1 Illinois DBG → 2 Results Hub → 3 LotteryUSA → 4 LotteryPost →
    5 IllinoisLotteryNumbers → 6 Lottery.net → caché JSON → BD
    """
    from scrapers import lucky_day_sources as lds

    sources_tried: list[dict] = []
    errors: list[str] = []

    logger.info("%s === Lucky Day Lotto — inicio (7 fuentes) ===", LOG)

    for fuente_key, fn_name, _label in SOURCE_CHAIN:
        logger.info("%s Lucky Day — probando %s", LOG, SOURCE_LABELS.get(fuente_key, fuente_key))
        t0 = time.monotonic()
        try:
            fn = getattr(lds, fn_name)
            res = fn()
            res["elapsed"] = round(time.monotonic() - t0, 2)
            _record(sources_tried, fuente_key, res)
            if _source_ok(res):
                return _success(res, fuente_key=fuente_key, sources_tried=sources_tried)
            msg = res.get("message") or res.get("error") or f"{fuente_key} sin datos"
            errors.append(msg)
            if res.get("errors"):
                errors.extend(res["errors"][:2])
        except Exception as exc:
            logger.exception("%s Lucky Day %s error", LOG, fuente_key)
            errors.append(str(exc))

    logger.info("%s Lucky Day — probando caché JSON", LOG)
    try:
        cached = _import_lucky_day_cache()
        _record(sources_tried, "cache_json", cached)
        if cached.get("ok") and _saved(cached):
            return _success(cached, fuente_key="cache_json", sources_tried=sources_tried, cache=True)
    except Exception as exc:
        errors.append(str(exc))

    saved_db = _count_lucky_day_db()
    if saved_db > 0:
        _log_fuente("Cache Local", {"imported": 0, "updated": 0, "rows_parsed": saved_db})
        return {
            "ok": True,
            "pais": "US",
            "parser": "lucky_day_multi",
            "fuente": "database",
            "fuente_label": "Cache Local",
            "fuente_usada": "Cache Local",
            "warning": True,
            "cache": True,
            "used_db_fallback": True,
            "saved_count": saved_db,
            "imported": 0,
            "updated": 0,
            "sources_tried": sources_tried,
            "errors": errors[:10],
            "mensaje": "⚠️ No se pudo actualizar en vivo. Se mantienen los últimos resultados guardados.",
            "message": "⚠️ No se pudo actualizar en vivo. Se mantienen los últimos resultados guardados.",
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
