"""API sites/env RD — Conectate y Loterías Dominicanas (+ fallback sessions)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from scrapers.kiskoo_nuxt_parser import (
    CONECTATE_API,
    CONECTATE_PAYLOAD,
    LD_API,
    LD_PAYLOAD,
    build_game_title_map,
    fetch_json,
    fetch_sessions,
    map_kiskoo_title,
    parse_iso_date,
    sessions_to_rows,
    valid_quiniela,
    _flatten_score_numbers,
)
from scrapers.rd_fallback_scrapers import _draw_time_for, save_rd_rows
from scrapers.rd_http import fetch_rd_json
from services.rd_normalize import normalize_rd_row

logger = logging.getLogger(__name__)

SITES_ENV_URLS = {
    "conectate": [
        "https://api.temp.conectate.com.do/conectate/sites/env",
        "https://api.conectate.com.do/conectate/sites/env",
    ],
    "ld": [
        "https://api.loteriasdominicanas.com/dominicana/sites/env",
    ],
}


def _parse_env_payload(data, *, source_url: str, fecha: str) -> list[dict]:
    """Intenta extraer filas quiniela desde JSON sites/env."""
    rows: list[dict] = []
    items = data if isinstance(data, list) else []
    if isinstance(data, dict):
        items = data.get("data") or data.get("sessions") or data.get("results") or []
        if isinstance(items, dict):
            items = list(items.values())

    for item in items or []:
        if not isinstance(item, dict):
            continue
        title = (
            item.get("title")
            or item.get("game_title")
            or item.get("name")
            or item.get("site")
            or ""
        )
        mapping = map_kiskoo_title(str(title))
        if not mapping:
            continue
        lottery_name, draw_name = mapping
        draw_date = parse_iso_date(item.get("date") or item.get("draw_date") or fecha)
        score = item.get("score") or item.get("numbers") or item.get("result")
        nums = _flatten_score_numbers(score) if score is not None else []
        if len(nums) < 3:
            continue
        nums = nums[:3]
        if not valid_quiniela(nums):
            continue
        rows.append({
            "lottery_name": lottery_name,
            "draw_name": draw_name,
            "draw_time": _draw_time_for(lottery_name, draw_name),
            "draw_date": draw_date,
            "numbers": nums,
            "source_url": source_url,
            "game_title": title,
        })

        for sess in item.get("sessions") or []:
            if not isinstance(sess, dict):
                continue
            dd = parse_iso_date(sess.get("date") or fecha)
            sn = _flatten_score_numbers(sess.get("score"))
            if len(sn) < 3 or not valid_quiniela(sn[:3]):
                continue
            rows.append({
                "lottery_name": lottery_name,
                "draw_name": draw_name,
                "draw_time": _draw_time_for(lottery_name, draw_name),
                "draw_date": dd,
                "numbers": sn[:3],
                "source_url": source_url,
                "game_title": title,
            })
    return rows


def fetch_sites_env_for_date(
    fecha: str,
    *,
    api_kind: str = "conectate",
    lottery_name: str | None = None,
) -> dict:
    urls = SITES_ENV_URLS.get(api_kind, SITES_ENV_URLS["conectate"])
    last_err = None
    for base in urls:
        url = f"{base.rstrip('/')}?date={fecha}"
        out = fetch_rd_json(url, source=f"{api_kind}_sites_env", timeout=12)
        if not out.get("ok"):
            last_err = out.get("error") or f"HTTP {out.get('status_code')}"
            continue
        data = out.get("data")
        rows = _parse_env_payload(data, source_url=url, fecha=fecha)
        norm_rows = []
        for r in rows:
            nr = normalize_rd_row(r)
            if not nr:
                continue
            if lottery_name and nr["lottery_name"].lower() != lottery_name.lower():
                continue
            norm_rows.append(nr)
        if norm_rows:
            return {
                "ok": True,
                "rows": norm_rows,
                "url": url,
                "status_code": out.get("status_code"),
                "parser": "sites-env-v1",
            }
        last_err = "sin filas quiniela en respuesta"
    return {"ok": False, "rows": [], "error": last_err or "sites/env falló", "parser": "sites-env-v1"}


def fetch_sites_env_range(
    *,
    days: int = 30,
    api_kind: str = "conectate",
    lottery_name: str | None = None,
) -> dict:
    """Recorre fechas; si sites/env falla en todas, usa sessions hub una vez."""
    days = max(1, min(int(days or 30), 365))
    all_rows: list[dict] = []
    errors: list[str] = []
    today = datetime.now().date()
    ok_dates = 0

    for offset in range(days):
        fecha = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        res = fetch_sites_env_for_date(fecha, api_kind=api_kind, lottery_name=lottery_name)
        if res.get("ok") and res.get("rows"):
            all_rows.extend(res["rows"])
            ok_dates += 1
        elif res.get("error"):
            errors.append(f"{fecha}: {res['error']}")

    if all_rows:
        return {
            "ok": True,
            "rows": all_rows,
            "rows_found": len(all_rows),
            "ok_dates": ok_dates,
            "errors": errors[:5],
            "parser": "sites-env-v1",
        }

    # Fallback: sessions API (más estable)
    api_base = CONECTATE_API if api_kind == "conectate" else LD_API
    payload_url = CONECTATE_PAYLOAD if api_kind == "conectate" else LD_PAYLOAD
    label = "conectate_api" if api_kind == "conectate" else "ld_api"
    cutoff = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    payload_resp = fetch_json(payload_url, source=f"{label}_payload", timeout=15)
    if not payload_resp.get("ok"):
        return {**payload_resp, "rows": [], "error": payload_resp.get("error") or last_err}
    payload = payload_resp["data"]
    if not isinstance(payload, list):
        return {"ok": False, "rows": [], "error": "payload inválido"}
    game_map = build_game_title_map(payload)
    sess_resp = fetch_sessions(api_base, source=label)
    if not sess_resp.get("ok"):
        return {**sess_resp, "rows": []}
    rows = sessions_to_rows(
        sess_resp["data"],
        game_map,
        cutoff=cutoff,
        source_url=api_base,
    )
    norm = [normalize_rd_row(r) for r in rows]
    norm = [r for r in norm if r]
    if lottery_name:
        norm = [r for r in norm if r["lottery_name"].lower() == lottery_name.lower()]
    return {
        "ok": bool(norm),
        "rows": norm,
        "rows_found": len(norm),
        "parser": "sessions-fallback",
        "fallback": True,
        "errors": errors[:5],
    }


def import_conectate_sites_env(lottery_name: str | None = None, days: int = 30, **_) -> dict:
    res = fetch_sites_env_range(days=days, api_kind="conectate", lottery_name=lottery_name)
    if not res.get("rows"):
        return {**res, "imported": 0, "updated": 0, "fuente_label": "Conectate API sites/env"}
    save = save_rd_rows_inteligente(res["rows"], fuente="conectate_sites_env", days=days, lottery_name=lottery_name)
    return {**res, **save, "fuente_label": "Conectate API sites/env"}


def import_ld_sites_env(lottery_name: str | None = None, days: int = 30, **_) -> dict:
    res = fetch_sites_env_range(days=days, api_kind="ld", lottery_name=lottery_name)
    if not res.get("rows"):
        return {**res, "imported": 0, "updated": 0, "fuente_label": "LD API sites/env"}
    save = save_rd_rows_inteligente(res["rows"], fuente="ld_sites_env", days=days, lottery_name=lottery_name)
    return {**res, **save, "fuente_label": "Loterías Dominicanas API sites/env"}


def save_rd_rows_inteligente(
    rows: list[dict],
    *,
    fuente: str,
    days: int = 30,
    lottery_name: str | None = None,
) -> dict:
    from services.rd_resultados_service import persist_rd_rows
    return persist_rd_rows(rows, fuente=fuente, days=days, lottery_name=lottery_name)
