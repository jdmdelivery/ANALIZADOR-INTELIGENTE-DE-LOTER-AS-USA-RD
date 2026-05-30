"""
Scraper LotteryUSA — fallback Illinois (Powerball, Mega Millions, Pick 3/4, etc.).
Fuente: https://www.lotteryusa.com/illinois/
"""
from __future__ import annotations

import logging
import re
import time

from scrapers.usa_http import fetch_url
from services.scraper_deps import ensure_scraper_deps, get_beautiful_soup

logger = logging.getLogger(__name__)
LOG = "[USA SCRAPER]"

FETCH_TIMEOUT = 30
FETCH_RETRIES = 3
BASE = "https://www.lotteryusa.com"
HUB_URL = f"{BASE}/illinois/"

MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}

LOTTERYUSA_GAMES = {
    "powerball": {
        "path": "/illinois/powerball/",
        "lottery_name": "Powerball",
        "game_name": "Powerball",
        "draw_name_default": "Powerball draw",
        "bonus_label": "Powerball",
        "type": "powerball",
        "main_count": 5,
    },
    "megamillions": {
        "path": "/illinois/mega-millions/",
        "lottery_name": "Mega Millions",
        "game_name": "Mega Millions",
        "draw_name_default": "Mega Millions draw",
        "bonus_label": "Mega Ball",
        "type": "mega_millions",
        "main_count": 5,
    },
    "pick3": {
        "path": "/illinois/daily-3/",
        "lottery_name": "Illinois Pick 3",
        "game_name": "Pick 3",
        "draw_name_default": "Evening",
        "bonus_label": "Fireball",
        "type": "pick3",
        "main_count": 3,
    },
    "pick4": {
        "path": "/illinois/daily-4/",
        "lottery_name": "Illinois Pick 4",
        "game_name": "Pick 4",
        "draw_name_default": "Evening",
        "bonus_label": "Fireball",
        "type": "pick4",
        "main_count": 4,
    },
    "luckyday": {
        "path": "/illinois/lucky-day-lotto/",
        "lottery_name": "Lucky Day Lotto",
        "game_name": "Lucky Day Lotto",
        "draw_name_default": "Evening",
        "bonus_label": None,
        "type": "lucky_day",
        "main_count": 5,
    },
    "lotto": {
        "path": "/illinois/lotto/",
        "lottery_name": "Illinois Lotto",
        "game_name": "Lotto",
        "draw_name_default": "Evening",
        "bonus_label": "Extra Shot",
        "type": "lotto",
        "main_count": 6,
    },
    "cash4life": {
        "path": "/illinois/cash4life/",
        "lottery_name": "Cash4Life",
        "game_name": "Cash4Life",
        "draw_name_default": "Cash4Life draw",
        "bonus_label": "Cash Ball",
        "type": "cash4life",
        "main_count": 5,
    },
}

# Nombre en BD -> slug
LOTTERY_NAME_TO_SLUG = {
    v["lottery_name"].lower(): k for k, v in LOTTERYUSA_GAMES.items()
}


def _pad_number(n, game_type: str) -> str:
    try:
        val = int(n)
    except (ValueError, TypeError):
        return str(n).strip()
    if game_type in ("pick3", "pick4"):
        return str(val)
    return str(val).zfill(2)


def _parse_lotteryusa_date(time_el) -> str | None:
    if not time_el:
        return None
    dow = ""
    sub = ""
    dow_el = time_el.select_one(".c-draw-card__draw-date-dow")
    sub_el = time_el.select_one(".c-draw-card__draw-date-sub")
    if dow_el:
        dow = dow_el.get_text(" ", strip=True)
    if sub_el:
        sub = sub_el.get_text(" ", strip=True)
    text = f"{dow} {sub}".strip() or time_el.get_text(" ", strip=True)
    # "Monday, May 25, 2026" or "May 25, 2026"
    m = re.search(
        r"(?:\w+day,?\s+)?(\w+)\s+(\d{1,2}),?\s+(\d{4})",
        text,
        re.I,
    )
    if not m:
        return None
    month, day, year = m.groups()
    return f"{year}-{MONTHS.get(month.lower(), '01')}-{int(day):02d}"


def _parse_ball_list(ul, game_cfg: dict) -> tuple[list[str], list[str]]:
    main: list[str] = []
    bonus: list[str] = []
    game_type = game_cfg["type"]
    expected_main = game_cfg.get("main_count", 5)

    for li in ul.select(":scope > li"):
        classes = " ".join(li.get("class") or [])
        if "c-result__bonus" in classes:
            ball = li.select_one(".c-ball")
            if ball:
                bonus.append(_pad_number(ball.get_text(strip=True), game_type))
            continue
        if "c-result__multiplier" in classes:
            continue
        if "c-ball" in classes:
            txt = li.get_text(strip=True)
            if txt.isdigit() or txt:
                main.append(_pad_number(txt, game_type))
        else:
            inner = li.select_one(".c-ball")
            if inner:
                main.append(_pad_number(inner.get_text(strip=True), game_type))

    if len(main) > expected_main:
        extra = main[expected_main:]
        main = main[:expected_main]
        if not bonus and extra:
            bonus = extra[:1]
    return main, bonus


def parse_lotteryusa_html(html: str, game_cfg: dict, source_url: str) -> list[dict]:
    """Parsea filas tr.c-draw-card de una página LotteryUSA."""
    BeautifulSoup = get_beautiful_soup()
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    game_type = game_cfg["type"]
    bonus_label = game_cfg.get("bonus_label")

    for card in soup.select("tr.c-draw-card"):
        time_el = card.select_one("time.c-draw-card__draw-date")
        draw_date = _parse_lotteryusa_date(time_el)
        if not draw_date:
            continue

        draw_boxes = card.select(".c-draw-card__ball-box")
        if not draw_boxes:
            ul = card.select_one("ul.c-result")
            draw_boxes = [ul.parent] if ul else []

        for box in draw_boxes:
            ul = box.select_one("ul.c-result") if box.name != "ul" else box
            if not ul:
                ul = box if box.name == "ul" else None
            if not ul:
                continue
            main, bonus = _parse_ball_list(ul, game_cfg)
            if not main or len(main) < min(game_cfg.get("main_count", 1), 1):
                continue

            rows.append({
                "lottery_name": game_cfg["lottery_name"],
                "game_name": game_cfg["game_name"],
                "draw_name": game_cfg["draw_name_default"],
                "draw_date": draw_date,
                "draw_time": "",
                "main_numbers": main,
                "bonus_numbers": bonus,
                "bonus_label": bonus_label if bonus else None,
                "source_url": source_url,
                "fuente": "lotteryusa",
            })

    return rows


class LotteryUsaScraper:
    def fetch_page(self, path: str) -> dict:
        url = path if path.startswith("http") else f"{BASE}{path}"
        return fetch_url(
            url,
            timeout=FETCH_TIMEOUT,
            retries=FETCH_RETRIES,
            valid_markers=("c-draw-card", "c-result"),
            source="lotteryusa",
            min_bytes=800,
        )

    def scrape_game(self, slug: str, max_rows: int = 15) -> dict:
        cfg = LOTTERYUSA_GAMES.get(slug)
        if not cfg:
            return {"ok": False, "message": f"Juego no configurado: {slug}", "rows": []}
        page = self.fetch_page(cfg["path"])
        if not page.get("ok"):
            return {**page, "rows": [], "slug": slug}
        try:
            ensure_scraper_deps()
            rows = parse_lotteryusa_html(page["html"], cfg, page["url"])
        except Exception as exc:
            logger.exception("%s LotteryUSA parse error %s: %s", LOG, slug, exc)
            return {"ok": False, "message": str(exc), "rows": [], "slug": slug}
        rows = rows[:max_rows]
        logger.info("%s LotteryUSA %s | resultados=%s", LOG, slug, len(rows))
        return {
            "ok": bool(rows),
            "rows": rows,
            "slug": slug,
            "url": page["url"],
            "status_code": page.get("status_code"),
            "elapsed": page.get("elapsed"),
            "count": len(rows),
            "message": f"{len(rows)} sorteos parseados" if rows else "Sin sorteos parseables",
        }

    def scrape_all(self, lottery_name: str | None = None, max_rows: int = 15) -> dict:
        slugs = list(LOTTERYUSA_GAMES.keys())
        if lottery_name:
            slug = LOTTERY_NAME_TO_SLUG.get(lottery_name.lower())
            slugs = [slug] if slug else []

        all_rows: list[dict] = []
        errors: list[str] = []
        urls: list[str] = []

        for slug in slugs:
            if not slug:
                continue
            res = self.scrape_game(slug, max_rows=max_rows)
            if res.get("rows"):
                all_rows.extend(res["rows"])
                urls.append(res.get("url", ""))
            elif not res.get("ok"):
                errors.append(res.get("message") or f"Fallo {slug}")

        return {
            "ok": bool(all_rows),
            "rows": all_rows,
            "errors": errors,
            "urls": urls,
            "count": len(all_rows),
        }


def probe_lotteryusa() -> dict:
    """Prueba LotteryUSA (Powerball) sin importar a BD."""
    scraper = LotteryUsaScraper()
    res = scraper.scrape_game("powerball", max_rows=5)
    return {
        "fuente": "lotteryusa",
        "url": res.get("url") or f"{BASE}/illinois/powerball/",
        "ok": bool(res.get("rows")),
        "status_code": res.get("status_code"),
        "elapsed": res.get("elapsed"),
        "sorteos_encontrados": len(res.get("rows") or []),
        "error": None if res.get("rows") else (res.get("message") or "Sin sorteos"),
    }


def import_lotteryusa_results(lottery_name: str | None = None) -> dict:
    """Descarga LotteryUSA, importa a BD y devuelve resumen."""
    from services.resultados.illinois_scraper import _import_rows_grouped

    try:
        ensure_scraper_deps()
    except ImportError as exc:
        return {
            "ok": False,
            "message": str(exc),
            "imported": 0,
            "updated": 0,
            "errors": [str(exc)],
            "source": "lotteryusa",
        }

    scraper = LotteryUsaScraper()
    scrape = scraper.scrape_all(lottery_name=lottery_name)
    rows = scrape.get("rows") or []

    if not rows:
        return {
            "ok": False,
            "status": "lotteryusa_empty",
            "source": "lotteryusa",
            "imported": 0,
            "updated": 0,
            "rows_parsed": 0,
            "errors": scrape.get("errors") or ["LotteryUSA sin resultados parseables"],
            "message": "LotteryUSA no devolvió sorteos válidos.",
        }

    imported, updated, errors, game_stats = _import_rows_grouped(rows)
    saved = imported + updated

    if saved == 0 and errors:
        return {
            "ok": False,
            "source": "lotteryusa",
            "imported": 0,
            "updated": 0,
            "errors": errors[:20],
            "message": errors[0],
        }

    from scrapers.cache.usa_results_cache import save_results_snapshot

    save_results_snapshot(rows, fuente="lotteryusa", url=(scrape.get("urls") or [""])[0])

    msg = f"Resultados desde LotteryUSA ({imported} nuevos, {updated} actualizados)."
    return {
        "ok": True,
        "status": "updated" if saved else "no_new",
        "source": "lotteryusa",
        "fuente": "lotteryusa",
        "imported": imported,
        "updated": updated,
        "errors": errors[:20],
        "game_stats": game_stats,
        "message": msg,
        "rows_parsed": len(rows),
        "url": (scrape.get("urls") or [HUB_URL])[0],
    }
