"""
Scraper LotteryPost — tercera fuente Illinois.
Fuente: https://www.lotterypost.com/results/il
"""
from __future__ import annotations

import logging
import re

from scrapers.usa_http import fetch_url
from services.scraper_deps import ensure_scraper_deps, get_beautiful_soup

logger = logging.getLogger(__name__)
LOG = "[USA SCRAPER]"

RESULTS_URL = "https://www.lotterypost.com/results/il"

# título h2 -> config juego
TITLE_RULES = (
    (re.compile(r"^pick\s*3\s*midday$", re.I), "Illinois Pick 3", "Pick 3", "Midday", "pick3", 3, "Fireball"),
    (re.compile(r"^pick\s*3\s*evening$", re.I), "Illinois Pick 3", "Pick 3", "Evening", "pick3", 3, "Fireball"),
    (re.compile(r"^pick\s*4\s*midday$", re.I), "Illinois Pick 4", "Pick 4", "Midday", "pick4", 4, "Fireball"),
    (re.compile(r"^pick\s*4\s*evening$", re.I), "Illinois Pick 4", "Pick 4", "Evening", "pick4", 4, "Fireball"),
    (re.compile(r"^lucky\s*day\s*lotto\s*midday$", re.I), "Lucky Day Lotto", "Lucky Day Lotto", "Midday", "lucky_day", 5, None),
    (re.compile(r"^lucky\s*day\s*lotto\s*evening$", re.I), "Lucky Day Lotto", "Lucky Day Lotto", "Evening", "lucky_day", 5, None),
    (re.compile(r"^lotto$", re.I), "Illinois Lotto", "Lotto", "Evening", "lotto", 6, "Extra Shot"),
    (re.compile(r"^mega\s*millions$", re.I), "Mega Millions", "Mega Millions", "Mega Millions draw", "mega_millions", 5, "Mega Ball"),
    (re.compile(r"^powerball$", re.I), "Powerball", "Powerball", "Powerball draw", "powerball", 5, "Powerball"),
    (re.compile(r"^cash\s*4\s*life$", re.I), "Cash4Life", "Cash4Life", "Cash4Life draw", "cash4life", 5, "Cash Ball"),
)

LOTTERY_NAME_TO_TITLE_PREFIX = {
    "powerball": "powerball",
    "mega millions": "mega",
    "illinois pick 3": "pick 3",
    "illinois pick 4": "pick 4",
    "lucky day lotto": "lucky",
    "illinois lotto": "lotto",
    "cash4life": "cash",
}


def _pad_number(n, game_type: str) -> str:
    try:
        val = int(n)
    except (ValueError, TypeError):
        return str(n).strip()
    if game_type in ("pick3", "pick4"):
        return str(val)
    return str(val).zfill(2)


def _match_title(title: str):
    t = (title or "").strip()
    for pattern, lottery_name, game_name, draw_name, gtype, main_count, bonus_label in TITLE_RULES:
        if pattern.match(t):
            return lottery_name, game_name, draw_name, gtype, main_count, bonus_label
    return None


def _parse_datetime(time_el) -> tuple[str, str]:
    if not time_el:
        return "", ""
    iso = time_el.get("datetime") or ""
    draw_date = ""
    if iso:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", iso)
        if m:
            draw_date = m.group(1)
    draw_time = ""
    if "T" in iso:
        draw_time = iso.split("T", 1)[1][:5]
    return draw_date, draw_time


def _parse_section_numbers(section, game_type: str, main_count: int) -> tuple[list[str], list[str], str | None]:
    main: list[str] = []
    bonus: list[str] = []
    bonus_label = None
    wrap = section.select_one(".resultsnumswrap")
    if not wrap:
        return main, bonus, bonus_label

    for row in wrap.select(".resultsnumsrow"):
        row_text = row.get_text(" ", strip=True)
        if "Lotto Million" in row_text or "Power Play" in row_text:
            continue
        nums = [
            li.get_text(strip=True)
            for li in row.select("ul.resultsnums li")
            if li.get_text(strip=True)
        ]
        if not nums:
            continue
        lower = row_text.lower()
        if any(k in lower for k in ("fireball", "mega ball", "powerball:", "extra shot", "cash ball")):
            bonus = [_pad_number(n, game_type) for n in nums[:1]]
            if "fireball" in lower:
                bonus_label = "Fireball"
            elif "mega ball" in lower:
                bonus_label = "Mega Ball"
            elif "powerball" in lower:
                bonus_label = "Powerball"
            elif "extra shot" in lower:
                bonus_label = "Extra Shot"
            elif "cash ball" in lower:
                bonus_label = "Cash Ball"
            continue
        if not main and nums:
            main = [_pad_number(n, game_type) for n in nums[:main_count]]
    return main, bonus, bonus_label


def parse_lotterypost_html(html: str, source_url: str = RESULTS_URL) -> list[dict]:
    BeautifulSoup = get_beautiful_soup()
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []

    for section in soup.select("section"):
        h2 = section.select_one("h2")
        if not h2:
            continue
        matched = _match_title(h2.get_text(strip=True))
        if not matched:
            continue
        lottery_name, game_name, draw_name, game_type, main_count, default_bonus = matched
        draw_date, draw_time = _parse_datetime(section.select_one("time"))
        if not draw_date:
            continue
        main, bonus, bonus_label = _parse_section_numbers(section, game_type, main_count)
        if len(main) < min(main_count, 1):
            continue
        rows.append({
            "lottery_name": lottery_name,
            "game_name": game_name,
            "draw_name": draw_name,
            "draw_date": draw_date,
            "draw_time": draw_time,
            "main_numbers": main,
            "bonus_numbers": bonus,
            "bonus_label": bonus_label or default_bonus if bonus else None,
            "source_url": source_url,
            "fuente": "lotterypost",
        })
    return rows


def probe_lotterypost() -> dict:
    """Prueba conexión sin importar a BD (debug Render)."""
    page = fetch_url(
        RESULTS_URL,
        valid_markers=("resultsgame", "resultsnumbers"),
        source="lotterypost",
    )
    out = {
        "fuente": "lotterypost",
        "url": RESULTS_URL,
        "ok": page.get("ok"),
        "status_code": page.get("status_code"),
        "elapsed": page.get("elapsed"),
        "size": page.get("size"),
        "error": page.get("error") or page.get("message"),
        "sorteos_encontrados": 0,
    }
    if page.get("ok"):
        try:
            ensure_scraper_deps()
            rows = parse_lotterypost_html(page["html"], page.get("url", RESULTS_URL))
            out["sorteos_encontrados"] = len(rows)
            out["ok"] = bool(rows)
            if not rows:
                out["error"] = "HTML OK pero sin sorteos parseables"
        except Exception as exc:
            logger.exception("%s LotteryPost probe parse error", LOG)
            out["ok"] = False
            out["error"] = str(exc)
    return out


def import_lotterypost_results(lottery_name: str | None = None) -> dict:
    from scrapers.cache.usa_results_cache import save_results_snapshot
    from services.resultados.illinois_scraper import _import_rows_grouped

    try:
        ensure_scraper_deps()
    except ImportError as exc:
        return {"ok": False, "message": str(exc), "errors": [str(exc)], "source": "lotterypost"}

    page = fetch_url(
        RESULTS_URL,
        valid_markers=("resultsgame", "resultsnumbers"),
        source="lotterypost",
    )
    if not page.get("ok"):
        return {
            "ok": False,
            "status": "lotterypost_unreachable",
            "source": "lotterypost",
            "imported": 0,
            "updated": 0,
            "errors": [page.get("message") or page.get("error") or "LotteryPost no respondió"],
            "status_code": page.get("status_code"),
            "url": RESULTS_URL,
            "elapsed": page.get("elapsed"),
        }

    rows = parse_lotterypost_html(page["html"], page.get("url", RESULTS_URL))
    if lottery_name:
        rows = [r for r in rows if (r.get("lottery_name") or "").lower() == lottery_name.lower()]

    logger.info(
        "%s LotteryPost OK | url=%s | status=%s | sorteos=%s | tiempo=%ss",
        LOG,
        page.get("url"),
        page.get("status_code"),
        len(rows),
        page.get("elapsed"),
    )

    if not rows:
        return {
            "ok": False,
            "source": "lotterypost",
            "imported": 0,
            "updated": 0,
            "errors": ["LotteryPost sin sorteos válidos"],
            "rows_parsed": 0,
        }

    imported, updated, errors, game_stats = _import_rows_grouped(rows)
    saved = imported + updated
    if saved == 0 and errors:
        return {
            "ok": False,
            "source": "lotterypost",
            "imported": 0,
            "updated": 0,
            "errors": errors[:20],
            "message": errors[0],
            "rows_parsed": len(rows),
        }

    save_results_snapshot(rows, fuente="lotterypost", url=page.get("url", RESULTS_URL))
    status = "updated" if saved else "no_new"
    return {
        "ok": True,
        "status": status,
        "source": "lotterypost",
        "fuente": "lotterypost",
        "imported": imported,
        "updated": updated,
        "errors": errors[:20],
        "game_stats": game_stats,
        "rows_parsed": len(rows),
        "status_code": page.get("status_code"),
        "url": page.get("url"),
        "elapsed": page.get("elapsed"),
        "message": f"Resultados desde LotteryPost ({imported} nuevos, {updated} actualizados).",
    }
