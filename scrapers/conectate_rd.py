"""
Importador Conectate RD — Anguila lee TODO el historial visible + fecha principal.
Fuente: https://www.conectate.com.do/loterias/
"""

import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode

from models import upsert_result, format_numbers, get_all_lotteries, get_db
from scrapers.rd_http import fetch_rd_url
from services.lottery_normalize import (
    find_lottery_in_list,
    lottery_names_match,
    normalize_lottery_name,
)
from services.rd_lottery_config import (
    build_conectate_draw_pages,
    build_logo_main_page,
    get_rd_lottery_config,
)

BASE_URL = "https://www.conectate.com.do"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-DO,es;q=0.9,en;q=0.8",
}

CONECTATE_DRAW_PAGES = build_conectate_draw_pages()

ANGUILA_DRAW_PAGES = [
    {"path": "/loterias/anguilla/anguila-10-am", "draw_name": "mañana", "draw_time": "10:00", "time_display": "10:00 AM"},
    {"path": "/loterias/anguilla/anguila-12-pm", "draw_name": "tarde", "draw_time": "13:00", "time_display": "1:00 PM"},
    {"path": "/loterias/anguilla/anguila-5-pm", "draw_name": "tardía", "draw_time": "18:00", "time_display": "6:00 PM"},
    {"path": "/loterias/anguilla/anguila-9-pm", "draw_name": "noche", "draw_time": "21:00", "time_display": "9:00 PM"},
]

ANGUILA_BLOCKS = [
    {"block_text": "Anguila 10:00 AM", "draw_name": "mañana", "draw_time": "10:00", "time_display": "10:00 AM"},
    {"block_text": "Anguila 1:00 PM", "draw_name": "tarde", "draw_time": "13:00", "time_display": "1:00 PM"},
    {"block_text": "Anguila 6:00 PM", "draw_name": "tardía", "draw_time": "18:00", "time_display": "6:00 PM"},
    {"block_text": "Anguila 9:00 PM", "draw_name": "noche", "draw_time": "21:00", "time_display": "9:00 PM"},
]

LOGO_MAIN_PAGE = build_logo_main_page()


def _extract_block_chunk(html, label):
    idx = html.find(label)
    if idx == -1:
        return None
    start = html.rfind("game-block", 0, idx)
    if start == -1:
        start = max(0, idx - 500)
    end = html.find("game-block", idx + len(label))
    if end == -1:
        end = idx + 1500
    return html[start:end]


def _extract_three_numbers(chunk):
    """Legacy game-block — delega al parser Nuxt si no hay marcadores viejos."""
    if "game-scores" in chunk:
        scores_m = re.search(r'class="game-scores[^"]*"[^>]*>(.*?)</div>', chunk, re.S)
        if scores_m:
            nums = re.findall(r'class="score[^"]*"[^>]*>\s*(\d{1,2})\s*<', scores_m.group(1))
            if len(nums) == 3:
                return [n.zfill(2) for n in nums]
    return None


def _parse_draw_page_nuxt(html: str, source_url: str, days: int = 90) -> list[dict]:
    from scrapers.kiskoo_nuxt_parser import parse_page_quiniela_rows

    return parse_page_quiniela_rows(html, source_url, days=days)


def _date_param_to_iso(date_param):
    if not date_param:
        return None
    date_param = date_param.strip()
    if re.match(r"\d{2}-\d{2}-\d{4}", date_param):
        d, m, y = date_param.split("-")
        return f"{y}-{m}-{d}"
    return None


def _normalize_date(date_raw, year_hint):
    date_raw = (date_raw or "").strip()
    if not date_raw:
        return None
    if re.match(r"\d{2}-\d{2}-\d{4}", date_raw):
        d, m, y = date_raw.split("-")
        return f"{y}-{m}-{d}"
    if re.match(r"\d{2}-\d{2}", date_raw):
        d, m = date_raw.split("-")
        return f"{year_hint}-{m}-{d}"
    return None


def parse_anguila_history_page(html, cfg, year_hint, source_url):
    """Historial visible en página de tanda Anguila (Nuxt/Kiskoo)."""
    from scrapers.kiskoo_nuxt_parser import parse_page_quiniela_rows

    results = []
    for row in parse_page_quiniela_rows(html, source_url, days=90):
        results.append({
            "lottery_name": "Anguila",
            "draw_name": cfg["draw_name"],
            "draw_time": cfg["draw_time"],
            "time_display": cfg["time_display"],
            "draw_date": row["draw_date"],
            "numbers": row["numbers"],
            "source_url": source_url,
        })
    return results


def parse_anguila_blocks(html, year_hint, source_url, page_date=None, hub: dict | None = None):
    """Bloques Anguila desde hub — usa API sessions (el hub Nuxt ya no incluye scores SSR)."""
    from scrapers.kiskoo_nuxt_parser import fetch_hub_rows

    if hub is None:
        hub = fetch_hub_rows(days=30)
    if not hub.get("ok"):
        return []
    target_date = page_date
    results = []
    for row in hub.get("rows") or []:
        if row.get("lottery_name") != "Anguila":
            continue
        if target_date and row.get("draw_date") != target_date:
            continue
        draw_name = row.get("draw_name", "mañana")
        cfg = next((b for b in ANGUILA_BLOCKS if b["draw_name"] == draw_name), None)
        results.append({
            "lottery_name": "Anguila",
            "draw_name": draw_name,
            "draw_time": cfg["draw_time"] if cfg else "",
            "time_display": cfg["time_display"] if cfg else "",
            "draw_date": row["draw_date"],
            "numbers": row["numbers"],
            "source_url": source_url,
        })
    return results


def scrape_anguila_all_visible(scraper, year_hint, days_back=60):
    from scrapers.kiskoo_nuxt_parser import fetch_hub_rows

    all_rows: list[dict] = []
    for cfg in ANGUILA_DRAW_PAGES:
        page = scraper.fetch_page(cfg["path"])
        if page.get("ok"):
            all_rows.extend(parse_anguila_history_page(page["html"], cfg, year_hint, page["url"]))
        time.sleep(0.3)

    hub = fetch_hub_rows(days=days_back)
    if hub.get("ok"):
        for row in hub.get("rows") or []:
            if row.get("lottery_name") != "Anguila":
                continue
            draw_name = row.get("draw_name", "mañana")
            block_cfg = next((b for b in ANGUILA_BLOCKS if b["draw_name"] == draw_name), None)
            all_rows.append({
                "lottery_name": "Anguila",
                "draw_name": draw_name,
                "draw_time": block_cfg["draw_time"] if block_cfg else "",
                "time_display": block_cfg["time_display"] if block_cfg else "",
                "draw_date": row["draw_date"],
                "numbers": row["numbers"],
                "source_url": row.get("source_url", BASE_URL),
            })

    dates = [r["draw_date"] for r in all_rows if r.get("draw_date")]
    fecha_max = max(dates) if dates else None
    return all_rows, fecha_max


def _parse_session_blocks(html, days: int = 90):
    return _parse_draw_page_nuxt(html, "", days=days)


def _parse_main_page_blocks(html, year_hint, page_date=None, days: int = 30, hub: dict | None = None):
    """Hub por fecha — API sessions (HTML Nuxt del hub ya no trae scores)."""
    from scrapers.kiskoo_nuxt_parser import fetch_hub_rows

    if hub is None:
        hub = fetch_hub_rows(days=days)
    if not hub.get("ok"):
        return []
    rows = []
    for row in hub.get("rows") or []:
        if page_date and row.get("draw_date") != page_date:
            continue
        rows.append({
            "lottery_name": row["lottery_name"],
            "draw_name": row["draw_name"],
            "draw_date": row["draw_date"],
            "numbers": row["numbers"],
            "source_url": row.get("source_url", BASE_URL + "/loterias/"),
        })
    return rows


def _hub_rows_for_lottery(days: int, lottery_name: str, hub: dict | None = None) -> tuple[list[dict], dict]:
    """Una sola llamada API hub; filtra por lotería."""
    from scrapers.kiskoo_nuxt_parser import fetch_hub_rows

    if hub is None:
        hub = fetch_hub_rows(days=days, source_label="conectate_api")
    if not hub.get("ok"):
        return [], hub
    rows = [
        {**row, "lottery_name": lottery_name}
        for row in (hub.get("rows") or [])
        if lottery_names_match(row.get("lottery_name", ""), lottery_name)
    ]
    return rows, hub


def _find_lottery_id(lotteries, name):
    lot = find_lottery_in_list(lotteries, name, country="RD")
    return lot["id"] if lot else None


def _cutoff_iso(days: int) -> str:
    return (datetime.now() - timedelta(days=max(1, days))).strftime("%Y-%m-%d")


def _filter_rows_by_days(rows: list, days: int, draw_name: str | None = None) -> list:
    """Filtra filas >= cutoff; opcionalmente por tanda."""
    cutoff = _cutoff_iso(days)
    out = []
    for r in rows:
        if draw_name and r.get("draw_name") != draw_name:
            continue
        dd = r.get("draw_date") or ""
        if dd and dd >= cutoff:
            out.append(r)
    return out


def _dedupe_rows(rows: list) -> list:
    seen: set[tuple] = set()
    out = []
    for r in rows:
        key = (r.get("draw_date"), r.get("draw_name"), tuple(r.get("numbers") or []))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


class ConectateRDScraper:
    source_key = "conectate_rd"
    base_url = BASE_URL

    def __init__(self):
        self._hub_cache: dict | None = None
        self._hub_cache_days: int | None = None

    def get_hub_rows(self, days: int = 30) -> dict:
        if self._hub_cache is None or self._hub_cache_days != days:
            from scrapers.kiskoo_nuxt_parser import fetch_hub_rows

            self._hub_cache = fetch_hub_rows(days=days, source_label="conectate_api")
            self._hub_cache_days = days
        return self._hub_cache

    def fetch_page(self, path="", params=None):
        url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        if params:
            url = f"{url}?{urlencode(params)}"
        page = fetch_rd_url(url, source="conectate_rd")
        if page.get("ok"):
            return {
                "ok": True,
                "html": page["html"],
                "url": page.get("url", url),
                "status_code": page.get("status_code"),
            }
        return {
            "ok": False,
            "message": page.get("error") or page.get("message") or "Error HTTP",
            "status_code": page.get("status_code"),
        }

    def scrape_draw_page(self, path, draw_name, draw_time, year_hint, days: int = 90):
        page = self.fetch_page(path)
        if not page.get("ok"):
            return []
        rows = []
        for s in _parse_draw_page_nuxt(page["html"], page.get("url", ""), days=days):
            rows.append({
                "draw_name": draw_name,
                "draw_time": draw_time,
                "draw_date": s["draw_date"],
                "numbers": s["numbers"],
                "source_url": page["url"],
            })
        return rows

    def scrape_main_for_date(self, date_param, year_hint, days: int = 30):
        page_date = _date_param_to_iso(date_param)
        return _parse_main_page_blocks(
            "", year_hint, page_date=page_date, days=days, hub=self.get_hub_rows(days)
        )


def import_conectate_rd_new_lotteries_only(days_back=30, delay_seconds=0.25):
    """
    Misma lógica que import_conectate_rd (portada por fecha + páginas de tanda),
    solo para loterías nuevas (Florida, King Lottery, New York).
    No modifica ni reescribe el flujo de las loterías viejas.
    """
    from services.new_lotteries import is_new_rd_lottery

    scraper = ConectateRDScraper()
    lotteries = get_all_lotteries()
    new_lots = {lot["id"]: lot for lot in lotteries if is_new_rd_lottery(lot)}
    if not new_lots:
        return {
            "ok": True,
            "source": "conectate_rd_new",
            "imported": 0,
            "updated": 0,
            "message": "No hay loterías nuevas configuradas.",
            "dates_found": [],
        }

    imported = updated = 0
    errors: list[str] = []
    cutoff = _cutoff_iso(days_back)
    years = {str(datetime.now().year)}
    if days_back > 60:
        years.add(str(datetime.now().year - 1))

    def _save_row(lottery_id: int, row: dict, draw_time: str | None = None) -> None:
        nonlocal imported, updated
        dd = row.get("draw_date") or ""
        if dd and dd < cutoff:
            return
        dt = draw_time if draw_time is not None else row.get("draw_time", "")
        try:
            _, action = upsert_result(
                lottery_id,
                row["draw_name"],
                dt,
                dd,
                format_numbers(row["numbers"]),
                source_url=row.get("source_url"),
                confirmed=1,
                fuente="conectate_rd",
                estado="publicado",
            )
            updated += action == "updated"
            imported += action == "inserted"
        except Exception as exc:
            errors.append(str(exc))

    try:
        for cfg in CONECTATE_DRAW_PAGES:
            lid = _find_lottery_id(lotteries, cfg["lottery_name"])
            if not lid or lid not in new_lots:
                continue
            for year_hint in years:
                for row in scraper.scrape_draw_page(
                    cfg["path"], cfg["draw_name"], cfg["draw_time"], year_hint
                ):
                    _save_row(lid, row, cfg["draw_time"])
            time.sleep(delay_seconds)

        for days_ago in range(days_back):
            dt = datetime.now() - timedelta(days=days_ago)
            date_param = dt.strftime("%d-%m-%Y")
            for row in scraper.scrape_main_for_date(date_param, str(dt.year)):
                lot = find_lottery_in_list(lotteries, row.get("lottery_name", ""), "RD")
                if lot and lot["id"] in new_lots:
                    _save_row(lot["id"], row, row.get("draw_time", ""))
            time.sleep(delay_seconds)
    except Exception as exc:
        errors.append(str(exc))

    dates_found: set[str] = set()
    with get_db() as conn:
        for lid in new_lots:
            rows = conn.execute(
                """SELECT DISTINCT draw_date FROM lottery_results
                   WHERE lottery_id = ? AND draw_date >= ? ORDER BY draw_date DESC""",
                (lid, cutoff),
            ).fetchall()
            dates_found.update(r["draw_date"] for r in rows if r["draw_date"])

    saved = imported + updated
    return {
        "ok": True,
        "source": "conectate_rd_new",
        "imported": imported,
        "updated": updated,
        "errors": errors[:15],
        "days": days_back,
        "dates_found": sorted(dates_found, reverse=True),
        "lotteries": [new_lots[i]["name"] for i in new_lots],
        "supports_full_history": len(dates_found) > 3,
        "message": (
            f"Loterías nuevas: {days_back} días revisados, {saved} guardados "
            f"({imported} nuevos, {updated} actualizados)."
        ),
    }


def import_conectate_lottery_bulk_style(lottery_name: str, days_back: int = 30) -> dict:
    """Import estilo bulk para UNA lotería nueva (misma lógica que import_conectate_rd)."""
    from services.new_lotteries import is_new_rd_lottery

    lot = find_lottery_in_list(get_all_lotteries(), lottery_name, country="RD")
    if not lot:
        return {"ok": False, "message": f"Lotería '{lottery_name}' no encontrada."}
    if not is_new_rd_lottery(lot):
        return import_conectate_lottery_history(lottery_name, days=days_back)

    scraper = ConectateRDScraper()
    lotteries = get_all_lotteries()
    lottery_id = lot["id"]
    db_name = lot["name"]
    imported = updated = 0
    errors: list[str] = []
    cutoff = _cutoff_iso(days_back)
    years = {str(datetime.now().year)}

    def _save(row: dict, draw_time: str | None = None) -> None:
        nonlocal imported, updated
        dd = row.get("draw_date") or ""
        if dd and dd < cutoff:
            return
        dt = draw_time if draw_time is not None else row.get("draw_time", "")
        try:
            _, action = upsert_result(
                lottery_id,
                row["draw_name"],
                dt,
                dd,
                format_numbers(row["numbers"]),
                source_url=row.get("source_url"),
                confirmed=1,
                fuente="conectate_rd",
                estado="publicado",
            )
            updated += action == "updated"
            imported += action == "inserted"
        except Exception as exc:
            errors.append(str(exc))

    pages = [
        p for p in CONECTATE_DRAW_PAGES
        if lottery_names_match(p.get("lottery_name", ""), db_name)
    ]
    cfg = get_rd_lottery_config(db_name)
    if cfg and cfg.get("conectate_pages"):
        pages = cfg["conectate_pages"]

    for pcfg in pages:
        for year_hint in years:
            for row in scraper.scrape_draw_page(
                pcfg["path"], pcfg["draw_name"], pcfg["draw_time"], year_hint
            ):
                _save(row, pcfg["draw_time"])
        time.sleep(0.2)

    for days_ago in range(days_back):
        dt = datetime.now() - timedelta(days=days_ago)
        date_param = dt.strftime("%d-%m-%Y")
        for row in scraper.scrape_main_for_date(date_param, str(dt.year), days=days_back):
            if lottery_names_match(row.get("lottery_name", ""), db_name):
                _save(row, row.get("draw_time", ""))
        time.sleep(0.02)

    # Complemento hub solo si hace falta (evita timeout de sessions API)
    if imported + updated == 0:
        hub_rows, hub = _hub_rows_for_lottery(days_back, db_name, scraper.get_hub_rows(days_back))
        if not hub.get("ok") and hub.get("error"):
            errors.append(str(hub.get("error")))
        for row in hub_rows:
            _save(row, row.get("draw_time", ""))

    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM lottery_results WHERE lottery_id = ?",
            (lottery_id,),
        ).fetchone()[0]
        dates = [
            r["draw_date"]
            for r in conn.execute(
                """SELECT DISTINCT draw_date FROM lottery_results
                   WHERE lottery_id = ? AND draw_date >= ?
                   ORDER BY draw_date DESC""",
                (lottery_id, cutoff),
            ).fetchall()
        ]

    saved = imported + updated
    return {
        "ok": True,
        "source": "conectate_rd_bulk",
        "imported": imported,
        "updated": updated,
        "days": days_back,
        "dates_found": dates,
        "total_for_lottery": total,
        "supports_full_history": len(dates) > 3,
        "errors": errors[:5],
        "message": (
            f"{db_name}: historial {days_back} días — {total} en DB, "
            f"{len(dates)} fechas ({saved} guardados ahora)."
        ),
    }


def import_conectate_rd(days_back=60, delay_seconds=0.4):
    scraper = ConectateRDScraper()
    lotteries = get_all_lotteries()
    imported = updated = 0
    errors = []

    def _save_row(lottery_id, row, draw_time=None):
        nonlocal imported, updated
        lot = next((l for l in lotteries if l["id"] == lottery_id), None)
        if lot and lot.get("country") != "RD":
            return
        dt = draw_time if draw_time is not None else row.get("draw_time", "")
        try:
            _, action = upsert_result(
                lottery_id, row["draw_name"], dt, row["draw_date"],
                format_numbers(row["numbers"]),
                source_url=row.get("source_url"), confirmed=1,
            )
            updated += action == "updated"
            imported += action == "inserted"
        except Exception as e:
            errors.append(str(e))

    try:
        for cfg in CONECTATE_DRAW_PAGES:
            lid = _find_lottery_id(lotteries, cfg["lottery_name"])
            if not lid:
                continue
            for row in scraper.scrape_draw_page(cfg["path"], cfg["draw_name"], cfg["draw_time"], str(datetime.now().year)):
                _save_row(lid, row, cfg["draw_time"])
            time.sleep(delay_seconds)

        anguila_id = _find_lottery_id(lotteries, "Anguila")
        if anguila_id:
            rows, _ = scrape_anguila_all_visible(scraper, str(datetime.now().year), days_back)
            for row in rows:
                _save_row(anguila_id, row, row.get("draw_time", ""))
            time.sleep(delay_seconds)

        for days_ago in range(days_back):
            dt = datetime.now() - timedelta(days=days_ago)
            date_param = dt.strftime("%d-%m-%Y")
            for row in scraper.scrape_main_for_date(date_param, str(dt.year)):
                lot = find_lottery_in_list(lotteries, row.get("lottery_name", ""), "RD")
                if lot:
                    _save_row(lot["id"], row, "")
            time.sleep(delay_seconds)
    except Exception as e:
        errors.append(str(e))

    return {
        "ok": True,
        "source": "conectate_rd",
        "imported": imported,
        "updated": updated,
        "errors": errors[:20],
        "message": f"Conectate RD: {imported} nuevos, {updated} actualizados.",
    }


def import_conectate_lottery_history(lottery_name: str, days: int = 90, draw_name: str | None = None) -> dict:
    """Importa historial Conectate (portada por fecha + páginas de tanda)."""
    cfg = get_rd_lottery_config(lottery_name)
    if cfg and cfg.get("source") == "leidsa":
        return {
            "ok": False,
            "message": "Leidsa se actualiza desde leidsa.com (módulo LEIDSA).",
        }
    scraper = ConectateRDScraper()
    lotteries = get_all_lotteries()
    lot = find_lottery_in_list(lotteries, lottery_name, country="RD")
    if not lot:
        return {"ok": False, "message": f"Lotería RD '{lottery_name}' no encontrada."}
    lottery_id = lot["id"]
    db_name = lot["name"]
    cutoff = _cutoff_iso(days)
    year_hint = str(datetime.now().year)
    raw_rows: list = []
    only_today_warning = False
    hub_errors: list[str] = []

    is_anguila = (cfg and cfg.get("anguila")) or normalize_lottery_name(lottery_name) == "anguila"
    if is_anguila:
        rows_vis, _ = scrape_anguila_all_visible(scraper, year_hint, days_back=days)
        raw_rows.extend(rows_vis)
    else:
        pages = (cfg or {}).get("conectate_pages") or []
        if not pages:
            pages = [
                p for p in CONECTATE_DRAW_PAGES
                if lottery_names_match(p.get("lottery_name", ""), db_name)
            ]
        page_dates_from_draw_pages: set[str] = set()
        for pcfg in pages:
            for row in scraper.scrape_draw_page(
                pcfg["path"], pcfg["draw_name"], pcfg["draw_time"], year_hint
            ):
                raw_rows.append({
                    **row,
                    "lottery_name": db_name,
                    "draw_time": pcfg["draw_time"],
                })
                if row.get("draw_date"):
                    page_dates_from_draw_pages.add(row["draw_date"])
            time.sleep(0.2)

        # Hub API solo si las páginas de tanda no entregaron historial suficiente
        if len(raw_rows) < max(3, days // 5):
            hub_rows, hub = _hub_rows_for_lottery(days, db_name, scraper.get_hub_rows(days))
            if not hub.get("ok") and hub.get("error"):
                hub_errors.append(str(hub.get("error")))
            raw_rows.extend(hub_rows)
        elif not raw_rows:
            hub_errors.append("Páginas de tanda sin filas parseables (parser Nuxt)")

        if pages and not page_dates_from_draw_pages:
            only_today_warning = True
        elif pages and page_dates_from_draw_pages:
            old_dates = [d for d in page_dates_from_draw_pages if d < cutoff]
            if not old_dates and len(page_dates_from_draw_pages) <= 2:
                only_today_warning = True

    raw_rows = _dedupe_rows(raw_rows)
    rows = _filter_rows_by_days(raw_rows, days, draw_name=draw_name)

    imported = updated = 0
    errors = list(hub_errors)
    for row in rows:
        try:
            _, action = upsert_result(
                lottery_id,
                row["draw_name"],
                row.get("draw_time", ""),
                row["draw_date"],
                format_numbers(row["numbers"]),
                source_url=row.get("source_url"),
                confirmed=1,
                fuente="conectate_rd",
                estado="publicado",
            )
            updated += action == "updated"
            imported += action == "inserted"
        except Exception as e:
            errors.append(str(e))

    dates_found = sorted({r.get("draw_date") for r in rows if r.get("draw_date")}, reverse=True)
    saved_total = imported + updated
    hub_status = None
    if hub_errors:
        for part in hub_errors:
            if "403" in part:
                hub_status = 403
                break
    ok = saved_total > 0 or len(rows) > 0
    if not ok and hub_errors:
        ok = False

    msg = (
        f"{db_name}: historial {days} días — {len(rows)} sorteos guardados "
        f"({imported} nuevos, {updated} actualizados)."
    )
    if only_today_warning and len(dates_found) <= 1:
        msg += " Esta fuente solo entregó resultados del día actual en las páginas de tanda."

    return {
        "ok": ok,
        "source": "conectate_rd",
        "imported": imported,
        "updated": updated,
        "errors": errors[:10],
        "days": days,
        "dates_found": dates_found,
        "rows_found": len(raw_rows),
        "rows_saved": len(rows),
        "status_code": hub_status,
        "parser": "nuxt_draw_pages",
        "supports_full_history": not only_today_warning or len(dates_found) > 3,
        "only_today_warning": only_today_warning and len(dates_found) <= 1,
        "message": msg,
    }


def import_conectate_lottery_today(lottery_name, draw_name=None, days: int = 30):
    """Compat: delega a historial (por defecto 30 días)."""
    return import_conectate_lottery_history(lottery_name, days=days, draw_name=draw_name)
