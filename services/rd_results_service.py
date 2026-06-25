"""
Orquestador multi-fuente RD — Conectate → LD → LotDom → EnLoteria → caché BD.
No afecta loterías USA.
"""
from __future__ import annotations

import logging
import time

from models import count_results_for_lottery, get_all_lotteries, get_max_draw_date
from services.lottery_normalize import find_lottery_in_list, normalize_lottery_name
from services.rd_lottery_config import get_rd_lottery_config, iter_enabled_conectate_configs
from services.rd_update_log import log_rd_update

logger = logging.getLogger(__name__)
LOG = "[RD]"

SOURCE_LABELS = {
    "conectate": "Conectate.com.do",
    "conectate_primary": "Conectate.com.do",
    "loteriasdominicanas": "LoteriasDominicanas.com",
    "loteriadominicana": "LoteriaDominicana.com.do",
    "enloteria": "EnLoteria.com",
    "leidsa": "LEIDSA.com",
    "cache": "Cache Local",
    "database": "Cache Local",
}

ALT_MESSAGE = "No se pudo actualizar desde una fuente, se usó fuente alternativa."

FALLBACK_CHAIN = [
    ("conectate", "import_conectate_hub"),
    ("loteriasdominicanas", "import_loteriasdominicanas"),
    ("loteriadominicana", "import_loteriadominicana"),
    ("enloteria", "import_enloteria"),
]


def _saved(res: dict) -> bool:
    return int(res.get("imported") or 0) + int(res.get("updated") or 0) > 0


def _rows_found(res: dict) -> int:
    return int(
        res.get("rows_found")
        or res.get("rows_saved")
        or res.get("rows_parsed")
        or res.get("results_found")
        or 0
    )


def _needs_fallback(res: dict) -> bool:
    if not res or not res.get("ok"):
        return True
    if _saved(res):
        return False
    if _rows_found(res) > 0:
        return False
    return True


def _record(sources: list, key: str, res: dict, *, lottery_name: str = "") -> None:
    err = None
    if not res.get("ok"):
        err = (res.get("errors") or [res.get("message") or res.get("error")])[0]
    entry = {
        "fuente": key,
        "fuente_label": res.get("fuente_label") or SOURCE_LABELS.get(key, key),
        "ok": bool(res.get("ok")),
        "status_code": res.get("status_code"),
        "elapsed": res.get("elapsed"),
        "sorteos": _rows_found(res),
        "imported": res.get("imported", 0),
        "updated": res.get("updated", 0),
        "error": err,
        "url": res.get("url") or "",
        "parser": res.get("parser"),
    }
    sources.append(entry)
    log_rd_update(
        fuente=entry["fuente_label"],
        url=entry["url"],
        status=entry.get("status_code") or ("ok" if entry["ok"] else "error"),
        tiempo=entry.get("elapsed") or "",
        loteria=lottery_name,
        resultados=entry["sorteos"],
        guardados=int(entry["imported"] or 0) + int(entry["updated"] or 0),
        actualizados=entry["updated"],
        error=err,
    )


def _log_result(label: str, lottery_name: str, res: dict) -> None:
    saved = _saved(res)
    rows = _rows_found(res)
    logger.info(
        "%s fuente=%s | lotería=%s | guardados=%s | sorteos=%s | ok=%s",
        LOG,
        label,
        lottery_name,
        int(res.get("imported") or 0) + int(res.get("updated") or 0),
        rows,
        res.get("ok"),
    )
    for row in res.get("saved_rows") or []:
        logger.info(
            "%s números | lotería=%s | fecha=%s | tanda=%s | nums=%s",
            LOG,
            row.get("lottery_name"),
            row.get("draw_date"),
            row.get("draw_name"),
            row.get("numbers"),
        )


def _cache_response(
    lot: dict | None,
    parser: str = "rd_multi",
    errors: list[str] | None = None,
) -> dict | None:
    if not lot:
        return None
    saved = count_results_for_lottery(lot["id"])
    if saved <= 0:
        return None
    latest = get_max_draw_date(lot["id"])
    err_text = "; ".join(str(e) for e in (errors or [])[:5] if e)
    if not err_text:
        err_text = "Todas las fuentes en vivo fallaron sin filas nuevas."
    msg = (
        f"⚠️ Actualización en vivo falló (última fecha en BD: {latest or 'desconocida'}). "
        f"{err_text}"
    )
    return {
        "ok": True,
        "status": "cached_fallback",
        "pais": "DO",
        "parser": parser,
        "used_db_fallback": True,
        "live_failed": True,
        "cache": True,
        "fuente": "database",
        "fuente_label": "Cache Local",
        "fuente_usada": "Cache Local",
        "saved_count": saved,
        "imported": 0,
        "updated": 0,
        "lottery_id": lot["id"],
        "latest_date": latest,
        "message": msg,
        "mensaje": msg,
        "errors": list(errors or []),
        "error_detail": err_text,
    }


def _success(
    res: dict,
    *,
    fuente_key: str,
    lottery_name: str,
    sources_tried: list,
    warning: bool = False,
    cache: bool = False,
) -> dict:
    label = res.get("fuente_label") or SOURCE_LABELS.get(fuente_key, fuente_key)
    _log_result(label, lottery_name, res)
    out = {
        **res,
        "ok": True,
        "pais": "DO",
        "parser": res.get("parser") or "rd_multi",
        "fuente": fuente_key,
        "fuente_label": label,
        "fuente_usada": label,
        "lottery_name": lottery_name,
        "warning": warning or cache,
        "cache": cache,
        "sources_tried": sources_tried,
    }
    if cache:
        out["mensaje"] = res.get("message") or "Mostrando resultados guardados (caché local)."
    elif warning:
        out["mensaje"] = ALT_MESSAGE
        out["message"] = ALT_MESSAGE
    else:
        out["mensaje"] = res.get("message") or f"✅ {lottery_name} actualizado."
        out["message"] = out["mensaje"]
    return out


def _run_conectate_primary(lottery_name: str, days: int) -> dict:
    from services.new_lotteries import is_new_rd_lottery

    lot = find_lottery_in_list(get_all_lotteries(), lottery_name, country="RD")
    if lot and is_new_rd_lottery(lot):
        from scrapers.conectate_rd import import_conectate_lottery_bulk_style

        res = import_conectate_lottery_bulk_style(lottery_name, days_back=days)
    else:
        from scrapers.conectate_rd import import_conectate_lottery_history

        res = import_conectate_lottery_history(lottery_name, days=days)
    res["fuente"] = "conectate_primary"
    res["fuente_label"] = "Conectate.com.do"
    res["parser"] = "conectate"
    return res


def _run_fallback(fuente_key: str, fn_name: str, lottery_name: str, days: int) -> dict:
    from scrapers import rd_fallback_scrapers as fb

    fn = getattr(fb, fn_name)
    return fn(lottery_name, days)


def actualizar_rd_loteria(lottery_name: str, days: int = 30) -> dict:
    """Actualiza una lotería RD con cadena multi-fuente."""
    sources_tried: list[dict] = []
    errors: list[str] = []
    lot = find_lottery_in_list(get_all_lotteries(), lottery_name, country="RD")
    if not lot:
        return {"ok": False, "pais": "DO", "message": f"Lotería RD no encontrada: {lottery_name}"}

    db_name = lot["name"]
    lot_type = (lot.get("type") or "").lower()
    cfg = get_rd_lottery_config(db_name)
    es_leidsa = (
        lot_type.startswith("leidsa_")
        or (cfg and cfg.get("source") == "leidsa")
        or "leidsa" in (lottery_name or "").lower()
    )

    if es_leidsa:
        return actualizar_leidsa_multi(days=days, lottery_name=db_name)

    logger.info("%s === Inicio %s — multi-fuente ===", LOG, db_name)
    t0 = time.monotonic()

    # 1 — Fuente actual (Conectate scraper existente)
    try:
        primary = _run_conectate_primary(db_name, days)
        primary["elapsed"] = round(time.monotonic() - t0, 2)
        _record(sources_tried, "conectate_primary", primary, lottery_name=db_name)
        if not _needs_fallback(primary):
            return _success(primary, fuente_key="conectate", lottery_name=db_name, sources_tried=sources_tried)
        if primary.get("message"):
            errors.append(primary["message"])
    except Exception as exc:
        logger.exception("%s Conectate primary error %s", LOG, db_name)
        errors.append(str(exc))
        _record(
            sources_tried,
            "conectate_primary",
            {"ok": False, "error": str(exc), "message": str(exc)},
            lottery_name=db_name,
        )

    # 2–5 — Fallbacks
    for fuente_key, fn_name in FALLBACK_CHAIN:
        logger.info("%s %s — probando %s", LOG, db_name, SOURCE_LABELS.get(fuente_key, fuente_key))
        try:
            fb = _run_fallback(fuente_key, fn_name, db_name, days)
            _record(sources_tried, fuente_key, fb, lottery_name=db_name)
            if fb.get("ok") and (_saved(fb) or _rows_found(fb) > 0):
                return _success(
                    fb,
                    fuente_key=fuente_key,
                    lottery_name=db_name,
                    sources_tried=sources_tried,
                    warning=True,
                )
            if fb.get("message"):
                errors.append(fb["message"])
        except Exception as exc:
            logger.exception("%s fallback %s error", LOG, fuente_key)
            errors.append(str(exc))
            _record(
                sources_tried,
                fuente_key,
                {"ok": False, "error": str(exc), "message": str(exc)},
                lottery_name=db_name,
            )

    # 6 — Caché BD
    cached = _cache_response(lot, errors=errors)
    if cached:
        cached["sources_tried"] = sources_tried
        cached["errors"] = errors[:10]
        logger.info("%s %s — usando caché BD (%s registros)", LOG, db_name, cached["saved_count"])
        return cached

    logger.error("%s %s — todas las fuentes fallaron", LOG, db_name)
    return {
        "ok": False,
        "pais": "DO",
        "lottery_name": db_name,
        "sources_tried": sources_tried,
        "errors": errors,
        "error_detail": "; ".join(errors[:5]) if errors else "Todas las fuentes fallaron",
        "live_failed": True,
        "message": errors[0] if errors else f"No se pudo actualizar {db_name}",
    }


def actualizar_leidsa_multi(*, days: int = 30, lottery_name: str | None = None) -> dict:
    """LEIDSA oficial + fallbacks agregadores + caché."""
    sources_tried: list[dict] = []
    errors: list[str] = []

    logger.info("%s === LEIDSA multi-fuente ===", LOG)
    try:
        from services.leidsa_service import update_leidsa_now

        leidsa = update_leidsa_now()
        leidsa["fuente"] = "leidsa"
        leidsa["fuente_label"] = "LEIDSA.com"
        _record(sources_tried, "leidsa", leidsa)
        if leidsa.get("ok") and (_saved(leidsa) or int(leidsa.get("results_found") or 0) > 0):
            leidsa["pais"] = "DO"
            leidsa["fuente_usada"] = "LEIDSA.com"
            leidsa["sources_tried"] = sources_tried
            leidsa["mensaje"] = leidsa.get("message") or "LEIDSA actualizada."
            return leidsa
        if leidsa.get("message"):
            errors.append(leidsa["message"])
    except Exception as exc:
        logger.exception("%s LEIDSA primary error", LOG)
        errors.append(str(exc))

    target = lottery_name or "Leidsa"
    for fuente_key, fn_name in FALLBACK_CHAIN:
        try:
            fb = _run_fallback(fuente_key, fn_name, target, days)
            _record(sources_tried, fuente_key, fb)
            if fb.get("ok") and _saved(fb):
                return _success(
                    fb,
                    fuente_key=fuente_key,
                    lottery_name=target,
                    sources_tried=sources_tried,
                    warning=True,
                )
            if fb.get("message"):
                errors.append(fb["message"])
        except Exception as exc:
            errors.append(str(exc))

    lot = find_lottery_in_list(get_all_lotteries(), target, country="RD")
    cached = _cache_response(lot, parser="leidsa")
    if not cached:
        from models import get_leidsa_history_from_db

        if len(get_leidsa_history_from_db(limit_days=90)) > 0:
            cached = {
                "ok": True,
                "status": "cached_fallback",
                "pais": "DO",
                "parser": "leidsa",
                "fuente_usada": "Cache Local",
                "cache": True,
                "message": "Mostrando resultados LEIDSA guardados en BD.",
            }
    if cached:
        cached["sources_tried"] = sources_tried
        cached["mensaje"] = ALT_MESSAGE + " Se muestran datos guardados."
        cached["message"] = cached["mensaje"]
        cached["warning"] = True
        return cached

    return {
        "ok": False,
        "pais": "DO",
        "sources_tried": sources_tried,
        "errors": errors,
        "message": errors[0] if errors else "LEIDSA no respondió",
    }


def actualizar_rd_todas(days: int = 30) -> dict:
    """Historial completo RD con multi-fuente por lotería."""
    days = int(days or 30)
    total_imported = 0
    total_updated = 0
    errors: list[str] = []
    details: list[dict] = []
    dates_union: set[str] = set()
    warnings: list[str] = []

    try:
        from services.leidsa_history import fetch_all_leidsa_history

        leidsa_hist = fetch_all_leidsa_history(days=days, save=True)
        leidsa_hist["imported"] = leidsa_hist.get("inserted", 0)
        details.append({"name": "LEIDSA historial", **leidsa_hist})
        if leidsa_hist.get("ok"):
            total_imported += int(leidsa_hist.get("inserted", 0))
            total_updated += int(leidsa_hist.get("updated", 0))
    except Exception as exc:
        errors.append(f"LEIDSA historial: {exc}")

    leidsa_out = actualizar_leidsa_multi(days=days)
    details.append({"name": "LEIDSA", **leidsa_out})
    if leidsa_out.get("ok"):
        total_imported += int(leidsa_out.get("imported") or 0)
        total_updated += int(leidsa_out.get("updated") or 0)
        if leidsa_out.get("warning"):
            warnings.append("LEIDSA")
    else:
        errors.append(leidsa_out.get("message") or "LEIDSA: error")

    refreshed: set[str] = set()
    for _label, cfg in iter_enabled_conectate_configs():
        db_name = cfg["db_names"][0]
        key = normalize_lottery_name(db_name)
        if key in refreshed:
            continue
        refreshed.add(key)
        try:
            out = actualizar_rd_loteria(db_name, days=days)
            lot_row = find_lottery_in_list(get_all_lotteries(), db_name, country="RD")
            lid = lot_row["id"] if lot_row else None
            latest = get_max_draw_date(lid) if lid else None
            logger.info(
                "%s RD resumen %s | nuevos=%s | actualizados=%s | última_fecha=%s | fuente=%s",
                LOG,
                db_name,
                out.get("imported", 0),
                out.get("updated", 0),
                latest,
                out.get("fuente_usada") or out.get("fuente"),
            )
            details.append({"name": db_name, "latest_date": latest, **out})
            if out.get("ok"):
                total_imported += int(out.get("imported") or 0)
                total_updated += int(out.get("updated") or 0)
                for d in out.get("dates_found") or []:
                    dates_union.add(d)
                if out.get("warning"):
                    warnings.append(db_name)
            else:
                errors.append(f"{db_name}: {out.get('message', 'error')}")
        except Exception as exc:
            errors.append(f"{db_name}: {exc}")

    saved = total_imported + total_updated
    msg = (
        f"Historial RD: {days} días, {saved} guardados "
        f"({total_imported} nuevos, {total_updated} actualizados)."
    )
    if warnings:
        msg += f" {ALT_MESSAGE} Fuentes alternativas: {', '.join(warnings[:8])}."

    return {
        "ok": bool(saved) or any(d.get("ok") for d in details),
        "status": "updated" if saved else "no_new",
        "pais": "DO",
        "message": msg,
        "mensaje": msg,
        "imported": total_imported,
        "updated": total_updated,
        "days": days,
        "dates_found": sorted(dates_union, reverse=True)[:60],
        "errors": errors,
        "details": details,
        "warning": bool(warnings),
        "alternate_sources_used": warnings,
    }
