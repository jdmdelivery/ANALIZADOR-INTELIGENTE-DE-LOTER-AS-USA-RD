"""
Scraper Lucky Day Lotto — IllinoisLotteryNumbers.net (solo respaldo).
Fuente: https://illinoislotterynumbers.net/lucky-day-lotto/results
"""
from __future__ import annotations

import logging
import re

from scrapers.usa_http import fetch_url
from services.scraper_deps import ensure_scraper_deps, get_beautiful_soup

logger = logging.getLogger(__name__)
LOG = "[USA SCRAPER]"

RESULTS_URL = "https://illinoislotterynumbers.net/lucky-day-lotto/results"
LOTTERY_NAME = "Lucky Day Lotto"
DRAW_TIMES = {"Midday": "12:40", "Evening": "21:22"}
MIN_NUM = 1
MAX_NUM = 45
MAIN_COUNT = 5

MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def _pad(n: int | str) -> str:
    return str(int(n)).zfill(2)


def _parse_date_block(date_el, block) -> str | None:
    if date_el:
        text = date_el.get_text(" ", strip=True)
        m = re.search(
            r"(?:\w+day,?\s+)?(\w+)\s+(\d{1,2}),?\s+(\d{4})",
            text,
            re.I,
        )
        if m:
            month, day, year = m.groups()
            return f"{year}-{MONTHS.get(month.lower(), '01')}-{int(day):02d}"
    link = block.select_one('a[href*="/lucky-day-lotto/results/"]')
    if link:
        href = link.get("href", "")
        m = re.search(r"/(\d{2})-(\d{2})-(\d{4})", href)
        if m:
            mo, day, year = m.groups()
            return f"{year}-{mo}-{day}"
    return None


def _valid_main(nums: list[str]) -> bool:
    if len(nums) != MAIN_COUNT:
        return False
    seen: set[int] = set()
    for raw in nums:
        try:
            v = int(str(raw).lstrip("0") or "0")
        except (TypeError, ValueError):
            return False
        if v < MIN_NUM or v > MAX_NUM:
            return False
        if v in seen:
            return False
        seen.add(v)
    return True


def parse_iln_luckyday_html(html: str, source_url: str = RESULTS_URL) -> list[dict]:
    BeautifulSoup = get_beautiful_soup()
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []

    for block in soup.select(".main-result"):
        date_el = block.select_one(".date")
        draw_date = _parse_date_block(date_el, block)
        if not draw_date:
            continue

        for box in block.select(".group-wrapper .box"):
            label_el = box.select_one(".h4")
            if not label_el:
                continue
            draw_name = label_el.get_text(strip=True)
            if draw_name not in DRAW_TIMES:
                continue
            main = [
                li.get_text(strip=True)
                for li in box.select("ul.balls li.ball")
                if li.get_text(strip=True)
            ]
            main = [_pad(n) for n in main[:MAIN_COUNT]]
            if not _valid_main(main):
                continue
            rows.append({
                "lottery_name": LOTTERY_NAME,
                "game_name": LOTTERY_NAME,
                "draw_name": draw_name,
                "draw_date": draw_date,
                "draw_time": DRAW_TIMES[draw_name],
                "main_numbers": main,
                "bonus_numbers": [],
                "bonus_label": None,
                "source_url": source_url,
                "fuente": "illinoislotterynumbers",
            })
    return rows


def fetch_iln_luckyday_page() -> dict:
    return fetch_url(
        RESULTS_URL,
        valid_markers=("main-result", "lucky-day-lotto"),
        source="illinoislotterynumbers",
        min_bytes=800,
    )


def import_iln_luckyday_results() -> dict:
    """Descarga ILN, importa Lucky Day Lotto a BD."""
    from scrapers.cache.usa_results_cache import save_results_snapshot
    from services.resultados.illinois_scraper import _import_rows_grouped

    try:
        ensure_scraper_deps()
    except ImportError as exc:
        return {
            "ok": False,
            "message": str(exc),
            "errors": [str(exc)],
            "source": "illinoislotterynumbers",
            "fuente_label": "IllinoisLotteryNumbers",
        }

    page = fetch_iln_luckyday_page()
    if not page.get("ok"):
        err = page.get("error") or page.get("message") or "IllinoisLotteryNumbers no respondió"
        logger.warning(
            "%s Lucky Day ILN falló | url=%s | status=%s | error=%s",
            LOG,
            RESULTS_URL,
            page.get("status_code"),
            err,
        )
        return {
            "ok": False,
            "source": "illinoislotterynumbers",
            "fuente_label": "IllinoisLotteryNumbers",
            "imported": 0,
            "updated": 0,
            "errors": [err],
            "status_code": page.get("status_code"),
            "url": RESULTS_URL,
            "elapsed": page.get("elapsed"),
        }

    rows = parse_iln_luckyday_html(page["html"], page.get("url", RESULTS_URL))
    logger.info(
        "%s Lucky Day ILN OK | url=%s | status=%s | sorteos=%s | tiempo=%ss",
        LOG,
        page.get("url"),
        page.get("status_code"),
        len(rows),
        page.get("elapsed"),
    )

    if not rows:
        return {
            "ok": False,
            "source": "illinoislotterynumbers",
            "fuente_label": "IllinoisLotteryNumbers",
            "imported": 0,
            "updated": 0,
            "rows_parsed": 0,
            "errors": ["IllinoisLotteryNumbers sin sorteos válidos (1-45, 5 números)"],
        }

    imported, updated, errors, _ = _import_rows_grouped(rows)
    saved = imported + updated
    if saved == 0 and errors:
        return {
            "ok": False,
            "source": "illinoislotterynumbers",
            "fuente_label": "IllinoisLotteryNumbers",
            "imported": 0,
            "updated": 0,
            "errors": errors[:20],
            "message": errors[0],
            "rows_parsed": len(rows),
        }

    save_results_snapshot(rows, fuente="illinoislotterynumbers", url=page.get("url", RESULTS_URL))
    return {
        "ok": True,
        "status": "updated" if saved else "no_new",
        "source": "illinoislotterynumbers",
        "fuente": "illinoislotterynumbers",
        "fuente_label": "IllinoisLotteryNumbers",
        "imported": imported,
        "updated": updated,
        "rows_parsed": len(rows),
        "errors": errors[:20],
        "status_code": page.get("status_code"),
        "url": page.get("url"),
        "elapsed": page.get("elapsed"),
        "message": f"Lucky Day desde IllinoisLotteryNumbers ({imported} nuevos, {updated} actualizados).",
    }
