"""
Fuentes dedicadas Lucky Day Lotto — parsers e importadores.
Solo Lucky Day Lotto (5 números, 1–45, Midday 12:40 / Evening 21:22).
"""
from __future__ import annotations

import logging
import re

from scrapers.usa_http import fetch_url
from services.lottery_dates import (
    filter_recent_rows,
    max_draw_date_in_rows,
    parse_card_date_text,
    recent_cutoff,
)
from services.scraper_deps import ensure_scraper_deps, get_beautiful_soup

logger = logging.getLogger(__name__)
LOG = "[USA SCRAPER]"

LOTTERY_NAME = "Lucky Day Lotto"
MIN_NUM = 1
MAX_NUM = 45
MAIN_COUNT = 5
DRAW_TIMES = {"Midday": "12:40", "Evening": "21:22"}

URLS = {
    "illinois_dbg": "https://www.illinoislottery.com/dbg/results/luckydaylotto",
    "illinois_hub": "https://www.illinoislottery.com/results-hub",
    "lotteryusa_evening": "https://www.lotteryusa.com/illinois/lucky-day-lotto-evening/",
    "lotteryusa_midday": "https://www.lotteryusa.com/illinois/midday-lucky-day-lotto/",
    "lotterypost_past": "https://www.lotterypost.com/results/il/luckydaylotto/past",
    "iln_past": "https://illinoislotterynumbers.net/lucky-day-lotto/past-numbers",
    "iln_results": "https://illinoislotterynumbers.net/lucky-day-lotto/results",
    "lottery_net_midday": "https://www.lottery.net/illinois/lucky-day-lotto-midday/numbers",
    "lottery_net_evening": "https://www.lottery.net/illinois/lucky-day-lotto-evening/numbers",
}

MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def _pad(n: int | str) -> str:
    return str(int(n)).zfill(2)


def valid_lucky_day_main(nums: list[str]) -> bool:
    if len(nums) != MAIN_COUNT:
        return False
    seen: set[int] = set()
    for raw in nums:
        try:
            v = int(str(raw).lstrip("0") or "0")
        except (TypeError, ValueError):
            return False
        if v < MIN_NUM or v > MAX_NUM or v in seen:
            return False
        seen.add(v)
    return True


def _normalize_draw_name(name: str) -> str:
    t = (name or "").strip().lower()
    if "midday" in t or "mid day" in t:
        return "Midday"
    if "evening" in t or "night" in t:
        return "Evening"
    return "Evening"


def _row(draw_date: str, draw_name: str, main: list[str], source_url: str, fuente: str) -> dict:
    dn = _normalize_draw_name(draw_name)
    return {
        "lottery_name": LOTTERY_NAME,
        "game_name": LOTTERY_NAME,
        "draw_name": dn,
        "draw_date": draw_date,
        "draw_time": DRAW_TIMES[dn],
        "main_numbers": main,
        "bonus_numbers": [],
        "bonus_label": None,
        "source_url": source_url,
        "fuente": fuente,
    }


def _dedupe_rows(rows: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    out = []
    for r in rows:
        key = (r.get("draw_date"), r.get("draw_name"), tuple(r.get("main_numbers") or []))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _parse_date_text(text: str) -> str | None:
    return parse_card_date_text(text)


def _import_rows(rows: list[dict], *, fuente: str, fuente_label: str, url: str, page: dict | None = None) -> dict:
    from scrapers.cache.usa_results_cache import save_results_snapshot
    from services.resultados.illinois_scraper import _import_rows_grouped

    rows = _dedupe_rows([r for r in rows if valid_lucky_day_main(r.get("main_numbers") or [])])
    rows = filter_recent_rows(rows, days=90)
    latest = max_draw_date_in_rows(rows)
    if not rows:
        return {
            "ok": False,
            "fuente": fuente,
            "fuente_label": fuente_label,
            "imported": 0,
            "updated": 0,
            "rows_parsed": 0,
            "url": url,
            "errors": ["Sin sorteos Lucky Day válidos (5 números, 1–45)"],
            "message": "Sin sorteos Lucky Day válidos (5 números, 1–45).",
        }

    imported, updated, errors, _ = _import_rows_grouped(rows)
    saved = imported + updated
    if saved > 0:
        save_results_snapshot(rows, fuente=fuente, url=url)

    for r in rows[:5]:
        logger.info(
            "%s Lucky Day | fuente=%s | fecha=%s | tanda=%s | nums=%s",
            LOG,
            fuente_label,
            r.get("draw_date"),
            r.get("draw_name"),
            r.get("main_numbers"),
        )

    return {
        "ok": True,
        "fuente": fuente,
        "fuente_label": fuente_label,
        "imported": imported,
        "updated": updated,
        "rows_parsed": len(rows),
        "rows": rows,
        "latest_date": latest,
        "errors": errors[:10],
        "status_code": (page or {}).get("status_code"),
        "elapsed": (page or {}).get("elapsed"),
        "url": url,
        "message": f"Lucky Day desde {fuente_label} ({imported} nuevos, {updated} actualizados).",
    }


def parse_illinois_hub_luckyday(html: str, source_url: str) -> list[dict]:
    from services.resultados.illinois_scraper import parse_results_hub_html

    return [
        {**r, "fuente": "illinoislottery", "draw_time": DRAW_TIMES.get(r.get("draw_name", ""), "")}
        for r in parse_results_hub_html(html)
        if (r.get("lottery_name") or "").lower() == LOTTERY_NAME.lower()
        and valid_lucky_day_main(r.get("main_numbers") or [])
    ]


def parse_lotteryusa_luckyday_html(html: str, draw_name: str, source_url: str) -> list[dict]:
    from scrapers.lotteryusa_scraper import LOTTERYUSA_GAMES, parse_lotteryusa_html

    cfg = {**LOTTERYUSA_GAMES["luckyday"], "draw_name_default": _normalize_draw_name(draw_name)}
    rows = parse_lotteryusa_html(html, cfg, source_url)
    out = []
    for r in rows:
        main = r.get("main_numbers") or []
        if not valid_lucky_day_main(main):
            continue
        out.append(_row(r["draw_date"], draw_name, main, source_url, "lotteryusa"))
    return out


def parse_lotterypost_luckyday_html(html: str, source_url: str) -> list[dict]:
    from scrapers.lotterypost_scraper import parse_lotterypost_html

    rows = parse_lotterypost_html(html, source_url)
    out = []
    for r in rows:
        if (r.get("lottery_name") or "").lower() != LOTTERY_NAME.lower():
            continue
        main = r.get("main_numbers") or []
        if not valid_lucky_day_main(main):
            continue
        out.append(_row(r["draw_date"], r.get("draw_name", "Evening"), main, source_url, "lotterypost"))
    return out


def parse_iln_luckyday_html(html: str, source_url: str) -> list[dict]:
    from scrapers.illinoislotterynumbers_luckyday import parse_iln_luckyday_html as _parse

    out = []
    for r in _parse(html, source_url):
        main = r.get("main_numbers") or []
        if not valid_lucky_day_main(main):
            continue
        out.append(_row(r["draw_date"], r.get("draw_name", "Evening"), main, source_url, "illinoislotterynumbers"))
    return out


def parse_lottery_net_html(html: str, draw_name: str, source_url: str) -> list[dict]:
    BeautifulSoup = get_beautiful_soup()
    soup = BeautifulSoup(html, "lxml")
    cls = "lucky-day-lotto-midday" if _normalize_draw_name(draw_name) == "Midday" else "lucky-day-lotto-evening"
    rows: list[dict] = []
    for ul in soup.select(f"ul.{cls}"):
        nums = [_pad(li.get_text(strip=True)) for li in ul.select("li.ball")][:MAIN_COUNT]
        if not valid_lucky_day_main(nums):
            continue
        prev = ul.find_previous(["h2", "h3", "h4", "p", "div"])
        draw_date = _parse_date_text(prev.get_text(" ", strip=True) if prev else "")
        if not draw_date:
            parent = ul.parent
            draw_date = _parse_date_text(parent.get_text(" ", strip=True) if parent else "")
        if not draw_date:
            continue
        rows.append(_row(draw_date, draw_name, nums, source_url, "lottery_net"))
    return rows


def _fetch(source_key: str, url: str, markers: tuple[str, ...]) -> dict:
    return fetch_url(url, source=source_key, valid_markers=markers, min_bytes=600)


def import_illinois_dbg_luckyday() -> dict:
    url = URLS["illinois_dbg"]
    page = _fetch("illinois_dbg", url, ("luckydaylotto", "dbg-results", "lucky"))
    if not page.get("ok"):
        return {**page, "ok": False, "fuente": "illinoislottery", "fuente_label": "Illinois Lottery DBG"}
    rows = parse_illinois_hub_luckyday(page["html"], page.get("url", url))
    return _import_rows(rows, fuente="illinoislottery", fuente_label="Illinois Lottery DBG", url=url, page=page)


def import_illinois_hub_luckyday() -> dict:
    url = URLS["illinois_hub"]
    page = _fetch("illinois_hub", url, ("results-container", "luckyday"))
    if not page.get("ok"):
        return {**page, "ok": False, "fuente": "illinoislottery", "fuente_label": "Illinois Results Hub"}
    rows = filter_recent_rows(parse_illinois_hub_luckyday(page["html"], page.get("url", url)), days=90)
    latest = max_draw_date_in_rows(rows)
    if not rows or (latest and latest < recent_cutoff(30)):
        return {
            "ok": False,
            "fuente": "illinoislottery",
            "fuente_label": "Illinois Results Hub",
            "imported": 0,
            "updated": 0,
            "rows_parsed": 0,
            "latest_date": latest,
            "message": "Illinois Hub sin sorteos recientes (SPA/caché obsoleta)",
            "url": url,
        }
    return _import_rows(rows, fuente="illinoislottery", fuente_label="Illinois Results Hub", url=url, page=page)


def import_lotteryusa_luckyday() -> dict:
    ensure_scraper_deps()
    all_rows: list[dict] = []
    last_page: dict = {}
    urls_used: list[str] = []
    for draw_name, key in (("Evening", "lotteryusa_evening"), ("Midday", "lotteryusa_midday")):
        url = URLS[key]
        page = _fetch("lotteryusa", url, ("c-draw-card", "c-result"))
        if page.get("ok"):
            all_rows.extend(parse_lotteryusa_luckyday_html(page["html"], draw_name, page.get("url", url)))
            last_page = page
            urls_used.append(url)
    if not all_rows:
        return {
            "ok": False,
            "fuente": "lotteryusa",
            "fuente_label": "LotteryUSA",
            "imported": 0,
            "updated": 0,
            "rows_parsed": 0,
            "errors": ["LotteryUSA Midday/Evening sin sorteos parseables"],
        }
    return _import_rows(
        all_rows,
        fuente="lotteryusa",
        fuente_label="LotteryUSA",
        url=urls_used[0] if urls_used else URLS["lotteryusa_evening"],
        page=last_page,
    )


def import_lotterypost_luckyday_past() -> dict:
    ensure_scraper_deps()
    url = URLS["lotterypost_past"]
    page = _fetch("lotterypost", url, ("resultsnums", "resultsgame"))
    if not page.get("ok"):
        return {**page, "ok": False, "fuente": "lotterypost", "fuente_label": "LotteryPost"}
    rows = parse_lotterypost_luckyday_html(page["html"], page.get("url", url))[:60]
    return _import_rows(rows, fuente="lotterypost", fuente_label="LotteryPost", url=url, page=page)


def import_iln_luckyday_past() -> dict:
    ensure_scraper_deps()
    for key in ("iln_past", "iln_results"):
        url = URLS[key]
        page = _fetch("illinoislotterynumbers", url, ("main-result", "lucky-day-lotto"))
        if not page.get("ok"):
            continue
        rows = parse_iln_luckyday_html(page["html"], page.get("url", url))[:60]
        result = _import_rows(
            rows,
            fuente="illinoislotterynumbers",
            fuente_label="IllinoisLotteryNumbers",
            url=url,
            page=page,
        )
        if result.get("ok") and (result.get("rows_parsed") or 0) > 0:
            return result
    return {
        "ok": False,
        "fuente": "illinoislotterynumbers",
        "fuente_label": "IllinoisLotteryNumbers",
        "imported": 0,
        "updated": 0,
        "rows_parsed": 0,
        "errors": ["IllinoisLotteryNumbers no respondió"],
    }


def import_lottery_net_luckyday() -> dict:
    ensure_scraper_deps()
    all_rows: list[dict] = []
    last_page: dict = {}
    urls_used: list[str] = []
    for draw_name, key in (("Midday", "lottery_net_midday"), ("Evening", "lottery_net_evening")):
        url = URLS[key]
        page = _fetch("lottery_net", url, ("lucky-day-lotto", "ball"))
        if page.get("ok"):
            all_rows.extend(parse_lottery_net_html(page["html"], draw_name, page.get("url", url)))
            last_page = page
            urls_used.append(url)
    if not all_rows:
        return {
            "ok": False,
            "fuente": "lottery_net",
            "fuente_label": "Lottery.net",
            "imported": 0,
            "updated": 0,
            "rows_parsed": 0,
            "errors": ["Lottery.net sin sorteos parseables"],
        }
    return _import_rows(
        all_rows,
        fuente="lottery_net",
        fuente_label="Lottery.net",
        url=urls_used[0],
        page=last_page,
    )
