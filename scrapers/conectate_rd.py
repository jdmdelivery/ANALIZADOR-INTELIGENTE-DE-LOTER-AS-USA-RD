"""
Importador Conectate RD — Anguila lee TODO el historial visible + fecha principal.
Fuente: https://www.conectate.com.do/loterias/
"""

import re
import time
from datetime import datetime, timedelta

import requests

from models import upsert_result, format_numbers, get_all_lotteries

BASE_URL = "https://www.conectate.com.do"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-DO,es;q=0.9,en;q=0.8",
}

CONECTATE_DRAW_PAGES = [
    {"lottery_name": "Leidsa", "path": "/loterias/leidsa/quiniela-pale", "draw_name": "noche", "draw_time": "20:55"},
    {"lottery_name": "Loteka", "path": "/loterias/loteka/quiniela-mega-decenas", "draw_name": "noche", "draw_time": "19:55"},
    {"lottery_name": "Lotería Nacional", "path": "/loterias/nacional/quiniela", "draw_name": "tarde", "draw_time": "14:30"},
    {"lottery_name": "Gana Más", "path": "/loterias/nacional/gana-mas", "draw_name": "tarde", "draw_time": "14:30"},
    {"lottery_name": "Lotería Real", "path": "/loterias/loto-real/quiniela", "draw_name": "tarde", "draw_time": "12:55"},
    {"lottery_name": "La Primera", "path": "/loterias/la-primera/quiniela-medio-dia", "draw_name": "mañana", "draw_time": "12:00"},
    {"lottery_name": "La Primera", "path": "/loterias/la-primera/quiniela-noche", "draw_name": "noche", "draw_time": "20:00"},
    {"lottery_name": "Suerte Dominicana", "path": "/loterias/la-suerte-dominicana/quiniela", "draw_name": "tarde", "draw_time": "12:30"},
    {"lottery_name": "Lotedom", "path": "/loterias/lotedom/quiniela", "draw_name": "tarde", "draw_time": "13:55"},
]

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

LOGO_MAIN_PAGE = {
    "quiniela-leidsa": ("Leidsa", "noche"),
    "quiniela-loteka": ("Loteka", "noche"),
    "quiniela-real": ("Lotería Real", "tarde"),
    "loteria-nacional": ("Lotería Nacional", "tarde"),
    "gana-mas-loteria-nacional": ("Gana Más", "tarde"),
    "la-primera-dia": ("La Primera", "mañana"),
    "la-primera-noche": ("La Primera", "noche"),
    "quiniela-lotedom": ("Lotedom", "tarde"),
    "quiniela-la-suerte": ("Suerte Dominicana", "tarde"),
}


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
    scores_m = re.search(r'class="game-scores[^"]*"[^>]*>(.*?)</div>', chunk, re.S)
    if not scores_m:
        return None
    nums = re.findall(r'class="score[^"]*"[^>]*>\s*(\d{1,2})\s*<', scores_m.group(1))
    if len(nums) != 3:
        return None
    return [n.zfill(2) for n in nums]


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
    """Todos los game-block visibles en pagina de tanda (historial)."""
    results = []
    blocks = list(re.finditer(r'<div class="game-block[^"]*"', html))
    for i, m in enumerate(blocks):
        start = m.start()
        end = blocks[i + 1].start() if i + 1 < len(blocks) else start + 1500
        chunk = html[start:end]
        numbers = _extract_three_numbers(chunk)
        if not numbers:
            continue
        date_m = re.search(r'class="session-date[^"]*"[^>]*>\s*([^<]+)', chunk)
        draw_date = _normalize_date(date_m.group(1).strip() if date_m else "", year_hint)
        if not draw_date:
            continue
        print("Guardando:", draw_date, cfg["draw_name"], cfg["time_display"], numbers)
        results.append({
            "lottery_name": "Anguila",
            "draw_name": cfg["draw_name"],
            "draw_time": cfg["draw_time"],
            "time_display": cfg["time_display"],
            "draw_date": draw_date,
            "numbers": numbers,
            "source_url": source_url,
        })
    return results


def parse_anguila_blocks(html, year_hint, source_url, page_date=None):
    """Bloques por texto en portada ?date= (fecha principal = page_date)."""
    results = []
    for block_cfg in ANGUILA_BLOCKS:
        chunk = _extract_block_chunk(html, block_cfg["block_text"])
        if not chunk:
            continue
        numbers = _extract_three_numbers(chunk)
        if not numbers:
            print(f"Resultado aún no disponible — {block_cfg['block_text']}")
            continue
        date_m = re.search(r'class="session-date[^"]*"[^>]*>\s*([^<]+)', chunk)
        draw_date = page_date or _normalize_date(date_m.group(1).strip() if date_m else "", year_hint)
        if not draw_date:
            continue
        print("Guardando:", draw_date, block_cfg["draw_name"], block_cfg["time_display"], numbers)
        results.append({
            "lottery_name": "Anguila",
            "draw_name": block_cfg["draw_name"],
            "draw_time": block_cfg["draw_time"],
            "time_display": block_cfg["time_display"],
            "draw_date": draw_date,
            "numbers": numbers,
            "source_url": source_url,
        })
    return results


def scrape_anguila_all_visible(scraper, year_hint, days_back=60):
    print("Leyendo TODO el historial visible")
    all_rows = []
    for cfg in ANGUILA_DRAW_PAGES:
        page = scraper.fetch_page(cfg["path"])
        if page.get("ok"):
            all_rows.extend(parse_anguila_history_page(page["html"], cfg, year_hint, page["url"]))
        time.sleep(0.3)
    for days_ago in range(days_back):
        dt = datetime.now() - timedelta(days=days_ago)
        date_param = dt.strftime("%d-%m-%Y")
        page = scraper.fetch_page("/loterias/", params={"date": date_param})
        if page.get("ok"):
            page_date = _date_param_to_iso(date_param)
            all_rows.extend(parse_anguila_blocks(page["html"], str(dt.year), page["url"], page_date=page_date))
        time.sleep(0.3)
    dates = [r["draw_date"] for r in all_rows if r.get("draw_date")]
    fecha_max = max(dates) if dates else None
    print("Fecha más nueva detectada:", fecha_max)
    print("Mostrando en últimos resultados solo:", fecha_max)
    return all_rows, fecha_max


def _parse_session_blocks(html):
    games = []
    blocks = list(re.finditer(r'<div class="game-block[^"]*"', html))
    for i, m in enumerate(blocks):
        start = m.start()
        end = blocks[i + 1].start() if i + 1 < len(blocks) else start + 1500
        chunk = html[start:end]
        date_m = re.search(r'class="session-date[^"]*"[^>]*>\s*([^<]+)', chunk)
        nums = _extract_three_numbers(chunk)
        if nums:
            games.append({
                "date_raw": date_m.group(1).strip() if date_m else "",
                "numbers": nums,
            })
    return games


def _parse_main_page_blocks(html, year_hint, page_date=None):
    results = []
    blocks = list(re.finditer(r'class="game-block\s+company-block-(\d+)\s+(\w+)"', html))
    for i, m in enumerate(blocks):
        start = m.start()
        end = blocks[i + 1].start() if i + 1 < len(blocks) else start + 2000
        chunk = html[start:end]
        logo_m = re.search(r'data-src="[^"]*/([^"/]+)\.png"', chunk)
        if not logo_m:
            continue
        mapping = LOGO_MAIN_PAGE.get(logo_m.group(1))
        if not mapping:
            continue
        lottery_name, draw_name = mapping
        date_m = re.search(r'class="session-date[^"]*"[^>]*>\s*([^<]+)', chunk)
        nums = _extract_three_numbers(chunk)
        if not nums:
            continue
        draw_date = page_date or _normalize_date(date_m.group(1).strip() if date_m else "", year_hint)
        if not draw_date:
            continue
        results.append({
            "lottery_name": lottery_name,
            "draw_name": draw_name,
            "draw_date": draw_date,
            "numbers": nums,
            "source_url": BASE_URL + "/loterias/",
        })
    return results


def _find_lottery_id(lotteries, name):
    for lot in lotteries:
        if lot["country"] == "RD" and lot["name"].lower() == name.lower():
            return lot["id"]
    return None


class ConectateRDScraper:
    source_key = "conectate_rd"
    base_url = BASE_URL

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def fetch_page(self, path="", params=None):
        url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        try:
            resp = self.session.get(url, params=params or {}, timeout=20)
            resp.raise_for_status()
            return {"ok": True, "html": resp.text, "url": resp.url}
        except requests.RequestException as e:
            return {"ok": False, "message": str(e)}

    def scrape_draw_page(self, path, draw_name, draw_time, year_hint):
        page = self.fetch_page(path)
        if not page.get("ok"):
            return []
        rows = []
        for s in _parse_session_blocks(page["html"]):
            draw_date = _normalize_date(s["date_raw"], year_hint)
            if draw_date:
                rows.append({
                    "draw_name": draw_name,
                    "draw_time": draw_time,
                    "draw_date": draw_date,
                    "numbers": s["numbers"],
                    "source_url": page["url"],
                })
        return rows

    def scrape_main_for_date(self, date_param, year_hint):
        page = self.fetch_page("/loterias/", params={"date": date_param})
        if not page.get("ok"):
            return []
        page_date = _date_param_to_iso(date_param)
        return _parse_main_page_blocks(page["html"], year_hint, page_date=page_date)


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
                lid = _find_lottery_id(lotteries, row["lottery_name"])
                if lid:
                    _save_row(lid, row, "")
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


def import_conectate_lottery_today(lottery_name):
    """Importa/actualiza solo los sorteos de hoy para una lotería RD."""
    if (lottery_name or "").strip().lower() == "leidsa":
        return {
            "ok": False,
            "message": "Leidsa se actualiza desde leidsa.com (módulo LEIDSA).",
        }
    scraper = ConectateRDScraper()
    lotteries = get_all_lotteries()
    lottery_id = _find_lottery_id(lotteries, lottery_name)
    if not lottery_id:
        return {"ok": False, "message": f"Lotería RD '{lottery_name}' no encontrada."}

    today = datetime.now()
    date_param = today.strftime("%d-%m-%Y")
    today_iso = today.strftime("%Y-%m-%d")
    year_hint = str(today.year)
    rows = []

    if lottery_name.lower() == "anguila":
        page = scraper.fetch_page("/loterias/", params={"date": date_param})
        if page.get("ok"):
            rows.extend(
                parse_anguila_blocks(
                    page["html"], year_hint, page["url"], page_date=today_iso
                )
            )
        for cfg in ANGUILA_DRAW_PAGES:
            page = scraper.fetch_page(cfg["path"])
            if page.get("ok"):
                for row in parse_anguila_history_page(
                    page["html"], cfg, year_hint, page["url"]
                ):
                    if row.get("draw_date") == today_iso:
                        rows.append(row)
            time.sleep(0.2)
    else:
        for row in scraper.scrape_main_for_date(date_param, year_hint):
            if row.get("lottery_name", "").lower() == lottery_name.lower():
                if row.get("draw_date") == today_iso:
                    rows.append(row)
        for cfg in CONECTATE_DRAW_PAGES:
            if cfg["lottery_name"].lower() != lottery_name.lower():
                continue
            for row in scraper.scrape_draw_page(
                cfg["path"], cfg["draw_name"], cfg["draw_time"], year_hint
            ):
                if row.get("draw_date") == today_iso:
                    rows.append({
                        **row,
                        "lottery_name": lottery_name,
                        "draw_time": cfg["draw_time"],
                    })
            time.sleep(0.2)

    imported = updated = 0
    errors = []
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
            )
            updated += action == "updated"
            imported += action == "inserted"
        except Exception as e:
            errors.append(str(e))

    return {
        "ok": True,
        "source": "conectate_rd",
        "imported": imported,
        "updated": updated,
        "errors": errors[:5],
        "today": today_iso,
        "message": f"{lottery_name} hoy: {imported} nuevos, {updated} actualizados.",
    }
