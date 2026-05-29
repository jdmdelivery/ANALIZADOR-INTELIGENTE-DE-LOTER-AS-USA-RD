"""
Orquestador profesional resultados USA:
Illinois Lottery (principal) → LotteryUSA (fallback) → caché JSON → BD.
Nunca borra resultados existentes.
"""
from __future__ import annotations

import logging
import time

from models import count_results_for_lottery, get_all_lotteries, get_max_draw_date

logger = logging.getLogger(__name__)
LOG = "[USA SCRAPER]"


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
    """Illinois respondió en vivo (no solo caché HTML del hub)."""
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


def _illinois_saved(res: dict) -> bool:
    return bool(res) and (int(res.get("imported") or 0) + int(res.get("updated") or 0)) > 0


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
    saved = imported + updated
    fuente = snap.get("fuente") or "cache"
    return {
        "ok": saved > 0 or bool(rows),
        "imported": imported,
        "updated": updated,
        "errors": errors,
        "fuente": fuente,
        "cache": True,
        "cache_used": True,
        "from_json_cache": True,
        "saved": saved,
        "message": (
            f"Caché local ({fuente}): {imported} nuevos, {updated} actualizados."
            if saved
            else "Caché local disponible; sin cambios en BD."
        ),
    }


def _db_fallback(lottery_name: str | None, state: str, errors: list) -> dict:
    saved = _count_usa_saved(lottery_name, state)
    if saved <= 0:
        return {
            "ok": False,
            "pais": "US",
            "imported": 0,
            "updated": 0,
            "errors": errors,
            "message": errors[0] if errors else "No hay resultados USA guardados.",
            "mensaje": errors[0] if errors else "No hay resultados USA guardados.",
        }
    logger.info("%s usando BD | registros=%s", LOG, saved)
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
        "errors": errors[:10],
        "message": "No se pudo actualizar ahora; se muestran resultados guardados.",
        "mensaje": "No se pudo actualizar ahora; se muestran resultados guardados.",
    }


def _normalize_success(
    res: dict,
    *,
    fuente: str,
    warning: bool = False,
    cache: bool = False,
    primary_failed: bool = False,
) -> dict:
    imported = int(res.get("imported") or 0)
    updated = int(res.get("updated") or 0)
    out = {
        **res,
        "ok": True,
        "pais": "US",
        "parser": res.get("parser") or "usa_multi",
        "fuente": fuente,
        "imported": imported,
        "updated": updated,
        "warning": warning or bool(res.get("partial")),
        "cache": cache or bool(res.get("from_cache")),
        "cache_used": cache or bool(res.get("from_cache") or res.get("cache_used")),
    }
    if primary_failed:
        out["warning"] = True
        out["mensaje"] = "Fuente principal falló. Se usó LotteryUSA."
        out["message"] = out["mensaje"]
    elif cache and not _illinois_live_ok(res):
        out["mensaje"] = "No se pudo actualizar ahora; se muestran resultados guardados."
        out["message"] = out["mensaje"]
    elif warning:
        out["mensaje"] = res.get("mensaje") or res.get("message") or (
            "Fuente principal falló. Se usó LotteryUSA."
        )
        out["message"] = out["mensaje"]
    else:
        out["mensaje"] = res.get("mensaje") or res.get("message") or "Resultados actualizados correctamente"
        out["message"] = out["mensaje"]
    return out


def _run_illinois(lottery_name: str | None, refresh_all: bool) -> dict:
    t0 = time.monotonic()
    try:
        if refresh_all or not lottery_name:
            from scrapers.illinois_scraper import import_illinois_results_hub

            res = import_illinois_results_hub()
        else:
            from scrapers.illinois_scraper import import_illinois_lottery_now

            res = import_illinois_lottery_now(lottery_name)
        elapsed = round(time.monotonic() - t0, 2)
        logger.info(
            "%s IllinoisLottery fin ok=%s imported=%s updated=%s from_cache=%s tiempo=%ss",
            LOG,
            res.get("ok"),
            res.get("imported", 0),
            res.get("updated", 0),
            res.get("from_cache"),
            elapsed,
        )
        if _illinois_live_ok(res) and (res.get("imported", 0) + res.get("updated", 0) >= 0):
            rows_n = res.get("rows_parsed")
            if rows_n is None and res.get("ok"):
                pass
        return res
    except Exception as exc:
        logger.exception("%s IllinoisLottery falló | %s", LOG, exc)
        return {"ok": False, "message": str(exc), "errors": [str(exc)]}


def _save_illinois_snapshot_if_rows(res: dict) -> None:
    """Guarda snapshot JSON tras import Illinois exitoso."""
    try:
        from scrapers.illinois_scraper import IllinoisResultsHubScraper, parse_results_hub_html
        from scrapers.cache.usa_results_cache import save_results_snapshot

        scraper = IllinoisResultsHubScraper()
        page = scraper.fetch_results_hub(allow_cache=True)
        if page.get("ok") and page.get("html"):
            rows = parse_results_hub_html(page["html"])
            if rows:
                save_results_snapshot(
                    rows,
                    fuente="illinoislottery",
                    url=page.get("url", ""),
                )
    except Exception as exc:
        logger.warning("%s No se pudo guardar snapshot Illinois: %s", LOG, exc)


def actualizar_resultados_usa_profesional(
    loteria: str | None = None,
    *,
    state: str = "Illinois",
    days: int = 30,
    refresh_all: bool = True,
) -> dict:
    """
    Flujo: Illinois → LotteryUSA → caché JSON → BD.
    Nunca borra datos existentes.
    """
    del days  # reservado; hub trae últimos sorteos
    errors: list[str] = []
    logger.info("%s Inicio actualización USA | lotería=%s", LOG, loteria or "TODAS")

    illinois = _run_illinois(loteria, refresh_all)

    if illinois.get("ok") and _illinois_live_ok(illinois):
        _save_illinois_snapshot_if_rows(illinois)
        return _normalize_success(
            illinois,
            fuente="illinoislottery",
            warning=bool(illinois.get("partial") or illinois.get("from_cache")),
        )

    if illinois and not illinois.get("ok"):
        err = illinois.get("message") or "Illinois falló"
        errors.append(err)
        logger.warning("%s IllinoisLottery falló | %s", LOG, err)
    elif illinois.get("ok") and (illinois.get("from_cache") or not _illinois_live_ok(illinois)):
        logger.warning(
            "%s IllinoisLottery sin live (from_cache=%s status=%s) — probando fallback",
            LOG,
            illinois.get("from_cache"),
            illinois.get("status"),
        )
        if illinois.get("message"):
            errors.append(str(illinois["message"]))

    # 2 — LotteryUSA fallback
    logger.info("%s Intentando LotteryUSA fallback", LOG)
    try:
        from scrapers.lotteryusa_scraper import import_lotteryusa_results

        usa = import_lotteryusa_results(loteria)
        if usa.get("ok") and (_illinois_saved(usa) or usa.get("status") == "no_new"):
            return _normalize_success(
                usa,
                fuente="lotteryusa",
                warning=True,
                primary_failed=True,
            )
        if usa.get("ok"):
            return _normalize_success(usa, fuente="lotteryusa", warning=True, primary_failed=True)
        if usa.get("message"):
            errors.append(usa["message"])
            logger.warning("%s LotteryUSA falló | %s", LOG, usa["message"])
    except Exception as exc:
        logger.exception("%s LotteryUSA excepción", LOG)
        errors.append(str(exc))

    # 3 — Caché JSON de resultados parseados
    logger.info("%s Intentando caché JSON local", LOG)
    try:
        cached = _import_from_json_cache(loteria)
        if cached.get("ok") and int(cached.get("saved") or 0) > 0:
            logger.info("%s usando cache local | imported=%s", LOG, cached.get("imported"))
            return _normalize_success(
                cached,
                fuente=cached.get("fuente", "cache"),
                warning=True,
                cache=True,
            )
        if cached.get("ok"):
            logger.info("%s cache JSON sin cambios BD", LOG)
    except Exception as exc:
        logger.warning("%s Error leyendo caché JSON: %s", LOG, exc)

    # Illinois con caché hub pero datos en BD — aceptar como warning
    if illinois.get("ok") and (illinois.get("from_cache") or illinois.get("status") == "no_new"):
        saved_db = _count_usa_saved(loteria, state)
        if saved_db > 0:
            return _normalize_success(
                {**illinois, "saved_count": saved_db},
                fuente="illinoislottery",
                warning=True,
                cache=True,
            )

    # 4 — BD
    logger.error("%s ambas fuentes fallaron; fallback BD", LOG)
    return _db_fallback(loteria, state, errors)
