"""
Orquestador multi-fuente RD — Conectate → LD → LotDom → EnLoteria → caché BD.
No afecta loterías USA.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta

from models import count_results_for_lottery, get_all_lotteries, get_latest_result_date_for_scope, get_max_draw_date
from services.lottery_normalize import find_lottery_in_list, normalize_lottery_name
from services.rd_lottery_config import get_rd_lottery_config, iter_enabled_conectate_configs
from services.rd_time import today_rd_iso
from services.rd_update_log import log_rd_update

logger = logging.getLogger(__name__)
LOG = "[RD]"
MAX_RD_JOB_SECONDS = int(os.environ.get("RD_MAX_JOB_SECONDS", "120"))
SOFT_RD_JOB_SECONDS = int(os.environ.get("RD_SOFT_JOB_SECONDS", "30"))
LEIDSA_PRIORITY_BUDGET_SECONDS = int(os.environ.get("RD_LEIDSA_PRIORITY_SECONDS", "10"))
REAL_PRIORITY_BUDGET_SECONDS = int(os.environ.get("RD_REAL_PRIORITY_SECONDS", "10"))

SOURCE_LABELS = {
    "conectate_api": "Conectate API",
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
    ("enloteria", "import_enloteria"),
    ("loteriadominicana", "import_loteriadominicana"),
    ("conectate", "import_conectate_hub"),
    ("loteriasdominicanas", "import_loteriasdominicanas"),
]


def _job_event(job_id: str | None, event: str, *, source: str = "-", elapsed_ms: int = 0, **extra) -> None:
    if not job_id:
        return
    parts = [f"job={job_id}", f"event={event}", f"source={source}", f"elapsed_ms={elapsed_ms}"]
    for k, v in extra.items():
        if v is None:
            continue
        parts.append(f"{k}={v}")
    logger.info("[RDJOB] %s", " ".join(parts))


def _deadline_reached(started_at: float, max_seconds: int) -> bool:
    return (time.monotonic() - started_at) >= max(5, int(max_seconds or MAX_RD_JOB_SECONDS))


def _saved(res: dict) -> bool:
    return int(res.get("imported") or 0) + int(res.get("updated") or 0) > 0


def _latest_is_stale(latest_date: str | None, *, max_age_days: int = 7) -> bool:
    """True si no hay fecha o está más atrasada que max_age_days (zona RD)."""
    if not latest_date:
        return True
    try:
        from services.leidsa_history import _days_since_draw

        age = _days_since_draw(str(latest_date)[:10])
        return age is None or age > max_age_days
    except Exception:
        return True


def _stale_threshold_for_lottery(lot: dict) -> int:
    try:
        from services.rd_stale import _threshold_for_lottery  # type: ignore

        return int(_threshold_for_lottery(lot))
    except Exception:
        return 3


def _iso_date(value: str):
    return datetime.strptime((value or "")[:10], "%Y-%m-%d").date()


def _effective_days_from_last_date(
    lottery_id: int,
    requested_days: int,
    *,
    lottery_name: str = "",
    force_days: int = 0,
) -> tuple[int, str, str]:
    """Ventana incremental por lotería/sorteo desde último dato guardado."""
    cfg = get_rd_lottery_config(lottery_name or "") or {}
    draws = cfg.get("draw_map", {})
    latest_values: list[str] = []
    for draw_name, time_12h in draws.items():
        latest = get_latest_result_date_for_scope(
            lottery_id,
            draw_name=draw_name,
            draw_time=time_12h,
        )
        if latest:
            latest_values.append(latest)

    latest_global = max(latest_values) if latest_values else get_max_draw_date(lottery_id)
    end_iso = today_rd_iso()
    if latest_global:
        start_date = _iso_date(latest_global) + timedelta(days=1)
    else:
        start_date = _iso_date(end_iso) - timedelta(days=max(7, int(requested_days or 30)))
    if force_days and int(force_days) > 0:
        force_start = _iso_date(end_iso) - timedelta(days=max(1, int(force_days)))
        if force_start < start_date:
            start_date = force_start
    start_iso = start_date.isoformat()
    span_days = max(1, (_iso_date(end_iso) - start_date).days + 1)
    days = max(7, min(max(span_days + 2, int(requested_days or 30)), 365))
    return days, start_iso, end_iso


def _rows_found(res: dict) -> int:
    return int(
        res.get("rows_found")
        or res.get("rows_saved")
        or res.get("rows_parsed")
        or res.get("results_found")
        or 0
    )


def _needs_fallback(res: dict) -> bool:
    if not res:
        return True
    status = int(res.get("status_code") or 0)
    if status == 403 or status >= 500:
        return True
    if not res.get("ok"):
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
        "latency_ms": int(float(res.get("elapsed") or 0) * 1000),
        "content_type": res.get("content_type") or "",
        "bytes": int(res.get("bytes") or res.get("size") or 0),
        "sorteos": _rows_found(res),
        "rows_detected": _rows_found(res),
        "imported": res.get("imported", 0),
        "updated": res.get("updated", 0),
        "ignored": res.get("ignored", 0),
        "rejected": res.get("rejected", 0),
        "error": err,
        "url": res.get("url") or "",
        "parser": res.get("parser"),
        "latest_date": res.get("latest_date") or ((res.get("dates_found") or [None])[0]),
        "started_at": res.get("started_at"),
        "finished_at": res.get("finished_at"),
        "disabled_until": res.get("disabled_until"),
        "source_health": res.get("source_health") or {},
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
    try:
        from services.rd_scraper_diagnostic import record_scraper_run

        dates = res.get("dates_found") or []
        record_scraper_run(
            key,
            {
                **entry,
                "ok": entry["ok"],
                "ultima_fecha": dates[0] if dates else None,
                "lottery_name": lottery_name,
            },
        )
    except Exception:
        pass


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
    cfg = get_rd_lottery_config(lottery_name) or {}
    multi_page = len(cfg.get("conectate_pages") or []) >= 2
    if (lot and is_new_rd_lottery(lot)) or multi_page:
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


def _run_with_timing(fn, *, source: str) -> dict:
    started = datetime.now().isoformat(timespec="seconds")
    t0 = time.monotonic()
    try:
        out = fn() or {}
    except Exception as exc:
        out = {"ok": False, "error": str(exc), "message": str(exc)}
    finished = datetime.now().isoformat(timespec="seconds")
    elapsed = round(time.monotonic() - t0, 2)
    out.setdefault("elapsed", elapsed)
    out["started_at"] = started
    out["finished_at"] = finished
    out["elapsed_ms"] = int(elapsed * 1000)
    out["source"] = source
    return out


def actualizar_rd_loteria(
    lottery_name: str,
    days: int = 30,
    *,
    force_days: int = 0,
    job_id: str | None = None,
    job_started_at: float | None = None,
    max_job_seconds: int | None = None,
) -> dict:
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
        return actualizar_leidsa_multi(
            days=days,
            lottery_name=db_name,
            job_id=job_id,
            job_started_at=job_started_at,
            max_job_seconds=max_job_seconds,
        )

    days, fecha_desde, fecha_hasta = _effective_days_from_last_date(
        lot["id"],
        days,
        lottery_name=db_name,
        force_days=force_days,
    )

    logger.info("%s === Inicio %s — multi-fuente ===", LOG, db_name)
    t0 = time.monotonic()
    j_start = job_started_at or t0
    j_limit = int(max_job_seconds or MAX_RD_JOB_SECONDS)
    attempted_sources: set[str] = set()
    soft_limit = int(min(max(1, SOFT_RD_JOB_SECONDS), j_limit))
    stale_threshold = _stale_threshold_for_lottery(lot)

    def _check_deadline(source: str) -> dict | None:
        if _deadline_reached(j_start, j_limit):
            msg = f"RD update exceeded maximum execution time ({j_limit}s)"
            _job_event(job_id, "SOURCE_ERROR", source=source, elapsed_ms=int((time.monotonic() - t0) * 1000), error=msg)
            return {
                "ok": False,
                "pais": "DO",
                "lottery_name": db_name,
                "sources_tried": sources_tried,
                "errors": errors + [msg],
                "error_detail": msg,
                "live_failed": True,
                "fecha_desde": fecha_desde,
                "fecha_hasta": fecha_hasta,
                "message": msg,
            }
        return None

    # 1 — Fuentes vivas priorizadas dinámicamente por salud.
    priority = [("enloteria", "import_enloteria"), ("loteriadominicana", "import_loteriadominicana")]
    try:
        from scrapers.rd_http import rank_sources

        rank_map = {k: v for k, v in priority}
        ordered_keys = rank_sources([k for k, _ in priority])
        priority = [(k, rank_map[k]) for k in ordered_keys if k in rank_map]
    except Exception:
        pass
    for fuente_key, fn_name in priority:
        attempted_sources.add(fuente_key)
        deadline_hit = _check_deadline(fuente_key)
        if deadline_hit:
            return deadline_hit
        try:
            _job_event(job_id, "SOURCE_START", source=fuente_key, elapsed_ms=int((time.monotonic() - t0) * 1000))
            pri = _run_with_timing(
                lambda: _run_fallback(fuente_key, fn_name, db_name, days),
                source=fuente_key,
            )
            _record(sources_tried, fuente_key, pri, lottery_name=db_name)
            _job_event(job_id, "SOURCE_END", source=fuente_key, elapsed_ms=int((time.monotonic() - t0) * 1000), rows=_rows_found(pri), status=pri.get("status_code"))
            latest_scope = get_max_draw_date(lot["id"])
            if pri.get("ok") and (_saved(pri) or _rows_found(pri) > 0) and not _latest_is_stale(latest_scope, max_age_days=stale_threshold):
                out = _success(pri, fuente_key=fuente_key, lottery_name=db_name, sources_tried=sources_tried)
                out["elapsed_total"] = round(time.monotonic() - t0, 2)
                out["tiempo"] = out["elapsed_total"]
                out["fecha_desde"] = fecha_desde
                out["fecha_hasta"] = fecha_hasta
                out["latest_date"] = latest_scope
                return out
            if pri.get("ok") and (_saved(pri) or _rows_found(pri) > 0) and _latest_is_stale(latest_scope, max_age_days=stale_threshold):
                errors.append(f"{fuente_key}: stale_source_result ({latest_scope})")
            if pri.get("message"):
                errors.append(pri["message"])
        except Exception as exc:
            logger.exception("%s fuente priorizada %s error", LOG, fuente_key)
            errors.append(str(exc))
            _record(
                sources_tried,
                fuente_key,
                {"ok": False, "error": str(exc), "message": str(exc)},
                lottery_name=db_name,
            )
            _job_event(job_id, "SOURCE_ERROR", source=fuente_key, elapsed_ms=int((time.monotonic() - t0) * 1000), error=str(exc))

    # 2 — API Kiskoo (Conectate → LD automático ante 403)
    if (time.monotonic() - j_start) < soft_limit:
        try:
            from scrapers.rd_fallback_scrapers import import_conectate_api

            _job_event(job_id, "SOURCE_START", source="conectate_api", elapsed_ms=int((time.monotonic() - t0) * 1000))
            api = _run_with_timing(
                lambda: import_conectate_api(db_name, days, force_refresh=True),
                source="conectate_api",
            )
            api["elapsed"] = api.get("elapsed") or round(time.monotonic() - t0, 2)
            _record(sources_tried, "conectate_api", api, lottery_name=db_name)
            _job_event(job_id, "SOURCE_END", source="conectate_api", elapsed_ms=int((time.monotonic() - t0) * 1000), rows=_rows_found(api), status=api.get("status_code"))
            if not _needs_fallback(api):
                out = _success(api, fuente_key="conectate_api", lottery_name=db_name, sources_tried=sources_tried)
                out["elapsed_total"] = round(time.monotonic() - t0, 2)
                out["tiempo"] = out["elapsed_total"]
                out["fecha_desde"] = fecha_desde
                out["fecha_hasta"] = fecha_hasta
                out["latest_date"] = get_max_draw_date(lot["id"])
                return out
            if api.get("message"):
                errors.append(api["message"])
        except Exception as exc:
            logger.exception("%s Conectate API error %s", LOG, db_name)
            errors.append(str(exc))
            _record(
                sources_tried,
                "conectate_api",
                {"ok": False, "error": str(exc), "message": str(exc)},
                lottery_name=db_name,
            )
            _job_event(job_id, "SOURCE_ERROR", source="conectate_api", elapsed_ms=int((time.monotonic() - t0) * 1000), error=str(exc))
    else:
        errors.append(f"{db_name}: soft_budget_skip_conectate_api")

    # 3 — Conectate HTML (páginas de tanda)
    if (time.monotonic() - j_start) < soft_limit:
        deadline_hit = _check_deadline("conectate_primary")
        if deadline_hit:
            return deadline_hit
        try:
            _job_event(job_id, "SOURCE_START", source="conectate_primary", elapsed_ms=int((time.monotonic() - t0) * 1000))
            primary = _run_with_timing(
                lambda: _run_conectate_primary(db_name, days),
                source="conectate_primary",
            )
            primary["elapsed"] = round(time.monotonic() - t0, 2)
            _record(sources_tried, "conectate_primary", primary, lottery_name=db_name)
            _job_event(job_id, "SOURCE_END", source="conectate_primary", elapsed_ms=int((time.monotonic() - t0) * 1000), rows=_rows_found(primary), status=primary.get("status_code"))
            if not _needs_fallback(primary):
                out = _success(primary, fuente_key="conectate", lottery_name=db_name, sources_tried=sources_tried)
                out["elapsed_total"] = round(time.monotonic() - t0, 2)
                out["tiempo"] = out["elapsed_total"]
                out["fecha_desde"] = fecha_desde
                out["fecha_hasta"] = fecha_hasta
                out["latest_date"] = get_max_draw_date(lot["id"])
                return out
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
            _job_event(job_id, "SOURCE_ERROR", source="conectate_primary", elapsed_ms=int((time.monotonic() - t0) * 1000), error=str(exc))
    else:
        errors.append(f"{db_name}: soft_budget_skip_conectate_primary")

    # 4..n — Fallbacks restantes
    for fuente_key, fn_name in FALLBACK_CHAIN:
        if fuente_key in attempted_sources:
            continue
        if (time.monotonic() - j_start) >= soft_limit:
            errors.append(f"{db_name}: soft_budget_skip_{fuente_key}")
            continue
        deadline_hit = _check_deadline(fuente_key)
        if deadline_hit:
            return deadline_hit
        logger.info("%s %s — probando %s", LOG, db_name, SOURCE_LABELS.get(fuente_key, fuente_key))
        try:
            _job_event(job_id, "SOURCE_START", source=fuente_key, elapsed_ms=int((time.monotonic() - t0) * 1000))
            fb = _run_with_timing(
                lambda: _run_fallback(fuente_key, fn_name, db_name, days),
                source=fuente_key,
            )
            _record(sources_tried, fuente_key, fb, lottery_name=db_name)
            _job_event(job_id, "SOURCE_END", source=fuente_key, elapsed_ms=int((time.monotonic() - t0) * 1000), rows=_rows_found(fb), status=fb.get("status_code"))
            latest_scope = get_max_draw_date(lot["id"])
            if fb.get("ok") and (_saved(fb) or _rows_found(fb) > 0) and not _latest_is_stale(latest_scope, max_age_days=stale_threshold):
                out = _success(
                    fb,
                    fuente_key=fuente_key,
                    lottery_name=db_name,
                    sources_tried=sources_tried,
                    warning=True,
                )
                out["elapsed_total"] = round(time.monotonic() - t0, 2)
                out["tiempo"] = out["elapsed_total"]
                out["fecha_desde"] = fecha_desde
                out["fecha_hasta"] = fecha_hasta
                out["latest_date"] = latest_scope
                return out
            if fb.get("ok") and (_saved(fb) or _rows_found(fb) > 0) and _latest_is_stale(latest_scope, max_age_days=stale_threshold):
                errors.append(f"{fuente_key}: stale_source_result ({latest_scope})")
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
            _job_event(job_id, "SOURCE_ERROR", source=fuente_key, elapsed_ms=int((time.monotonic() - t0) * 1000), error=str(exc))

    # 7 — Caché BD (solo si TODAS las fuentes fallaron)
    cached = _cache_response(lot, errors=errors)
    if cached:
        cached["sources_tried"] = sources_tried
        cached["errors"] = errors[:10]
        cached["elapsed_total"] = round(time.monotonic() - t0, 2)
        cached["tiempo"] = cached["elapsed_total"]
        cached["fecha_desde"] = fecha_desde
        cached["fecha_hasta"] = fecha_hasta
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
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "message": errors[0] if errors else f"No se pudo actualizar {db_name}",
    }


def _leidsa_history_slug(lottery_name: str | None) -> str | None:
    if not lottery_name:
        return None
    from services.leidsa_config import LEIDSA_SLUGS, is_leidsa_game_lottery

    lot = find_lottery_in_list(get_all_lotteries(), lottery_name, country="RD")
    if not lot or not is_leidsa_game_lottery(lot):
        return None
    ltype = (lot.get("type") or "").strip().lower()
    if ltype in LEIDSA_SLUGS:
        return ltype
    from services.leidsa_service import normalize_lottery_slug

    return normalize_lottery_slug(name=lot.get("name") or lottery_name)


def actualizar_leidsa_multi(
    *,
    days: int = 30,
    lottery_name: str | None = None,
    job_id: str | None = None,
    job_started_at: float | None = None,
    max_job_seconds: int | None = None,
) -> dict:
    """LEIDSA oficial + fallbacks agregadores + caché."""
    sources_tried: list[dict] = []
    errors: list[str] = []
    history_slug = _leidsa_history_slug(lottery_name)
    days = int(days or 30)
    lot = None
    if lottery_name:
        lot = find_lottery_in_list(get_all_lotteries(), lottery_name, country="RD")
    if not lot and history_slug:
        from models import get_lottery_by_slug

        lot = get_lottery_by_slug(history_slug)

    logger.info("%s === LEIDSA multi-fuente === slug=%s", LOG, history_slug or "todos")
    t0 = time.monotonic()
    j_start = job_started_at or t0
    j_limit = int(max_job_seconds or MAX_RD_JOB_SECONDS)
    total_imported = 0
    total_updated = 0
    total_ignored = 0
    total_rejected = 0

    def _check_deadline(source: str) -> dict | None:
        if _deadline_reached(j_start, j_limit):
            msg = f"RD update exceeded maximum execution time ({j_limit}s)"
            _job_event(job_id, "SOURCE_ERROR", source=source, elapsed_ms=int((time.monotonic() - t0) * 1000), error=msg)
            return {
                "ok": False,
                "pais": "DO",
                "sources_tried": sources_tried,
                "errors": errors + [msg],
                "message": msg,
            }
        return None

    if history_slug:
        from services.leidsa_service import update_leidsa_game_incremental

        _job_event(job_id, "SOURCE_START", source="leidsa_incremental", elapsed_ms=int((time.monotonic() - t0) * 1000))
        fast = update_leidsa_game_incremental(
            history_slug,
            lookback_days=days,
        )
        fast["fuente"] = "leidsa"
        fast["fuente_label"] = "LEIDSA.com"
        _record(
            sources_tried,
            "leidsa_drawResults",
            fast,
            lottery_name=lottery_name or history_slug,
        )
        _job_event(job_id, "SOURCE_END", source="leidsa_incremental", elapsed_ms=int((time.monotonic() - t0) * 1000), rows=int(fast.get("rows_found") or 0), status=fast.get("status_code"))
        if lot:
            fast["lottery_id"] = lot["id"]
            fast["latest_date"] = get_max_draw_date(lot["id"]) or fast.get("latest_date")
            fast["ultima_fecha"] = fast.get("latest_date")
        if fast.get("ok") and not _latest_is_stale(fast.get("latest_date")):
            fast["pais"] = "DO"
            fast["fuente_usada"] = "LEIDSA.com"
            fast["sources_tried"] = sources_tried
            fast["imported"] = int(fast.get("inserted") or 0)
            fast["mensaje"] = fast.get("message") or f"LEIDSA {history_slug} actualizado."
            return fast
        if fast.get("ok") and _latest_is_stale(fast.get("latest_date")):
            msg = (
                f"LEIDSA {history_slug}: fecha atrasada "
                f"({fast.get('latest_date') or 'sin fecha'}) — probando fuentes alternativas"
            )
            logger.warning("%s %s", LOG, msg)
            errors.append(msg)
        elif fast.get("message"):
            errors.append(fast["message"])

    try:
        from services.leidsa_service import update_leidsa_now

        deadline_hit = _check_deadline("leidsa")
        if deadline_hit:
            return deadline_hit
        _job_event(job_id, "SOURCE_START", source="leidsa", elapsed_ms=int((time.monotonic() - t0) * 1000))
        scrape_cache: dict = {}
        leidsa = update_leidsa_now(
            history_game_slug=history_slug,
            history_days=days,
            scrape_cache=scrape_cache,
        )
        leidsa["fuente"] = "leidsa"
        leidsa["fuente_label"] = "LEIDSA.com"
        _record(sources_tried, "leidsa", leidsa)
        _job_event(job_id, "SOURCE_END", source="leidsa", elapsed_ms=int((time.monotonic() - t0) * 1000), rows=int(leidsa.get("results_found") or 0), status=leidsa.get("status_code"))
        if lot is None and lottery_name:
            lot = find_lottery_in_list(get_all_lotteries(), lottery_name, country="RD")
        if lot:
            leidsa["latest_date"] = get_max_draw_date(lot["id"]) or leidsa.get("latest_date")
        total_imported += int(leidsa.get("imported") or leidsa.get("inserted") or 0)
        total_updated += int(leidsa.get("updated") or 0)
        total_ignored += int(leidsa.get("ignored") or 0)
        total_rejected += int(leidsa.get("rejected") or 0)
        if leidsa.get("ok") and not _latest_is_stale(leidsa.get("latest_date")):
            pass
        elif leidsa.get("ok") and _latest_is_stale(leidsa.get("latest_date")):
            errors.append(
                f"LEIDSA update_now fecha atrasada ({leidsa.get('latest_date') or 'sin fecha'})"
            )
        elif leidsa.get("message"):
            errors.append(leidsa["message"])

        priority_targets = [history_slug] if history_slug else ["leidsa_quiniela_pale", "leidsa_super_kino_tv"]
        priority_fresh: dict[str, bool] = {}

        # Prioridad funcional: Quiniela Palé + Super Kino no pueden quedar fuera.
        if not history_slug:
            from models import get_lottery_by_slug
            from services.leidsa_service import sync_priority_games_from_cached_scrape

            for slug in priority_targets:
                lot_slug = get_lottery_by_slug(slug)
                latest_slug = get_max_draw_date(lot_slug["id"]) if lot_slug else None
                is_fresh = lot_slug and not _latest_is_stale(latest_slug, max_age_days=3)
                if is_fresh:
                    priority_fresh[slug] = True
                    continue
                deadline_hit = _check_deadline(f"leidsa_priority_{slug}")
                if deadline_hit:
                    return deadline_hit
                _job_event(
                    job_id,
                    "SOURCE_START",
                    source=f"leidsa_priority_{slug}",
                    elapsed_ms=int((time.monotonic() - t0) * 1000),
                )
                fix = sync_priority_games_from_cached_scrape(
                    slugs=[slug],
                    scrape_cache=scrape_cache,
                )
                fix["fuente"] = "leidsa"
                fix["fuente_label"] = "LEIDSA.com"
                _record(sources_tried, f"leidsa_priority_{slug}", fix, lottery_name=slug)
                _job_event(
                    job_id,
                    "SOURCE_END",
                    source=f"leidsa_priority_{slug}",
                    elapsed_ms=int((time.monotonic() - t0) * 1000),
                    rows=int(fix.get("results_found") or 0),
                    status=fix.get("status_code"),
                )
                total_imported += int(fix.get("inserted") or fix.get("imported") or 0)
                total_updated += int(fix.get("updated") or 0)
                total_ignored += int(fix.get("ignored") or 0)
                total_rejected += int(fix.get("rejected") or 0)
                latest_slug = get_max_draw_date(lot_slug["id"]) if lot_slug else latest_slug
                is_fresh = bool(lot_slug and not _latest_is_stale(latest_slug, max_age_days=3))
                priority_fresh[slug] = is_fresh
                if not is_fresh:
                    errors.append(f"{slug}: stale_after_priority_sync ({latest_slug or 'sin fecha'})")
        else:
            priority_fresh[history_slug] = not _latest_is_stale(leidsa.get("latest_date"), max_age_days=3)

        all_priority_fresh = all(priority_fresh.get(s, False) for s in priority_targets)
        if (total_imported + total_updated > 0 or leidsa.get("ok")) and all_priority_fresh:
            return {
                "ok": True,
                "pais": "DO",
                "status": "updated" if not errors else "partial",
                "message": leidsa.get("message") or "LEIDSA actualizada.",
                "imported": total_imported,
                "updated": total_updated,
                "ignored": total_ignored,
                "rejected": total_rejected,
                "latest_date": leidsa.get("latest_date"),
                "fuente": "leidsa",
                "fuente_usada": "LEIDSA.com",
                "fuente_label": "LEIDSA.com",
                "sources_tried": sources_tried,
                "warning": bool(errors),
                "errors": errors[:10],
            }
    except Exception as exc:
        logger.exception("%s LEIDSA primary error", LOG)
        errors.append(str(exc))
        _job_event(job_id, "SOURCE_ERROR", source="leidsa", elapsed_ms=int((time.monotonic() - t0) * 1000), error=str(exc))

    target = lottery_name or "Leidsa"
    for fuente_key, fn_name in FALLBACK_CHAIN:
        deadline_hit = _check_deadline(fuente_key)
        if deadline_hit:
            return deadline_hit
        try:
            _job_event(job_id, "SOURCE_START", source=fuente_key, elapsed_ms=int((time.monotonic() - t0) * 1000))
            fb = _run_fallback(fuente_key, fn_name, target, days)
            _record(sources_tried, fuente_key, fb)
            _job_event(job_id, "SOURCE_END", source=fuente_key, elapsed_ms=int((time.monotonic() - t0) * 1000), rows=_rows_found(fb), status=fb.get("status_code"))
            lot_fb = find_lottery_in_list(get_all_lotteries(), target, country="RD")
            latest_fb = get_max_draw_date(lot_fb["id"]) if lot_fb else fb.get("latest_date")
            if fb.get("ok") and _saved(fb) and not _latest_is_stale(latest_fb):
                out = _success(
                    fb,
                    fuente_key=fuente_key,
                    lottery_name=target,
                    sources_tried=sources_tried,
                    warning=True,
                )
                out["imported"] = int(out.get("imported") or 0) + total_imported
                out["updated"] = int(out.get("updated") or 0) + total_updated
                out["ignored"] = int(out.get("ignored") or 0) + total_ignored
                out["rejected"] = int(out.get("rejected") or 0) + total_rejected
                out["latest_date"] = latest_fb
                return out
            if fb.get("ok") and _saved(fb) and _latest_is_stale(latest_fb):
                errors.append(
                    f"{fuente_key}: guardó filas pero fecha sigue atrasada ({latest_fb})"
                )
            elif fb.get("message"):
                errors.append(fb["message"])
        except Exception as exc:
            errors.append(str(exc))
            _job_event(job_id, "SOURCE_ERROR", source=fuente_key, elapsed_ms=int((time.monotonic() - t0) * 1000), error=str(exc))

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
        cached["imported"] = int(cached.get("imported") or 0) + total_imported
        cached["updated"] = int(cached.get("updated") or 0) + total_updated
        cached["ignored"] = int(cached.get("ignored") or 0) + total_ignored
        cached["rejected"] = int(cached.get("rejected") or 0) + total_rejected
        cached["mensaje"] = ALT_MESSAGE + " Se muestran datos guardados."
        cached["message"] = cached["mensaje"]
        cached["warning"] = True
        return cached

    latest_date = None
    try:
        if history_slug:
            from models import get_lottery_by_slug

            lot_h = get_lottery_by_slug(history_slug)
            latest_date = get_max_draw_date(lot_h["id"]) if lot_h else None
        else:
            from models import get_lottery_by_slug

            cand = []
            for slug in ("leidsa_quiniela_pale", "leidsa_super_kino_tv"):
                lot_h = get_lottery_by_slug(slug)
                if lot_h:
                    d = get_max_draw_date(lot_h["id"])
                    if d:
                        cand.append(d)
            latest_date = max(cand) if cand else None
    except Exception:
        latest_date = None

    ok_any = (total_imported + total_updated) > 0
    if ok_any:
        return {
            "ok": True,
            "pais": "DO",
            "status": "partial" if errors else "updated",
            "sources_tried": sources_tried,
            "errors": errors[:10],
            "message": "LEIDSA actualizada parcialmente con prioridad aplicada.",
            "imported": total_imported,
            "updated": total_updated,
            "ignored": total_ignored,
            "rejected": total_rejected,
            "latest_date": latest_date,
            "warning": bool(errors),
        }

    return {
        "ok": False,
        "pais": "DO",
        "sources_tried": sources_tried,
        "errors": errors,
        "message": errors[0] if errors else "LEIDSA no respondió",
        "imported": total_imported,
        "updated": total_updated,
        "ignored": total_ignored,
        "rejected": total_rejected,
        "latest_date": latest_date,
    }


def actualizar_rd_todas(
    days: int = 30,
    *,
    force_days: int = 0,
    job_id: str | None = None,
    max_job_seconds: int | None = None,
) -> dict:
    """Historial completo RD con multi-fuente por lotería."""
    days = int(days or 30)
    total_imported = 0
    total_updated = 0
    total_ignored = 0
    total_rejected = 0
    errors: list[str] = []
    details: list[dict] = []
    sources_all: list[dict] = []
    dates_union: set[str] = set()
    warnings: list[str] = []
    started = time.monotonic()
    deadline_seconds = int(max_job_seconds or MAX_RD_JOB_SECONDS)
    soft_seconds = min(deadline_seconds, int(max(1, SOFT_RD_JOB_SECONDS)))

    _job_event(job_id, "JOB_START", source="-", elapsed_ms=0, days=days)
    job_sequence: list[dict] = []

    def _seq(scope: str, status: str, started_scope: float, *, kind: str = "scope", note: str = "") -> None:
        job_sequence.append(
            {
                "kind": kind,
                "scope": scope,
                "status": status,
                "elapsed_ms": int((time.monotonic() - started_scope) * 1000),
                "elapsed_cumulative_ms": int((time.monotonic() - started) * 1000),
                "note": note,
            }
        )

    # PHASE 1 — PRIORITY (siempre antes de cortar por soft budget)
    p1_start = time.monotonic()
    leidsa_out = actualizar_leidsa_multi(
        days=min(days, 30),
        job_id=job_id,
        job_started_at=started,
        max_job_seconds=deadline_seconds,
    )
    _seq("LEIDSA", "done" if leidsa_out.get("ok") else "error", p1_start, kind="priority")
    details.append({"name": "LEIDSA", **leidsa_out})
    if leidsa_out.get("ok"):
        total_imported += int(leidsa_out.get("imported") or 0)
        total_updated += int(leidsa_out.get("updated") or 0)
        total_ignored += int(leidsa_out.get("ignored") or 0)
        total_rejected += int(leidsa_out.get("rejected") or 0)
        if leidsa_out.get("warning"):
            warnings.append("LEIDSA")
    else:
        errors.append(leidsa_out.get("message") or "LEIDSA: error")
    for src in leidsa_out.get("sources_tried") or []:
        sources_all.append({"lottery": "LEIDSA", **src})

    refreshed: set[str] = set()
    configs = list(iter_enabled_conectate_configs())
    configs.sort(key=lambda it: 0 if (it[1]["db_names"][0] == "Lotería Real") else 1)
    # Reserva conceptual de presupuesto para prioridades.
    reserved_priority = min(
        soft_seconds,
        max(1, min(LEIDSA_PRIORITY_BUDGET_SECONDS, soft_seconds))
        + max(1, min(REAL_PRIORITY_BUDGET_SECONDS, soft_seconds)),
    )
    phase2_soft_gate = max(1, soft_seconds - max(0, reserved_priority - int(time.monotonic() - started)))

    priority_done = {"Lotería Real": False}
    for _label, cfg in configs:
        if _deadline_reached(started, deadline_seconds):
            msg = f"RD update exceeded maximum execution time ({deadline_seconds}s)"
            errors.append(msg)
            break
        db_name = cfg["db_names"][0]
        key = normalize_lottery_name(db_name)
        if key in refreshed:
            continue
        refreshed.add(key)
        # Completar scope prioritario (Real) aun si ya se tocó soft budget.
        if (
            db_name != "Lotería Real"
            and (time.monotonic() - started) >= soft_seconds
            and (total_imported + total_updated) > 0
        ):
            errors.append(f"RD update reached soft budget ({soft_seconds}s)")
            _seq(db_name, "skipped", started, kind="secondary", note="soft_budget")
            break
        if (
            db_name != "Lotería Real"
            and (time.monotonic() - started) >= phase2_soft_gate
            and (total_imported + total_updated) > 0
        ):
            errors.append(f"RD update reached soft budget ({soft_seconds}s)")
            _seq(db_name, "skipped", started, kind="secondary", note="phase2_soft_gate")
            break
        scope_start = time.monotonic()
        try:
            out = actualizar_rd_loteria(
                db_name,
                days=days,
                force_days=force_days,
                job_id=job_id,
                job_started_at=started,
                max_job_seconds=deadline_seconds,
            )
            _seq(
                db_name,
                "done" if out.get("ok") else "error",
                scope_start,
                kind="priority" if db_name == "Lotería Real" else "secondary",
            )
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
                total_ignored += int(out.get("ignored") or 0)
                total_rejected += int(out.get("rejected") or 0)
                for d in out.get("dates_found") or []:
                    dates_union.add(d)
                if out.get("warning"):
                    warnings.append(db_name)
            else:
                errors.append(f"{db_name}: {out.get('message', 'error')}")
            for src in out.get("sources_tried") or []:
                sources_all.append({"lottery": db_name, **src})
            if db_name == "Lotería Real":
                priority_done["Lotería Real"] = True
        except Exception as exc:
            errors.append(f"{db_name}: {exc}")
            _seq(
                db_name,
                "error",
                scope_start,
                kind="priority" if db_name == "Lotería Real" else "secondary",
                note=str(exc),
            )

    saved = total_imported + total_updated
    msg = (
        f"Historial RD: {days} días, {saved} guardados "
        f"({total_imported} nuevos, {total_updated} actualizados)."
    )
    if warnings:
        msg += f" {ALT_MESSAGE} Fuentes alternativas: {', '.join(warnings[:8])}."

    out = {
        "ok": bool(saved) or any(d.get("ok") for d in details),
        "status": "updated" if saved else "no_new",
        "pais": "DO",
        "message": msg,
        "mensaje": msg,
        "imported": total_imported,
        "updated": total_updated,
        "ignored": total_ignored,
        "rejected": total_rejected,
        "days": days,
        "dates_found": sorted(dates_union, reverse=True)[:60],
        "errors": errors,
        "details": details,
        "sources_tried": sources_all,
        "warning": bool(warnings),
        "alternate_sources_used": warnings,
        "job_sequence": job_sequence,
        "priority_completed": bool(leidsa_out.get("ok") or total_imported + total_updated > 0) and priority_done.get("Lotería Real", False),
        "soft_budget_seconds": soft_seconds,
    }
    _job_event(
        job_id,
        "JOB_END",
        source="-",
        elapsed_ms=int((time.monotonic() - started) * 1000),
        inserted=total_imported,
        updated=total_updated,
        errors=len(errors),
    )
    return out


def _days_for_range(fecha_desde: str, fecha_hasta: str) -> int:
    try:
        d0 = datetime.strptime((fecha_desde or "")[:10], "%Y-%m-%d").date()
        d1 = datetime.strptime((fecha_hasta or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return 30
    if d0 > d1:
        d0, d1 = d1, d0
    return max(1, (d1 - d0).days + 1)


def actualizar_rd_loteria_rango(
    lottery_name: str,
    *,
    fecha_desde: str,
    fecha_hasta: str,
) -> dict:
    """Backfill/incremental por rango para una lotería RD."""
    lot = find_lottery_in_list(get_all_lotteries(), lottery_name, country="RD")
    if not lot:
        return {"ok": False, "pais": "DO", "message": f"Lotería RD no encontrada: {lottery_name}"}
    lot_type = (lot.get("type") or "").lower()
    if lot_type.startswith("leidsa_") or "leidsa" in (lottery_name or "").lower():
        from services.leidsa_service import update_leidsa_game_incremental

        slug = _leidsa_history_slug(lottery_name)
        if not slug:
            return {"ok": False, "pais": "DO", "message": f"Slug LEIDSA no encontrado: {lottery_name}"}
        out = update_leidsa_game_incremental(
            slug,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
        out["imported"] = int(out.get("inserted") or 0)
        out["pais"] = "DO"
        out["lottery_name"] = lottery_name
        out["range_mode"] = True
        return out

    days = _days_for_range(fecha_desde, fecha_hasta)
    out = actualizar_rd_loteria(lottery_name, days=days)
    out["range_mode"] = True
    out["fecha_desde"] = fecha_desde
    out["fecha_hasta"] = fecha_hasta
    return out


def actualizar_rd_todas_rango(*, fecha_desde: str, fecha_hasta: str) -> dict:
    """Backfill/incremental por rango para todas las loterías RD."""
    days = _days_for_range(fecha_desde, fecha_hasta)
    out = actualizar_rd_todas(days=days)
    out["range_mode"] = True
    out["fecha_desde"] = fecha_desde
    out["fecha_hasta"] = fecha_hasta
    return out
