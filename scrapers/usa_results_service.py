"""
Orquestador resultados USA — 3 fuentes + caché + BD.
Illinois → LotteryUSA → LotteryPost → caché JSON → BD.
Nunca borra resultados existentes.
"""
from __future__ import annotations

import logging
import time

from models import count_results_for_lottery, get_all_lotteries, get_max_draw_date

logger = logging.getLogger(__name__)
LOG = "[USA SCRAPER]"

FALLBACK_LABELS = {
    "lotteryusa": "LotteryUSA",
    "lotterypost": "LotteryPost",
}


def _count_usa_saved(lottery_name: str | None = None, state: str = "Illinois") -> int:
    if lottery_name:
        for lot in get_all_lotteries(active_only=True):
            if lot.get("country") != "USA":
                continue
            if lot["name"].lower() != lottery_name.lower():
                continue
            if state and (lot.get("state") or "").lower() != state.lower():
                continue
            return count_results_for_lottery(lot["id"])
        return 0
    return sum(
        count_results_for_lottery(l["id"])
        for l in get_all_lotteries(active_only=True)
        if l.get("country") == "USA"
    )


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


def _source_saved(res: dict) -> bool:
    return bool(res) and (int(res.get("imported") or 0) + int(res.get("updated") or 0)) > 0


def _record_try(sources_tried: list, fuente: str, res: dict, url: str = "") -> None:
    sources_tried.append({
        "fuente": fuente,
        "ok": bool(res.get("ok")),
        "status_code": res.get("status_code"),
        "elapsed": res.get("elapsed"),
        "sorteos": res.get("rows_parsed") or res.get("count") or 0,
        "imported": res.get("imported", 0),
        "updated": res.get("updated", 0),
        "error": (res.get("errors") or [res.get("message") or res.get("error")])[0]
        if not res.get("ok")
        else None,
        "url": url or res.get("url") or res.get("hub_url") or "",
    })


def _import_from_json_cache(lottery_name: str | None = None) -> dict:
    from scrapers.cache.usa_results_cache import load_results_snapshot
    from services.resultados.illinois_scraper import _import_rows_grouped

    snap = load_results_snapshot()
    rows = snap.get("resultados") or []
    if lottery_name:
        rows = [r for r in rows if (r.get("lottery_name") or "").lower() == lottery_name.lower()]
    if not rows:
        return {"ok": False, "message": snap.get("message", "Sin caché JSON")}

    imported, updated, errors, _ = _import_rows_grouped(rows)
    fuente = snap.get("fuente") or "cache"
    return {
        "ok": True,
        "imported": imported,
        "updated": updated,
        "errors": errors,
        "fuente": fuente,
        "cache": True,
        "cache_used": True,
        "rows_parsed": len(rows),
        "fecha": snap.get("fecha"),
        "saved": imported + updated,
        "message": f"Caché local ({fuente}): {imported} nuevos, {updated} actualizados.",
    }


def _db_fallback(lottery_name: str | None, state: str, errors: list, sources_tried: list) -> dict:
    saved = _count_usa_saved(lottery_name, state)
    if saved <= 0:
        return {
            "ok": False,
            "pais": "US",
            "imported": 0,
            "updated": 0,
            "errors": errors,
            "sources_tried": sources_tried,
            "message": errors[0] if errors else "No hay resultados USA guardados.",
            "mensaje": errors[0] if errors else "No hay resultados USA guardados.",
        }
    logger.info("%s usando BD | registros=%s", LOG, saved)
    msg = "Mostrando resultados guardados (última actualización en BD)."
    return {
        "ok": True,
        "status": "cached_fallback",
        "pais": "US",
        "parser": "usa_multi",
        "fuente": "database",
        "used_db_fallback": True,
        "cache": True,
        "cache_used": True,
        "warning": True,
        "saved_count": saved,
        "imported": 0,
        "updated": 0,
        "cantidad_resultados": saved,
        "errors": errors[:10],
        "sources_tried": sources_tried,
        "message": msg,
        "mensaje": msg,
    }


def _normalize_success(
    res: dict,
    *,
    fuente: str,
    warning: bool = False,
    cache: bool = False,
    fallback_fuente: str | None = None,
) -> dict:
    imported = int(res.get("imported") or 0)
    updated = int(res.get("updated") or 0)
    rows_n = int(res.get("rows_parsed") or res.get("count") or (imported + updated))
    out = {
        **res,
        "ok": True,
        "pais": "US",
        "parser": "usa_multi",
        "fuente": fuente,
        "imported": imported,
        "updated": updated,
        "cantidad_resultados": rows_n or _count_usa_saved(),
        "warning": warning or bool(res.get("partial")),
        "cache": cache or bool(res.get("from_cache") or res.get("cache_used")),
        "cache_used": cache or bool(res.get("from_cache") or res.get("cache_used")),
    }
    if fallback_fuente:
        label = FALLBACK_LABELS.get(fallback_fuente, fallback_fuente)
        out["mensaje"] = f"Fuente principal falló. Se usó {label}."
        out["message"] = out["mensaje"]
        out["warning"] = True
    elif cache and out.get("cache_used"):
        out["mensaje"] = "Mostrando resultados guardados (caché local)."
        out["message"] = out["mensaje"]
        out["warning"] = True
    elif warning:
        out["mensaje"] = res.get("mensaje") or res.get("message") or "Actualizado con fuente alternativa."
        out["message"] = out["mensaje"]
    else:
        out["mensaje"] = res.get("mensaje") or res.get("message") or "Resultados actualizados correctamente"
        out["message"] = out["mensaje"]
    return out


def _persist_meta(result: dict, sources_tried: list) -> None:
    from scrapers.cache.usa_meta import save_last_run

    try:
        save_last_run(
            fuente=result.get("fuente", "unknown"),
            status=result.get("status") or ("ok" if result.get("ok") else "error"),
            cantidad_resultados=int(
                result.get("cantidad_resultados")
                or result.get("saved_count")
                or result.get("rows_parsed")
                or _count_usa_saved()
            ),
            imported=int(result.get("imported") or 0),
            updated=int(result.get("updated") or 0),
            sources_tried=sources_tried,
            url=result.get("url") or result.get("hub_url") or "",
            warning=bool(result.get("warning")),
            cache_used=bool(result.get("cache_used")),
        )
    except Exception as exc:
        logger.warning("%s No se pudo guardar usa_last_run.json: %s", LOG, exc)


def _run_illinois(lottery_name: str | None, refresh_all: bool) -> dict:
    t0 = time.monotonic()
    try:
        if refresh_all or not lottery_name:
            from scrapers.illinois_scraper import import_illinois_results_hub
            res = import_illinois_results_hub()
        else:
            from scrapers.illinois_scraper import import_illinois_lottery_now
            res = import_illinois_lottery_now(lottery_name)
        res["elapsed"] = round(time.monotonic() - t0, 2)
        res.setdefault("url", res.get("hub_url"))
        logger.info(
            "%s IllinoisLottery | ok=%s | imported=%s | updated=%s | from_cache=%s | status_code=%s | tiempo=%ss",
            LOG,
            res.get("ok"),
            res.get("imported", 0),
            res.get("updated", 0),
            res.get("from_cache"),
            res.get("status_code"),
            res.get("elapsed"),
        )
        return res
    except Exception as exc:
        logger.exception("%s IllinoisLottery excepción completa", LOG)
        return {
            "ok": False,
            "message": str(exc),
            "errors": [str(exc)],
            "elapsed": round(time.monotonic() - t0, 2),
        }


def _save_snapshot_from_rows(rows: list[dict], fuente: str, url: str) -> None:
    if not rows:
        return
    try:
        from scrapers.cache.usa_results_cache import save_results_snapshot
        save_results_snapshot(rows, fuente=fuente, url=url)
    except Exception as exc:
        logger.warning("%s snapshot error: %s", LOG, exc)


def _try_fallback_source(fuente: str, loteria: str | None, sources_tried: list) -> dict | None:
    if fuente == "lotteryusa":
        from scrapers.lotteryusa_scraper import import_lotteryusa_results
        res = import_lotteryusa_results(loteria)
    elif fuente == "lotterypost":
        from scrapers.lotterypost_scraper import import_lotterypost_results
        res = import_lotterypost_results(loteria)
    else:
        return None

    _record_try(sources_tried, fuente, res)
    if res.get("ok"):
        logger.info(
            "%s %s OK | imported=%s | updated=%s | sorteos=%s",
            LOG,
            fuente,
            res.get("imported", 0),
            res.get("updated", 0),
            res.get("rows_parsed", 0),
        )
        return res
    err = res.get("message") or (res.get("errors") or ["falló"])[0]
    logger.warning("%s %s falló | %s", LOG, fuente, err)
    return None


def actualizar_resultados_usa_profesional(
    loteria: str | None = None,
    *,
    state: str = "Illinois",
    days: int = 30,
    refresh_all: bool = True,
) -> dict:
    del days
    errors: list[str] = []
    sources_tried: list[dict] = []
    logger.info("%s === Inicio actualización USA | lotería=%s ===", LOG, loteria or "TODAS")

    # 1 — Illinois Lottery (oficial)
    illinois = _run_illinois(loteria, refresh_all)
    _record_try(sources_tried, "illinoislottery", illinois, "https://www.illinoislottery.com/results-hub")

    if illinois.get("ok") and _illinois_live_ok(illinois):
        saved_il = _source_saved(illinois)
        if saved_il or (not loteria and illinois.get("status") == "no_new"):
            result = _normalize_success(
                illinois,
                fuente="illinoislottery",
                warning=bool(illinois.get("partial")),
            )
            result["sources_tried"] = sources_tried
            _persist_meta(result, sources_tried)
            return result
        if loteria:
            logger.info(
                "%s Illinois sin datos nuevos para %s; probando fallback",
                LOG,
                loteria,
            )
            errors.append(illinois.get("message") or f"Sin datos Illinois para {loteria}")

    if not illinois.get("ok"):
        errors.append(illinois.get("message") or "Illinois Lottery falló")
    elif not _illinois_live_ok(illinois):
        errors.append(illinois.get("message") or "Illinois sin respuesta en vivo (caché/bloqueo)")

    # 2 — LotteryUSA
    logger.info("%s Fallback 2/3: LotteryUSA", LOG)
    usa = _try_fallback_source("lotteryusa", loteria, sources_tried)
    if usa:
        result = _normalize_success(usa, fuente="lotteryusa", fallback_fuente="lotteryusa")
        result["sources_tried"] = sources_tried
        _persist_meta(result, sources_tried)
        return result

    # 3 — LotteryPost
    logger.info("%s Fallback 3/3: LotteryPost", LOG)
    lp = _try_fallback_source("lotterypost", loteria, sources_tried)
    if lp:
        result = _normalize_success(lp, fuente="lotterypost", fallback_fuente="lotterypost")
        result["sources_tried"] = sources_tried
        _persist_meta(result, sources_tried)
        return result

    # 4 — Caché JSON
    logger.info("%s Fallback: caché JSON local", LOG)
    try:
        cached = _import_from_json_cache(loteria)
        _record_try(sources_tried, "cache_json", cached)
        if cached.get("ok") and int(cached.get("saved") or 0) > 0:
            result = _normalize_success(cached, fuente=cached.get("fuente", "cache"), cache=True)
            result["sources_tried"] = sources_tried
            _persist_meta(result, sources_tried)
            return result
    except Exception as exc:
        logger.exception("%s Error caché JSON", LOG)
        errors.append(str(exc))

    # Illinois hub cache con datos en BD
    if illinois.get("ok"):
        saved_db = _count_usa_saved(loteria, state)
        if saved_db > 0:
            result = _normalize_success(
                {**illinois, "saved_count": saved_db, "cantidad_resultados": saved_db},
                fuente="illinoislottery",
                cache=True,
            )
            result["sources_tried"] = sources_tried
            _persist_meta(result, sources_tried)
            return result

    # 5 — BD (nunca error si hay datos)
    logger.error("%s Todas las fuentes fallaron | intentos=%s", LOG, len(sources_tried))
    result = _db_fallback(loteria, state, errors, sources_tried)
    _persist_meta(result, sources_tried)
    return result
