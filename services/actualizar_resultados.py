"""
Actualización de resultados — USA y RD/DO totalmente separados.
Illinois NUNCA se ejecuta cuando país = DO / RD.
"""
from __future__ import annotations

import logging

from models import count_results_for_lottery, get_all_lotteries, get_max_draw_date
from services.lottery_normalize import find_lottery_in_list
from services.rd_lottery_config import get_rd_lottery_config

logger = logging.getLogger(__name__)

LOG_RD = "[RD]"
LOG_USA = "[USA]"


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
    }


def actualizar_resultados_rd(
    loteria: str | None = None,
    *,
    days: int = 30,
    refresh_all: bool = False,
) -> dict:
    """
    Solo scrapers RD: LEIDSA (parser leidsa) y Conectate.
    Sin Illinois Results Hub.
    """
    days = int(days or 30)
    logger.info("%s Actualizando resultados RD — lotería=%s", LOG_RD, loteria or "TODAS")

    if refresh_all or not loteria:
        from services.history_fetch import fetch_all_rd_history

        logger.info("%s Historial completo RD (%s días)", LOG_RD, days)
        out = fetch_all_rd_history(days=days)
        out["pais"] = "DO"
        if not out.get("ok"):
            fb = _rd_respuesta_cache()
            if fb:
                fb["message"] = (
                    "⚠️ Actualización parcial; se mantienen resultados guardados en BD."
                )
                return fb
        return out

    lot = _find_rd_lottery(loteria)
    if not lot:
        return {
            "ok": False,
            "pais": "DO",
            "message": f"Lotería RD no encontrada: {loteria}",
        }

    lot_type = (lot.get("type") or "").lower()
    cfg = get_rd_lottery_config(lot["name"])
    es_leidsa = (
        lot_type.startswith("leidsa_")
        or (cfg and cfg.get("source") == "leidsa")
        or "leidsa" in (loteria or "").lower()
    )

    try:
        if es_leidsa:
            logger.info("%s Actualizando LEIDSA", LOG_RD)
            from services.leidsa_service import update_leidsa_now

            scrape = update_leidsa_now()
            parser = scrape.get("parser") or "leidsa"
            found = scrape.get("results_found") or scrape.get("games") or 0
            if isinstance(found, list):
                found = len(found)
            logger.info("%s Parser usado: %s", LOG_RD, parser)
            logger.info("%s Resultados encontrados: %s", LOG_RD, found)

            scrape["pais"] = "DO"
            scrape["parser"] = parser
            if scrape.get("ok"):
                return scrape

            fb = _rd_respuesta_cache(lot, parser="leidsa")
            if fb:
                logger.info("%s LEIDSA en vivo falló; BD tiene %s registros", LOG_RD, fb["saved_count"])
                return fb
            return scrape

        from services.history_fetch import fetch_history_for_source
        from services.new_lotteries import is_new_rd_lottery

        if is_new_rd_lottery(lot):
            from scrapers.conectate_rd import import_conectate_lottery_bulk_style

            logger.info("%s Conectate (nueva) — %s", LOG_RD, lot["name"])
            scrape = import_conectate_lottery_bulk_style(lot["name"], days_back=days)
        else:
            logger.info("%s Conectate — %s", LOG_RD, lot["name"])
            scrape = fetch_history_for_source(
                "conectate", days=days, lottery_name=lot["name"]
            )

        scrape["pais"] = "DO"
        scrape["parser"] = scrape.get("parser") or "conectate"

        if scrape.get("ok"):
            logger.info(
                "%s Parser usado: %s — importados=%s",
                LOG_RD,
                scrape["parser"],
                scrape.get("imported", scrape.get("inserted", 0)),
            )
            return _finalize_rd_scrape(lot, scrape, days)

        fb = _rd_respuesta_cache(lot, parser="conectate")
        if fb:
            return fb
        return scrape

    except Exception as exc:
        logger.exception("%s Error actualizando %s", LOG_RD, loteria)
        fb = _rd_respuesta_cache(lot)
        if fb:
            fb["errors"] = [str(exc)]
            return fb
        return {
            "ok": False,
            "pais": "DO",
            "message": f"Error temporal en {loteria}: {exc}",
            "errors": [str(exc)],
        }


def _finalize_rd_scrape(lot: dict, scrape: dict, days: int) -> dict:
    lottery_id = lot["id"]
    imported = scrape.get("imported", scrape.get("inserted", 0))
    updated = scrape.get("updated", 0)
    latest_date = get_max_draw_date(lottery_id)
    saved = imported + updated

    base = {
        "ok": True,
        "pais": "DO",
        "lottery_id": lottery_id,
        "imported": imported,
        "updated": updated,
        "days": days,
        "latest_date": latest_date,
        "parser": scrape.get("parser"),
        "errors": scrape.get("errors", []),
    }

    if saved == 0:
        base["status"] = "no_new"
        base["message"] = scrape.get("message") or "No hay resultados nuevos en el rango"
    else:
        base["status"] = "updated"
        base["message"] = scrape.get("message") or f"✅ RD actualizado ({saved} registros)."

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
