"""
Actualización de resultados — USA y RD/DO totalmente separados.
Illinois NUNCA se ejecuta cuando país = DO / RD.
"""
from __future__ import annotations

import logging

from models import count_results_for_lottery, get_all_lotteries, get_max_draw_date
from services.lottery_normalize import find_lottery_in_list

logger = logging.getLogger(__name__)

LOG_RD = "[RD]"
LOG_USA = "[USA]"
ALT_RD_MSG = "No se pudo actualizar desde una fuente, se usó fuente alternativa."


def es_pais_do(pais: str) -> bool:
    p = (pais or "").strip().upper()
    if p in ("RD", "DO", "DOM"):
        return True
    if "DOMINIC" in p or p == "REPUBLICA DOMINICANA":
        return True
    return False


def es_pais_us(pais: str) -> bool:
    p = (pais or "").strip().upper()
    return p in ("USA", "US", "EEUU")


def _find_rd_lottery(lottery_name: str):
    return find_lottery_in_list(get_all_lotteries(), lottery_name, country="RD")


def _find_usa_lottery(lottery_name: str, state: str = "Illinois"):
    for lot in get_all_lotteries():
        if lot.get("country") != "USA":
            continue
        if lot["name"].lower() != (lottery_name or "").lower():
            continue
        if state and (lot.get("state") or "").lower() != state.lower():
            continue
        return lot
    return None


def _rd_respuesta_cache(lot=None, lottery_name: str = "", parser: str = "leidsa") -> dict | None:
    """Si hay datos en BD, no fallar ni borrar nada."""
    from models import get_leidsa_history_from_db

    saved = 0
    if lot and (lot.get("type") or "").lower().startswith("leidsa"):
        saved = len(get_leidsa_history_from_db(limit_days=90))
    elif lot:
        saved = count_results_for_lottery(lot["id"])
    elif lottery_name:
        lot = _find_rd_lottery(lottery_name)
        if lot:
            if (lot.get("type") or "").lower().startswith("leidsa"):
                saved = len(get_leidsa_history_from_db(limit_days=90))
            else:
                saved = count_results_for_lottery(lot["id"])

    if saved <= 0:
        return None

    lottery_id = lot["id"] if lot else None
    return {
        "ok": True,
        "status": "cached_fallback",
        "pais": "DO",
        "parser": parser,
        "used_db_fallback": True,
        "saved_count": saved,
        "imported": 0,
        "updated": 0,
        "lottery_id": lottery_id,
        "latest_date": get_max_draw_date(lottery_id) if lottery_id else None,
        "message": "⚠️ No se pudo actualizar en vivo; se mantienen los resultados guardados en BD.",
        "errors": [],
        "live_failed": True,
    }


def actualizar_resultados_rd(
    loteria: str | None = None,
    *,
    days: int = 30,
    refresh_all: bool = False,
) -> dict:
    """
    RD multi-fuente: Conectate → LD → LotDom → EnLoteria → caché BD.
    LEIDSA mantiene scraper oficial + mismos fallbacks.
    """
    days = int(days or 30)
    logger.info("%s Actualizando resultados RD — lotería=%s", LOG_RD, loteria or "TODAS")

    from services.rd_results_service import actualizar_rd_loteria, actualizar_rd_todas

    if refresh_all or not loteria:
        logger.info("%s Historial completo RD (%s días) — multi-fuente", LOG_RD, days)
        return actualizar_rd_todas(days=days)

    lot = _find_rd_lottery(loteria)
    if not lot:
        return {
            "ok": False,
            "pais": "DO",
            "message": f"Lotería RD no encontrada: {loteria}",
        }

    result = actualizar_rd_loteria(lot["name"], days=days)
    if result.get("ok"):
        return _finalize_rd_scrape(lot, result, days)

    fb = _rd_respuesta_cache(lot, parser=result.get("parser") or "rd_multi")
    if fb:
        fb["sources_tried"] = result.get("sources_tried", [])
        fb["errors"] = result.get("errors", [])
        err_detail = result.get("error_detail") or "; ".join(result.get("errors", [])[:5])
        fb["error_detail"] = err_detail
        fb["mensaje"] = err_detail or (ALT_RD_MSG + " Se mantienen resultados guardados.")
        fb["message"] = fb["mensaje"]
        fb["warning"] = True
        fb["live_failed"] = True
        return fb
    return result


def _finalize_rd_scrape(lot: dict, scrape: dict, days: int) -> dict:
    lottery_id = lot["id"]
    imported = scrape.get("imported", scrape.get("inserted", 0))
    updated = scrape.get("updated", 0)
    latest_date = get_max_draw_date(lottery_id)
    saved = imported + updated

    base = {
        **{k: v for k, v in scrape.items() if k not in ("message", "mensaje")},
        "ok": True,
        "pais": "DO",
        "lottery_id": lottery_id,
        "imported": imported,
        "updated": updated,
        "days": days,
        "latest_date": latest_date,
        "ultima_fecha": latest_date,
        "parser": scrape.get("parser"),
        "errors": scrape.get("errors", []),
        "fuente_usada": scrape.get("fuente_usada") or scrape.get("fuente_label"),
        "sources_tried": scrape.get("sources_tried", []),
        "warning": scrape.get("warning", False),
        "tiempo": scrape.get("tiempo") or scrape.get("elapsed_total") or scrape.get("elapsed"),
        "elapsed_total": scrape.get("elapsed_total") or scrape.get("elapsed"),
        "cache": bool(scrape.get("cache") or scrape.get("used_db_fallback")),
        "live_failed": bool(scrape.get("live_failed")),
    }

    fuente_label = base["fuente_usada"] or "RD"
    tiempo = base.get("tiempo")

    if scrape.get("used_db_fallback") or scrape.get("status") == "cached_fallback":
        base["status"] = "cached_fallback"
        latest = latest_date or scrape.get("latest_date") or "desconocida"
        base["message"] = scrape.get("mensaje") or scrape.get("message") or (
            f"⚠️ Todas las fuentes fallaron. Última fecha en BD: {latest}."
        )
    elif saved == 0:
        base["status"] = "no_new"
        base["message"] = scrape.get("mensaje") or scrape.get("message") or "No hay resultados nuevos en el rango"
    else:
        base["status"] = "updated"
        tiempo_txt = f"{tiempo}s" if tiempo else "—"
        if scrape.get("warning"):
            base["message"] = (
                f"✅ Fuente: {fuente_label} · Tiempo: {tiempo_txt} · "
                f"Nuevos: {imported} · Actualizados: {updated} · Última fecha: {latest_date or '—'}. "
                f"{ALT_RD_MSG}"
            )
        else:
            base["message"] = (
                f"✅ Fuente: {fuente_label} · Tiempo: {tiempo_txt} · "
                f"Nuevos: {imported} · Actualizados: {updated} · Última fecha: {latest_date or '—'}"
            )
    base["mensaje"] = base["message"]
    return base


def actualizar_resultados_usa(
    loteria: str | None = None,
    *,
    state: str = "Illinois",
    days: int = 30,
    refresh_all: bool = True,
) -> dict:
    """USA: Illinois → LotteryUSA → caché JSON → BD. Sin LEIDSA ni Conectate."""
    logger.info("%s Actualizando resultados USA — lotería=%s", LOG_USA, loteria or "TODAS")

    try:
        from scrapers.usa_results_service import actualizar_resultados_usa_profesional

        result = actualizar_resultados_usa_profesional(
            loteria,
            state=state,
            days=days,
            refresh_all=refresh_all or not loteria,
        )
    except Exception as exc:
        logger.exception("%s USA multi-fuente error", LOG_USA)
        result = {"ok": False, "message": str(exc), "errors": [str(exc)]}
        saved = sum(
            count_results_for_lottery(l["id"])
            for l in get_all_lotteries(active_only=True)
            if l.get("country") == "USA"
        )
        if saved > 0:
            result = {
                "ok": True,
                "status": "cached_fallback",
                "used_db_fallback": True,
                "saved_count": saved,
                "imported": 0,
                "updated": 0,
                "message": "Mostrando resultados guardados.",
                "mensaje": "Mostrando resultados guardados.",
                "errors": [str(exc)],
            }

    result.setdefault("pais", "US")
    result.setdefault("parser", "usa_multi")
    return result
