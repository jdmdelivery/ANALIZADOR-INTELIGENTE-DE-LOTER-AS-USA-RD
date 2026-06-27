"""
Orquestador inteligente RD — multi-fuente, normalización, confirmación y persistencia.
No afecta Illinois/USA.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from models import (
    count_results_for_lottery,
    format_numbers,
    get_all_lotteries,
    get_max_draw_date,
    upsert_rd_result,
)
from services.lottery_normalize import find_lottery_in_list, lottery_names_match
from services.rd_fuentes_service import (
    LOG_DUP,
    LOG_FALLBACK,
    RD_FUENTES,
    get_fuentes_status,
    log_resultado,
    mark_rd_update,
    run_source,
)
from services.rd_normalize import normalize_rd_row
from services.rd_lottery_config import iter_enabled_conectate_configs

logger = logging.getLogger(__name__)
LOG = "[RD]"

# key → callable (lazy import en run)
_SOURCE_IMPORTERS: dict[str, str] = {
    "conectate_sites_env": "scrapers.rd_sites_env_api.import_conectate_sites_env",
    "ld_sites_env": "scrapers.rd_sites_env_api.import_ld_sites_env",
    "conectate_api": "services.rd_resultados_service._import_conectate_api",
    "conectate_html": "services.rd_resultados_service._import_conectate_html",
    "loteriasdominicanas": "scrapers.rd_fallback_scrapers.import_loteriasdominicanas",
    "loteriadominicana": "scrapers.rd_fallback_scrapers.import_loteriadominicana",
    "sorteosrd": "scrapers.rd_sorteosrd.import_sorteosrd",
    "enloteria": "scrapers.rd_fallback_scrapers.import_enloteria",
    "leidsa": "services.rd_resultados_service._import_leidsa",
    "loteriasdominicanas_us": "services.rd_resultados_service._import_ld_us",
}


def _import_conectate_api(lottery_name: str | None = None, days: int = 30, **_) -> dict:
    if lottery_name:
        from scrapers.rd_fallback_scrapers import import_conectate_api
        return import_conectate_api(lottery_name, days=days)
    from scrapers.kiskoo_nuxt_parser import CONECTATE_API, CONECTATE_PAYLOAD, fetch_hub_rows
    from services.rd_normalize import normalize_rd_row

    res = fetch_hub_rows(api_base=CONECTATE_API, payload_url=CONECTATE_PAYLOAD, days=days)
    rows = [normalize_rd_row(r) for r in (res.get("rows") or [])]
    rows = [r for r in rows if r]
    if not rows:
        return {**res, "imported": 0, "updated": 0, "rows_found": 0}
    save = persist_rd_rows(rows, fuente="conectate_api", days=days)
    return {**res, **save, "rows_found": len(rows), "fuente_label": "Conectate API sessions"}


def _import_conectate_html(lottery_name: str | None = None, days: int = 30, **_) -> dict:
    if lottery_name:
        from scrapers.conectate_rd import import_conectate_lottery_history
        return import_conectate_lottery_history(lottery_name, days=days)
    from scrapers.conectate_rd import import_conectate_rd
    return import_conectate_rd(days_back=days)


def _import_leidsa(lottery_name: str | None = None, days: int = 30, **_) -> dict:
    from services.leidsa_service import update_leidsa_now
    return update_leidsa_now()


def _import_ld_us(lottery_name: str | None = None, days: int = 30, **_) -> dict:
    from services.leidsa_fallback.orchestrator import scrape_leidsa_with_fallbacks
    return scrape_leidsa_with_fallbacks()


def _cutoff_iso(days: int) -> str:
    return (datetime.now() - timedelta(days=max(1, int(days)))).strftime("%Y-%m-%d")


def _load_importer(key: str):
    path = _SOURCE_IMPORTERS.get(key)
    if not path:
        return None
    mod_name, fn_name = path.rsplit(".", 1)
    import importlib

    mod = importlib.import_module(mod_name)
    return getattr(mod, fn_name, None)


def persist_rd_rows(
    rows: list[dict],
    *,
    fuente: str,
    days: int = 30,
    lottery_name: str | None = None,
) -> dict:
    """Guarda filas normalizadas; fusiona fuentes_confirmadas en duplicados."""
    lotteries = get_all_lotteries()
    cutoff = _cutoff_iso(days)
    imported = updated = ignored = 0
    errors: list[str] = []

    for raw in rows:
        row = normalize_rd_row(raw) if not raw.get("pais") else raw
        if not row:
            continue
        nums = row.get("numbers") or []
        db_name = row.get("lottery_name") or ""
        if lottery_name and not lottery_names_match(db_name, lottery_name):
            continue
        lot = find_lottery_in_list(lotteries, db_name, country="RD")
        if not lot:
            continue
        dd = row.get("draw_date") or ""
        if dd and dd < cutoff:
            continue
        draw_name = row.get("draw_name") or "tarde"
        draw_time = row.get("draw_time") or ""
        try:
            rid, action, merged = upsert_rd_result(
                lot["id"],
                draw_name,
                draw_time,
                dd,
                format_numbers(nums),
                fuente=fuente,
                fuentes_extra=row.get("fuentes_confirmadas"),
                confianza_fuente=row.get("confianza_fuente"),
                raw_data=row.get("raw_data"),
                primera=row.get("primera"),
                segunda=row.get("segunda"),
                tercera=row.get("tercera"),
            )
            if action == "inserted":
                imported += 1
                log_resultado("nuevo", row, fuente)
            elif action == "updated":
                updated += 1
                log_resultado("actualizado", row, fuente)
            else:
                ignored += 1
                logger.debug("%s loteria=%s fecha=%s", LOG_DUP, db_name, dd)
        except Exception as exc:
            errors.append(str(exc))
            logger.warning("%s error guardando %s: %s", LOG, db_name, exc)

    return {
        "ok": (imported + updated) > 0 or (bool(rows) and not errors),
        "imported": imported,
        "updated": updated,
        "ignored": ignored,
        "rows_found": len(rows),
        "rows_saved": imported + updated,
        "errors": errors[:10],
    }


def _merge_row_maps(maps: list[dict[tuple, dict]]) -> list[dict]:
    """Fusiona filas por (lotería, sorteo, horario, fecha, números)."""
    merged: dict[tuple, dict] = {}
    for m in maps:
        for key, row in m.items():
            if key not in merged:
                merged[key] = {**row, "fuentes_confirmadas": [row.get("fuente", "")]}
            else:
                existing = merged[key]
                srcs = set(existing.get("fuentes_confirmadas") or [])
                srcs.add(row.get("fuente", ""))
                existing["fuentes_confirmadas"] = sorted(s for s in srcs if s)
                existing["confianza_fuente"] = min(100, 50 + 15 * len(existing["fuentes_confirmadas"]))
    return list(merged.values())


def _row_key(row: dict) -> tuple:
    return (
        row.get("lottery_name", ""),
        row.get("draw_name", ""),
        row.get("draw_time", ""),
        row.get("draw_date", ""),
        tuple(row.get("numbers") or []),
    )


def actualizar_resultados_rd(
    *,
    days: int = 100,
    lottery_name: str | None = None,
    fecha: str | None = None,
) -> dict:
    """
    Recorre fuentes RD en orden de prioridad; acumula y persiste sin duplicar.
    """
    days = max(7, min(int(days or 100), 365))
    sources_tried: list[dict] = []
    total_imported = total_updated = 0
    errors: list[str] = []
    primary_source = None

    for key, label, _timeout, leidsa_only in RD_FUENTES:
        if leidsa_only and lottery_name and "leidsa" not in lottery_name.lower():
            continue
        if not lottery_name and key in (
            "loteriasdominicanas", "loteriadominicana", "enloteria", "conectate_html",
        ):
            continue
        fn = _load_importer(key)
        if not fn:
            continue
        res = run_source(
            key,
            fn,
            days=days,
            lottery_name=lottery_name,
            fecha=fecha,
        )
        sources_tried.append({
            "key": key,
            "label": label,
            "ok": res.get("ok"),
            "imported": res.get("imported", 0),
            "updated": res.get("updated", 0),
            "rows": res.get("rows_found") or len(res.get("rows") or []),
            "error": res.get("error"),
        })
        total_imported += int(res.get("imported") or 0)
        total_updated += int(res.get("updated") or 0)
        if res.get("ok") and (res.get("imported") or res.get("updated") or res.get("rows")):
            if not primary_source:
                primary_source = label
        if not res.get("ok"):
            errors.append(f"{label}: {res.get('error') or 'falló'}")
            print(f"{LOG_FALLBACK} fuente falló ({label}), continuando")

    mark_rd_update()
    saved = total_imported + total_updated
    lot = find_lottery_in_list(get_all_lotteries(), lottery_name, country="RD") if lottery_name else None
    lottery_id = lot["id"] if lot else None

    return {
        "ok": saved > 0 or any(s.get("ok") for s in sources_tried),
        "pais": "RD",
        "days": days,
        "imported": total_imported,
        "updated": total_updated,
        "saved_count": saved,
        "fuente_principal": primary_source or "multi",
        "sources_tried": sources_tried,
        "fuentes_status": get_fuentes_status(),
        "lottery_id": lottery_id,
        "latest_date": get_max_draw_date(lottery_id) if lottery_id else None,
        "message": f"RD actualizado ({days} días): +{total_imported} nuevos, {total_updated} actualizados.",
        "errors": errors[:10],
    }


def actualizar_rd_todas(days: int = 100) -> dict:
    """Actualiza todas las loterías RD habilitadas."""
    days = max(7, min(int(days or 100), 365))
    # Primero pasada global multi-fuente
    global_res = actualizar_resultados_rd(days=days)
    per_lot: list[dict] = []
    for cfg in iter_enabled_conectate_configs():
        name = cfg["db_names"][0]
        r = actualizar_resultados_rd(days=days, lottery_name=name)
        per_lot.append({"loteria": name, "imported": r.get("imported"), "updated": r.get("updated")})
    return {
        **global_res,
        "por_loteria": per_lot,
        "loterias": len(per_lot),
    }


def test_resultados_fecha(fecha: str, lottery_name: str | None = None) -> dict:
    from scrapers.rd_sites_env_api import fetch_sites_env_for_date

    out = {"fecha": fecha, "fuentes": []}
    for kind in ("conectate", "ld"):
        res = fetch_sites_env_for_date(fecha, api_kind=kind, lottery_name=lottery_name)
        rows = res.get("rows") or []
        out["fuentes"].append({
            "api": kind,
            "ok": res.get("ok"),
            "count": len(rows),
            "error": res.get("error"),
            "sample": rows[:3],
        })
    return out


def reparar_historico(days: int = 365) -> dict:
    """Re-sincroniza historial RD completo sin borrar datos."""
    return actualizar_rd_todas(days=min(int(days or 365), 365))
