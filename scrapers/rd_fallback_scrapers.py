"""
Scrapers de respaldo RD — loteriasdominicanas, loteriadominicana, enloteria.
Reutiliza parsers kiskoo (game-block) donde aplica. Solo quinielas RD (3 números 00-99).
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta

from models import format_numbers, get_all_lotteries, upsert_result
from scrapers.rd_http import fetch_rd_url
from services.lottery_normalize import find_lottery_in_list, lottery_names_match, normalize_lottery_name
from services.rd_lottery_config import get_rd_lottery_config, build_logo_main_page

logger = logging.getLogger(__name__)
LOG = "[RD SCRAPER]"

CONECTATE_BASE = "https://www.conectate.com.do"
LD_BASE = "https://loteriasdominicanas.com"
LOTDOM_BASE = "https://www.loteriadominicana.com.do"
ENLOTERIA_BASE = "https://enloteria.com"
CONECTATE_API = "https://api.conectate.com.do"
LD_API = "https://api.loteriasdominicanas.com"
CONECTATE_PAYLOAD = "https://www.conectate.com.do/loterias/_payload.json"
LD_PAYLOAD = "https://loteriasdominicanas.com/_payload.json"

MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

LD_LOGO_MAP: dict[str, tuple[str, str]] = {
    "florida-dia": ("Florida", "tarde"),
    "florida-noche": ("Florida", "noche"),
    "gana-mas": ("Gana Más", "tarde"),
    "la-primera-dia": ("La Primera", "mañana"),
    "la-primera-noche": ("La Primera", "noche"),
    "la-suerte-dia": ("Suerte Dominicana", "tarde"),
    "la-suerte-noche": ("Suerte Dominicana", "noche"),
    "loteria-real": ("Lotería Real", "tarde"),
    "loto-real": ("Lotería Real", "tarde"),
    "quiniela-loteka": ("Loteka", "tarde"),
    "mega-lotto-loteka": ("Loteka", "noche"),
    "mega-chances": ("Loteka", "noche"),
    "quiniela-king-lottery-dia": ("King Lottery", "tarde"),
    "quiniela-king-lottery-noche": ("King Lottery", "noche"),
    "new-york-tarde": ("New York", "tarde"),
    "new-york-noche": ("New York", "noche"),
    "anguila-manana-10am": ("Anguila", "mañana"),
    "anguila-medio-dia-1pm": ("Anguila", "tarde"),
    "anguila-tarde-6pm": ("Anguila", "tardía"),
    "anguila-noche-9pm": ("Anguila", "noche"),
    "quiniela-leidsa": ("Leidsa", "noche"),
    "loto-leidsa": ("Leidsa", "noche"),
}

LD_LOTTERY_PATHS: dict[str, str] = {
    "Florida": "/",
    "King Lottery": "/king-lottery",
    "La Primera": "/la-primera",
    "Suerte Dominicana": "/la-suerte-dominicana",
    "La Suerte Dominicana": "/la-suerte-dominicana",
    "Lotedom": "/lotedom",
    "Loteka": "/loteka",
    "Gana Más": "/",
    "Lotería Nacional": "/loteria-nacional",
    "New York": "/nueva-york",
    "Lotería Real": "/loto-real",
    "Quiniela Real": "/loto-real",
    "Anguila": "/anguila",
    "Leidsa": "/leidsa",
}

LOTDOM_TITLE_MAP: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"gana\s*m[aá]s", re.I), "Gana Más", "tarde"),
    (re.compile(r"nacional.*noche|noche.*nacional", re.I), "Lotería Nacional", "noche"),
    (re.compile(r"nacional.*tarde|nacional.*tard[ií]a|juega.*pega", re.I), "Lotería Nacional", "tardía"),
    (re.compile(r"nacional", re.I), "Lotería Nacional", "tarde"),
    (re.compile(r"quiniela\s*real|real.*quiniela", re.I), "Lotería Real", "tarde"),
    (re.compile(r"quiniela\s*loteka|loteka.*quiniela", re.I), "Loteka", "noche"),
    (re.compile(r"lotedom", re.I), "Lotedom", "tarde"),
    (re.compile(r"la\s*primera", re.I), "La Primera", "mañana"),
    (re.compile(r"la\s*suerte|suerte\s*dom", re.I), "Suerte Dominicana", "tarde"),
    (re.compile(r"king\s*lottery", re.I), "King Lottery", "tarde"),
    (re.compile(r"florida", re.I), "Florida", "tarde"),
    (re.compile(r"new\s*york|nueva\s*york", re.I), "New York", "tarde"),
    (re.compile(r"anguila|anguilla", re.I), "Anguila", "mañana"),
    (re.compile(r"quiniela\s*pal[eé]|pal[eé]", re.I), "Leidsa", "noche"),
    (re.compile(r"pega\s*3", re.I), "Leidsa", "noche"),
    (re.compile(r"leidsa", re.I), "Leidsa", "noche"),
]

ENLOTERIA_TITLE_MAP: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"^gana\s*m[aá]s", re.I), "Gana Más", "tarde"),
    (re.compile(r"^nacional\s*noche", re.I), "Lotería Nacional", "noche"),
    (re.compile(r"^nacional", re.I), "Lotería Nacional", "tarde"),
    (re.compile(r"^real\b", re.I), "Lotería Real", "tarde"),
    (re.compile(r"^loteka", re.I), "Loteka", "noche"),
    (re.compile(r"^lotedom", re.I), "Lotedom", "tarde"),
    (re.compile(r"^la\s*primera", re.I), "La Primera", "mañana"),
    (re.compile(r"^la\s*suerte", re.I), "Suerte Dominicana", "tarde"),
    (re.compile(r"^king\s*lottery\s*d[ií]a", re.I), "King Lottery", "tarde"),
    (re.compile(r"^king\s*lottery\s*noche", re.I), "King Lottery", "noche"),
    (re.compile(r"^florida\s*tarde", re.I), "Florida", "tarde"),
    (re.compile(r"^florida\s*noche", re.I), "Florida", "noche"),
    (re.compile(r"^new\s*york\s*tarde", re.I), "New York", "tarde"),
    (re.compile(r"^new\s*york\s*noche", re.I), "New York", "noche"),
    (re.compile(r"^anguilla?\s*10\s*am|^anguilla?\s*10am", re.I), "Anguila", "mañana"),
    (re.compile(r"^anguilla?\s*1\s*pm|^anguilla?\s*12\s*pm", re.I), "Anguila", "tarde"),
    (re.compile(r"^anguilla?\s*6\s*pm", re.I), "Anguila", "tardía"),
    (re.compile(r"^anguilla?\s*9\s*pm", re.I), "Anguila", "noche"),
    (re.compile(r"^leidsa", re.I), "Leidsa", "noche"),
]


def _pad(n: str) -> str:
    return str(int(n)).zfill(2)


def _valid_quiniela(nums: list[str]) -> bool:
    if len(nums) != 3:
        return False
    for raw in nums:
        try:
            v = int(str(raw).lstrip("0") or "0")
        except (TypeError, ValueError):
            return False
        if v < 0 or v > 99:
            return False
    return True


def _normalize_date_raw(date_raw: str, year_hint: str) -> str | None:
    date_raw = (date_raw or "").strip()
    if not date_raw:
        return None
    if re.match(r"\d{2}-\d{2}-\d{4}", date_raw):
        d, m, y = date_raw.split("-")
        return f"{y}-{m}-{d}"
    if re.match(r"\d{2}-\d{2}", date_raw):
        d, m = date_raw.split("-")
        return f"{year_hint}-{m}-{d}"
    m = re.search(
        r"(\d{1,2})\s+de\s+(\w+)\s*,?\s*(\d{4})",
        date_raw,
        re.I,
    )
    if m:
        day, month_name, year = m.groups()
        mo = MONTHS_ES.get(month_name.lower(), 0)
        if mo:
            return f"{year}-{mo:02d}-{int(day):02d}"
    return None


def _date_param_to_iso(date_param: str) -> str | None:
    if re.match(r"\d{2}-\d{2}-\d{4}", date_param or ""):
        d, m, y = date_param.split("-")
        return f"{y}-{m}-{d}"
    return None


def _extract_three_numbers(chunk: str) -> list[str] | None:
    scores_m = re.search(r'class="game-scores[^"]*"[^>]*>(.*?)</div>', chunk, re.S)
    if not scores_m:
        return None
    nums = re.findall(r'class="score[^"]*"[^>]*>\s*(\d{1,2})\s*<', scores_m.group(1))
    if len(nums) != 3:
        return None
    return [_pad(n) for n in nums]


def _parse_kiskoo_history(html: str, lottery_name: str, draw_name: str, draw_time: str, year_hint: str, source_url: str, days: int = 90) -> list[dict]:
    from scrapers.kiskoo_nuxt_parser import parse_page_quiniela_rows

    return [
        {
            "lottery_name": lottery_name,
            "draw_name": draw_name,
            "draw_time": draw_time,
            "draw_date": row["draw_date"],
            "numbers": row["numbers"],
            "source_url": source_url,
        }
        for row in parse_page_quiniela_rows(html, source_url, days=days)
    ]


def _parse_kiskoo_main(html: str, base_url: str, logo_map: dict, year_hint: str, page_date: str | None = None, days: int = 30) -> list[dict]:
    """Hub/portada — API sessions Kiskoo (HTML hub sin scores SSR)."""
    from scrapers.kiskoo_nuxt_parser import fetch_hub_rows

    api_base = CONECTATE_API if "conectate" in base_url else LD_API
    payload_url = CONECTATE_PAYLOAD if "conectate" in base_url else LD_PAYLOAD
    label = "conectate_api" if "conectate" in base_url else "loteriasdominicanas_api"
    hub = fetch_hub_rows(api_base=api_base, payload_url=payload_url, days=days, source_label=label)
    if not hub.get("ok"):
        return []
    rows = hub.get("rows") or []
    if page_date:
        rows = [r for r in rows if r.get("draw_date") == page_date]
    return [
        {
            "lottery_name": r["lottery_name"],
            "draw_name": r["draw_name"],
            "draw_date": r["draw_date"],
            "numbers": r["numbers"],
            "source_url": r.get("source_url", base_url),
        }
        for r in rows
    ]


def _cutoff_iso(days: int) -> str:
    return (datetime.now() - timedelta(days=max(1, days))).strftime("%Y-%m-%d")


def _dedupe_rows(rows: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    out = []
    for r in rows:
        key = (r.get("lottery_name"), r.get("draw_date"), r.get("draw_name"), tuple(r.get("numbers") or []))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _filter_lottery(rows: list[dict], lottery_name: str) -> list[dict]:
    return [r for r in rows if lottery_names_match(r.get("lottery_name", ""), lottery_name)]


def _filter_days(rows: list[dict], days: int) -> list[dict]:
    cutoff = _cutoff_iso(days)
    return [r for r in rows if (r.get("draw_date") or "") >= cutoff]


def _resolve_db_name(lottery_name: str) -> str:
    lot = find_lottery_in_list(get_all_lotteries(), lottery_name, country="RD")
    return lot["name"] if lot else lottery_name


def _draw_time_for(lottery_name: str, draw_name: str) -> str:
    from lottery_schedules import get_schedule_slot, time_12h_to_24h

    slot = get_schedule_slot(lottery_name, draw_name)
    if slot and slot.get("time"):
        return time_12h_to_24h(slot["time"])
    cfg = get_rd_lottery_config(lottery_name)
    if not cfg:
        return ""
    for page in cfg.get("conectate_pages") or []:
        if page.get("draw_name") == draw_name:
            return page.get("draw_time", "")
    draw_map = cfg.get("draw_map") or {}
    if draw_name in draw_map:
        return time_12h_to_24h(draw_map[draw_name])
    return ""


def save_rd_rows(
    rows: list[dict],
    *,
    fuente: str,
    days: int = 30,
    lottery_name: str | None = None,
) -> dict:
    """Guarda filas válidas; nunca borra existentes."""
    lotteries = get_all_lotteries()
    cutoff = _cutoff_iso(days)
    imported = updated = 0
    errors: list[str] = []
    saved_rows: list[dict] = []

    for row in rows:
        nums = row.get("numbers") or []
        if not _valid_quiniela(nums):
            continue
        db_name = _resolve_db_name(row.get("lottery_name") or lottery_name or "")
        if lottery_name and not lottery_names_match(db_name, lottery_name):
            continue
        lot = find_lottery_in_list(lotteries, db_name, country="RD")
        if not lot:
            continue
        dd = row.get("draw_date") or ""
        if dd and dd < cutoff:
            continue
        draw_name = row.get("draw_name") or "tarde"
        draw_time = row.get("draw_time") or _draw_time_for(db_name, draw_name)
        try:
            _, action = upsert_result(
                lot["id"],
                draw_name,
                draw_time,
                dd,
                format_numbers(nums),
                source_url=row.get("source_url"),
                confirmed=1,
                fuente=fuente,
                estado="publicado",
            )
            updated += action == "updated"
            imported += action == "inserted"
            saved_rows.append({**row, "lottery_name": db_name, "draw_time": draw_time})
            from models import count_results_for_date
            from services.resultados_log import log_resultados

            total_dia = count_results_for_date(lot["id"], dd)
            log_resultados(
                fecha_consultada=dd,
                cantidad_api=len(rows),
                loteria=db_name,
                sorteo=draw_name,
                hora=draw_time,
                accion=action,
                total_fecha_bd=total_dia,
            )
        except Exception as exc:
            errors.append(str(exc))
            logger.warning("%s error guardando %s: %s", LOG, db_name, exc)

    saved = imported + updated
    return {
        "ok": saved > 0 or (bool(rows) and not errors),
        "imported": imported,
        "updated": updated,
        "rows_found": len(rows),
        "rows_saved": len(saved_rows),
        "errors": errors[:10],
        "saved_rows": saved_rows,
    }


def import_conectate_api(lottery_name: str, days: int = 30, *, force_refresh: bool = False) -> dict:
    """API Kiskoo sessions — Conectate, luego Loterías Dominicanas si 403 o sin filas."""
    from scrapers.kiskoo_nuxt_parser import (
        CONECTATE_API,
        CONECTATE_PAYLOAD,
        LD_API,
        LD_PAYLOAD,
        fetch_hub_rows,
    )

    attempts = [
        (CONECTATE_API, CONECTATE_PAYLOAD, "Conectate API", "conectate_api"),
        (LD_API, LD_PAYLOAD, "Loterías Dominicanas API", "ld_api"),
    ]
    errors: list[str] = []
    for api_base, payload_url, label, key in attempts:
        hub = fetch_hub_rows(
            api_base=api_base,
            payload_url=payload_url,
            days=days,
            source_label=key,
            force_refresh=force_refresh,
        )
        status = hub.get("status_code")
        if status == 403 or (not hub.get("ok") and status and int(status) >= 400):
            errors.append(f"{label}: HTTP {status}")
            logger.warning("%s %s HTTP %s — probando siguiente API", LOG, label, status)
            continue
        if not hub.get("ok"):
            err = hub.get("error") or "sin datos"
            errors.append(f"{label}: {err}")
            continue
        raw = _filter_lottery(hub.get("rows") or [], lottery_name)
        raw = _dedupe_rows(_filter_days(raw, days))
        if not raw:
            errors.append(f"{label}: 0 filas para {lottery_name}")
            continue
        batch = save_rd_rows(raw, fuente="conectate_api", days=days, lottery_name=lottery_name)
        return {
            **batch,
            "fuente": "conectate_api",
            "fuente_label": label,
            "parser": hub.get("parser") or "nuxt-sessions-v2",
            "url": hub.get("url"),
            "status_code": status,
            "elapsed": hub.get("elapsed"),
            "message": f"{label}: {batch.get('rows_saved', 0)} sorteos.",
        }
    return {
        "ok": False,
        "fuente": "conectate_api",
        "fuente_label": "Conectate API",
        "rows_found": 0,
        "imported": 0,
        "updated": 0,
        "errors": errors,
        "message": errors[-1] if errors else "API Kiskoo sin filas",
        "error": errors[-1] if errors else "API Kiskoo sin filas",
    }


def import_conectate_hub(lottery_name: str, days: int = 30) -> dict:
    """Fallback: página hub Conectate (ej. /loterias/loto-real)."""
    cfg = get_rd_lottery_config(lottery_name) or {}
    path = cfg.get("fallback_conectate_path") or cfg.get("conectate_hub") or ""
    if not path and cfg.get("conectate_pages"):
        path = cfg["conectate_pages"][0]["path"].rsplit("/", 1)[0]
    if not path:
        key = normalize_lottery_name(lottery_name)
        defaults = {
            "quiniela_real": "/loterias/loto-real",
            "loteria_nacional": "/loterias/nacional/quiniela",
            "loteka": "/loterias/loteka/quiniela-mega-decenas",
        }
        path = defaults.get(key, "/loterias/")
    url = CONECTATE_BASE.rstrip("/") + path
    page = fetch_rd_url(url, source="conectate_hub")
    if not page.get("ok"):
        return {**page, "fuente": "conectate", "rows_found": 0, "imported": 0, "updated": 0}

    year_hint = str(datetime.now().year)
    db_name = _resolve_db_name(lottery_name)
    raw: list[dict] = []
    for pcfg in (cfg.get("conectate_pages") or []):
        raw.extend(
            _parse_kiskoo_history(
                page["html"],
                db_name,
                pcfg["draw_name"],
                pcfg.get("draw_time", ""),
                year_hint,
                page["url"],
            )
        )
    if not raw:
        logo_map = build_logo_main_page()
        raw = _parse_kiskoo_main(page["html"], page["url"], logo_map, year_hint, days=days)
        raw = _filter_lottery(raw, lottery_name)

    if not raw:
        from scrapers.kiskoo_nuxt_parser import fetch_hub_rows

        hub = fetch_hub_rows(days=days, source_label="conectate_api")
        if hub.get("ok"):
            raw = _filter_lottery(hub.get("rows") or [], lottery_name)
        elif hub.get("error"):
            return {
                **hub,
                "fuente": "conectate",
                "fuente_label": "Conectate.com.do",
                "rows_found": 0,
                "imported": 0,
                "updated": 0,
                "message": hub.get("error"),
            }

    raw = _dedupe_rows(_filter_lottery(_filter_days(raw, days), lottery_name))
    batch = save_rd_rows(raw, fuente="conectate_rd", days=days, lottery_name=lottery_name)
    return {
        **batch,
        "fuente": "conectate",
        "fuente_label": "Conectate.com.do",
        "url": url,
        "status_code": page.get("status_code"),
        "message": f"Conectate hub {lottery_name}: {batch.get('rows_saved', 0)} sorteos.",
    }


def import_loteriasdominicanas(lottery_name: str, days: int = 30) -> dict:
    path = LD_LOTTERY_PATHS.get(lottery_name) or LD_LOTTERY_PATHS.get(_resolve_db_name(lottery_name)) or "/"
    url = LD_BASE.rstrip("/") + path
    page = fetch_rd_url(url, source="loteriasdominicanas")
    if not page.get("ok"):
        return {**page, "fuente": "loteriasdominicanas", "rows_found": 0, "imported": 0, "updated": 0}

    year_hint = str(datetime.now().year)
    db_name = _resolve_db_name(lottery_name)
    cfg = get_rd_lottery_config(lottery_name) or {}
    raw: list[dict] = []
    for pcfg in (cfg.get("conectate_pages") or []):
        raw.extend(
            _parse_kiskoo_history(
                page["html"],
                db_name,
                pcfg["draw_name"],
                pcfg.get("draw_time", ""),
                year_hint,
                page["url"],
            )
        )
    if not raw:
        raw = _parse_kiskoo_main(page["html"], page["url"], LD_LOGO_MAP, year_hint, days=days)
        raw = _filter_lottery(raw, lottery_name)

    if not raw:
        from scrapers.kiskoo_nuxt_parser import fetch_hub_rows

        hub = fetch_hub_rows(
            api_base=LD_API,
            payload_url=LD_PAYLOAD,
            days=days,
            source_label="loteriasdominicanas_api",
        )
        if hub.get("ok"):
            raw = _filter_lottery(hub.get("rows") or [], lottery_name)

    for days_ago in range(min(days, 14)):
        dt = datetime.now() - timedelta(days=days_ago)
        date_param = dt.strftime("%d-%m-%Y")
        hub = fetch_rd_url(f"{LD_BASE}/?date={date_param}", source="loteriasdominicanas")
        if not hub.get("ok"):
            hub = fetch_rd_url(LD_BASE + "/", source="loteriasdominicanas")
        if hub.get("ok"):
            page_date = _date_param_to_iso(date_param) if days_ago == 0 else None
            raw.extend(_parse_kiskoo_main(hub["html"], hub["url"], LD_LOGO_MAP, str(dt.year), page_date))
        time.sleep(0.15)

    raw = _dedupe_rows(_filter_lottery(_filter_days(raw, days), lottery_name))
    batch = save_rd_rows(raw, fuente="loteriasdominicanas", days=days, lottery_name=lottery_name)
    return {
        **batch,
        "fuente": "loteriasdominicanas",
        "fuente_label": "LoteriasDominicanas.com",
        "url": url,
        "status_code": page.get("status_code"),
        "message": f"LoteriasDominicanas {lottery_name}: {batch.get('rows_saved', 0)} sorteos.",
    }


def _parse_loteriadominicana_html(html: str, source_url: str) -> list[dict]:
    from services.scraper_deps import get_beautiful_soup

    soup = get_beautiful_soup()(html, "lxml")
    rows: list[dict] = []
    for item in soup.select(".result-item"):
        title = item.get_text(" ", strip=True)
        title_short = title[:80]
        lottery_name = draw_name = None
        for pat, lname, dname in LOTDOM_TITLE_MAP:
            if pat.search(title_short):
                lottery_name, draw_name = lname, dname
                break
        if not lottery_name:
            continue
        balls = []
        for span in item.select(".result-item-ball-content span, .result-item-ball"):
            t = span.get_text(strip=True)
            if re.match(r"^\d{1,2}$", t):
                balls.append(_pad(t))
        if len(balls) >= 3:
            nums = balls[:3] if len(balls) == 3 else balls[-3:]
        else:
            nums = re.findall(r"\b(\d{2})\b", title)
            if len(nums) < 3:
                continue
            nums = [_pad(n) for n in nums[-3:]]
        if not _valid_quiniela(nums):
            continue
        date_m = re.search(r"(\d{2}-\d{2}-\d{4})", title)
        draw_date = _normalize_date_raw(date_m.group(1), str(datetime.now().year)) if date_m else None
        if not draw_date:
            continue
        rows.append({
            "lottery_name": lottery_name,
            "draw_name": draw_name,
            "draw_date": draw_date,
            "numbers": nums,
            "source_url": source_url,
        })
    return rows


def import_loteriadominicana(lottery_name: str, days: int = 30) -> dict:
    url = LOTDOM_BASE + "/"
    page = fetch_rd_url(url, source="loteriadominicana")
    if not page.get("ok"):
        return {**page, "fuente": "loteriadominicana", "rows_found": 0, "imported": 0, "updated": 0}

    raw = _filter_lottery(
        _filter_days(_parse_loteriadominicana_html(page["html"], page["url"]), days),
        lottery_name,
    )
    raw = _dedupe_rows(raw)
    batch = save_rd_rows(raw, fuente="loteriadominicana", days=days, lottery_name=lottery_name)
    return {
        **batch,
        "fuente": "loteriadominicana",
        "fuente_label": "LoteriaDominicana.com.do",
        "url": url,
        "status_code": page.get("status_code"),
        "message": f"LoteriaDominicana {lottery_name}: {batch.get('rows_saved', 0)} sorteos.",
    }


def _parse_enloteria_html(html: str, source_url: str) -> list[dict]:
    from services.scraper_deps import get_beautiful_soup

    soup = get_beautiful_soup()(html, "lxml")
    rows: list[dict] = []
    for card in soup.select(".result-card"):
        txt = card.get_text(" ", strip=True)
        if re.search(r"av[ií]same|pendiente|proxim", txt, re.I):
            continue
        lottery_name = draw_name = None
        for pat, lname, dname in ENLOTERIA_TITLE_MAP:
            if pat.search(txt):
                lottery_name, draw_name = lname, dname
                break
        if not lottery_name:
            continue
        nums = re.findall(r"\b(\d{2})\b", txt)
        if len(nums) < 3:
            continue
        nums = [_pad(n) for n in nums[-3:]]
        if not _valid_quiniela(nums):
            continue
        date_m = re.search(
            r"(\d{1,2})\s+de\s+(\w+)\s*,?\s*(\d{4})",
            txt,
            re.I,
        )
        draw_date = None
        if date_m:
            day, month_name, year = date_m.groups()
            mo = MONTHS_ES.get(month_name.lower(), 0)
            if mo:
                draw_date = f"{year}-{mo:02d}-{int(day):02d}"
        if not draw_date:
            draw_date = datetime.now().strftime("%Y-%m-%d")
        rows.append({
            "lottery_name": lottery_name,
            "draw_name": draw_name,
            "draw_date": draw_date,
            "numbers": nums,
            "source_url": source_url,
        })
    return rows


def import_enloteria(lottery_name: str, days: int = 30) -> dict:
    url = ENLOTERIA_BASE + "/"
    page = fetch_rd_url(url, source="enloteria")
    if not page.get("ok"):
        return {**page, "fuente": "enloteria", "rows_found": 0, "imported": 0, "updated": 0}

    raw = _filter_lottery(
        _filter_days(_parse_enloteria_html(page["html"], page["url"]), days),
        lottery_name,
    )
    raw = _dedupe_rows(raw)
    batch = save_rd_rows(raw, fuente="enloteria", days=days, lottery_name=lottery_name)
    return {
        **batch,
        "fuente": "enloteria",
        "fuente_label": "EnLoteria.com",
        "url": url,
        "status_code": page.get("status_code"),
        "message": f"EnLoteria {lottery_name}: {batch.get('rows_saved', 0)} sorteos.",
    }
