"""
Scraper oficial Illinois Lottery — Results Hub.
Fuente: https://www.illinoislottery.com/results-hub

Solo USA / Illinois. No usar Conectate para USA.
"""

import logging
import re
import time
from datetime import datetime

import cloudscraper

from models import format_numbers, get_all_lotteries, upsert_result
from services.resultados.illinois_cache import load_hub_cache, save_hub_cache
from services.scraper_deps import ensure_scraper_deps, get_beautiful_soup

logger = logging.getLogger(__name__)
LOG_PREFIX = "[USA]"

RESULTS_HUB_URL = "https://www.illinoislottery.com/results-hub"
ILLINOIS_HOME_URL = "https://www.illinoislottery.com/"
FETCH_TIMEOUT = 35
FETCH_RETRIES = 3

# Fallback por juego si results-hub falla (misma estructura HTML)
ILLINOIS_GAME_URLS = {
    "powerball": "https://www.illinoislottery.com/dbg/results/powerball",
    "megamillions": "https://www.illinoislottery.com/dbg/results/megamillions",
    "pick3": "https://www.illinoislottery.com/dbg/results/pick3",
    "pick4": "https://www.illinoislottery.com/dbg/results/pick4",
    "lotto": "https://www.illinoislottery.com/dbg/results/lotto",
    "luckydaylotto": "https://www.illinoislottery.com/dbg/results/luckydaylotto",
    "cash4life": "https://www.illinoislottery.com/dbg/results/cash4life",
}

ILLINOIS_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}

# slug en HTML -> configuración del juego
ILLINOIS_GAMES = {
    "powerball": {
        "game_name": "Powerball",
        "lottery_name": "Powerball",
        "draw_name_default": "Powerball draw",
        "bonus_label": "Powerball",
        "type": "powerball",
    },
    "megamillions": {
        "game_name": "Mega Millions",
        "lottery_name": "Mega Millions",
        "draw_name_default": "Mega Millions draw",
        "bonus_label": "Mega Ball",
        "type": "mega_millions",
    },
    "lotto": {
        "game_name": "Lotto",
        "lottery_name": "Illinois Lotto",
        "draw_name_default": "Evening",
        "bonus_label": "Extra Shot",
        "type": "lotto",
    },
    "luckydaylotto": {
        "game_name": "Lucky Day Lotto",
        "lottery_name": "Lucky Day Lotto",
        "draw_name_default": "Evening",
        "bonus_label": None,
        "type": "lucky_day",
        "has_midday_evening": True,
    },
    "pick3": {
        "game_name": "Pick 3",
        "lottery_name": "Illinois Pick 3",
        "draw_name_default": "Evening",
        "bonus_label": "Fireball",
        "type": "pick3",
        "has_midday_evening": True,
    },
    "pick4": {
        "game_name": "Pick 4",
        "lottery_name": "Illinois Pick 4",
        "draw_name_default": "Evening",
        "bonus_label": "Fireball",
        "type": "pick4",
        "has_midday_evening": True,
    },
    "cash4life": {
        "game_name": "Cash4Life",
        "lottery_name": "Cash4Life",
        "draw_name_default": "Cash4Life draw",
        "bonus_label": "Cash Ball",
        "type": "cash4life",
    },
}

# Juegos soportados en Results Hub (Illinois Lottery oficial)
ILLINOIS_GAME_SLUGS = tuple(ILLINOIS_GAMES.keys())


def _pad_number(n, game_type):
    try:
        val = int(n)
    except (ValueError, TypeError):
        return str(n).strip()
    if game_type in ("pick3", "pick4"):
        return str(val)
    return str(val).zfill(2)


def _parse_date_text(date_text):
    """May 23 2026 -> 2026-05-23"""
    m = re.match(r"(\w+)\s+(\d{1,2})\s+(\d{4})", (date_text or "").strip())
    if not m:
        return None
    month, day, year = m.groups()
    return f"{year}-{MONTHS.get(month.lower(), '01')}-{int(day):02d}"


def _parse_draw_name(schedule_el, game_cfg):
    if game_cfg.get("has_midday_evening"):
        time_el = schedule_el.select_one(".results-content__time")
        if time_el:
            t = time_el.get_text(" ", strip=True).lower()
            if "midday" in t:
                return "Midday"
            if "evening" in t:
                return "Evening"
    return game_cfg["draw_name_default"]


def _parse_balls(balls_container, game_type):
    """Extrae main-ball y last-ball (bonus/fireball/extra shot)."""
    primary = balls_container.select_one(
        ".results-content__primary-container, .latest-results__primary-container"
    )
    if not primary:
        return [], []

    main = []
    for el in primary.select(".main-ball"):
        txt = el.get_text(strip=True)
        if txt.isdigit() or txt:
            main.append(_pad_number(txt, game_type))

    bonus = []
    for el in primary.select(".last-ball"):
        txt = el.get_text(strip=True)
        if txt.isdigit() or txt:
            bonus.append(_pad_number(txt, game_type))

    return main, bonus


def parse_results_hub_html(html):
    """
    Parsea la página results-hub y devuelve lista de filas normalizadas.
    Solo guarda si hay al menos los números principales esperados.
    """
    BeautifulSoup = get_beautiful_soup()
    soup = BeautifulSoup(html, "lxml")
    rows = []

    containers = soup.select(".results-container[class*='results-container--']")
    if not containers:
        containers = soup.select("[class*='results-container--']")

    for container in containers:
        slug = None
        for cls in container.get("class", []):
            if cls.startswith("results-container--"):
                slug = cls.replace("results-container--", "")
                break
        if not slug or slug not in ILLINOIS_GAMES:
            continue

        game_cfg = ILLINOIS_GAMES[slug]
        game_type = game_cfg["type"]

        for content in container.select(".results-content"):
            schedule = content.select_one(".results-content__schedule")
            if not schedule:
                continue

            date_el = schedule.select_one(".results-content__date")
            draw_date = _parse_date_text(date_el.get_text(strip=True) if date_el else "")
            if not draw_date:
                continue

            draw_name = _parse_draw_name(schedule, game_cfg)
            balls_wrap = content.select_one(".results-content__balls")
            if not balls_wrap:
                continue

            main_numbers, bonus_numbers = _parse_balls(balls_wrap, game_type)
            if not main_numbers:
                print(f"ILLINOIS SCRAPER: sin números para {game_cfg['game_name']} {draw_date} {draw_name}")
                continue

            min_main = {
                "pick3": 3,
                "pick4": 4,
                "lucky_day": 5,
                "lotto": 6,
                "powerball": 5,
                "mega_millions": 5,
                "cash4life": 5,
            }.get(game_type, 3)
            if len(main_numbers) < min_main:
                print(
                    f"ILLINOIS SCRAPER: Resultado aún no disponible — "
                    f"{game_cfg['game_name']} {draw_name} ({len(main_numbers)}/{min_main})"
                )
                continue

            bonus_label = game_cfg.get("bonus_label") if bonus_numbers else None

            rows.append({
                "country": "USA",
                "state": "Illinois",
                "game_name": game_cfg["game_name"],
                "lottery_name": game_cfg["lottery_name"],
                "draw_name": draw_name,
                "draw_date": draw_date,
                "draw_time": "",
                "main_numbers": main_numbers,
                "bonus_numbers": bonus_numbers,
                "bonus_label": bonus_label,
                "source_url": RESULTS_HUB_URL,
            })

            print("Juego detectado:", game_cfg["game_name"])
            print("Fecha:", draw_date)
            print("Draw:", draw_name)
            print("Números principales:", main_numbers)
            if bonus_numbers:
                print("Bonus:", bonus_numbers, f"({bonus_label})")
            else:
                print("Bonus: —")

    return rows


def _find_lottery_id(lotteries, name):
    for lot in lotteries:
        if lot["country"] == "USA" and lot["name"].lower() == name.lower():
            return lot["id"]
    return None


class IllinoisResultsHubScraper:
    source_key = "illinois_lottery"
    base_url = "https://www.illinoislottery.com"

    def __init__(self):
        self.session = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        self.session.headers.update(ILLINOIS_FETCH_HEADERS)

    def _fetch_url(self, url: str) -> dict:
        last_error = None
        status_code = None
        for attempt in range(1, FETCH_RETRIES + 1):
            try:
                logger.info(
                    "%s Illinois Hub GET %s (intento %s/%s)",
                    LOG_PREFIX,
                    url,
                    attempt,
                    FETCH_RETRIES,
                )
                resp = self.session.get(
                    url,
                    headers=ILLINOIS_FETCH_HEADERS,
                    timeout=FETCH_TIMEOUT,
                )
                status_code = resp.status_code
                logger.info(
                    "%s Illinois Hub respuesta url=%s status_code=%s bytes=%s",
                    LOG_PREFIX,
                    resp.url,
                    status_code,
                    len(resp.text or ""),
                )
                if status_code == 403:
                    last_error = f"HTTP 403 Forbidden en {url}"
                    time.sleep(1.5 * attempt)
                    continue
                if status_code >= 400:
                    last_error = f"HTTP {status_code} en {url}"
                    time.sleep(1.0 * attempt)
                    continue
                html = resp.text or ""
                if len(html) < 1000:
                    last_error = "Respuesta demasiado corta"
                    continue
                if "results-container" not in html and url.endswith("results-hub"):
                    last_error = "HTML sin bloques results-container"
                    continue
                save_hub_cache(html, url=resp.url, status_code=status_code)
                return {
                    "ok": True,
                    "html": html,
                    "url": resp.url,
                    "status_code": status_code,
                    "from_cache": False,
                }
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "Illinois Hub error url=%s intento=%s: %s",
                    url,
                    attempt,
                    e,
                )
                time.sleep(1.2 * attempt)
        return {
            "ok": False,
            "message": last_error or "Error de red",
            "status_code": status_code,
            "url": url,
        }

    def fetch_game_page(self, game_slug: str) -> dict:
        url = ILLINOIS_GAME_URLS.get(game_slug)
        if not url:
            return {"ok": False, "message": f"URL no configurada para {game_slug}"}
        return self._fetch_url(url)

    def fetch_results_hub(self, allow_cache: bool = True):
        """Descarga Results Hub; fallback por juego; luego caché local."""
        page = self._fetch_url(RESULTS_HUB_URL)
        if page.get("ok"):
            logger.info("%s Illinois parser OK (results-hub)", LOG_PREFIX)
            return page

        logger.warning(
            "%s Illinois Hub falló: url=%s status_code=%s error=%s",
            LOG_PREFIX,
            page.get("url", RESULTS_HUB_URL),
            page.get("status_code"),
            page.get("message"),
        )

        merged_html_parts = []
        merged_url = RESULTS_HUB_URL
        ok_slugs = []
        for slug in ILLINOIS_GAME_URLS:
            gpage = self.fetch_game_page(slug)
            if gpage.get("ok") and gpage.get("html"):
                merged_html_parts.append(gpage["html"])
                ok_slugs.append(slug)
                merged_url = gpage.get("url", merged_url)
        if merged_html_parts:
            combined = "\n".join(merged_html_parts)
            logger.info(
                "%s Illinois parser OK (fallback juegos: %s)",
                LOG_PREFIX,
                ", ".join(ok_slugs),
            )
            save_hub_cache(combined, url=merged_url, status_code=200)
            return {
                "ok": True,
                "html": combined,
                "url": merged_url,
                "status_code": 200,
                "from_cache": False,
                "fallback_games": ok_slugs,
            }

        if allow_cache:
            cached = load_hub_cache()
            if cached.get("ok"):
                logger.info(
                    "Illinois Hub: usando caché local (guardado %s, status previo %s)",
                    cached.get("saved_at"),
                    cached.get("status_code"),
                )
                cached["hub_error"] = page.get("message")
                cached["live_status_code"] = page.get("status_code")
                return cached

        return {
            "ok": False,
            "message": page.get("message", "Illinois Results Hub no respondió."),
            "status_code": page.get("status_code"),
            "url": RESULTS_HUB_URL,
            "from_cache": False,
        }

    def test_connection(self):
        page = self.fetch_results_hub()
        if page.get("ok"):
            rows = parse_results_hub_html(page["html"])
            return {
                "ok": True,
                "message": f"Conexión exitosa con Illinois Results Hub ({len(rows)} sorteos detectados).",
                "url": page["url"],
            }
        return page

    def scrape_all(self):
        page = self.fetch_results_hub()
        if not page.get("ok"):
            return []
        return parse_results_hub_html(page["html"])


def _upsert_illinois_row(row, lotteries):
    """Guarda una fila; devuelve ('inserted'|'updated', None) o (None, error)."""
    lottery_id = _find_lottery_id(lotteries, row["lottery_name"])
    if not lottery_id:
        return None, f"Lotería no registrada: {row['lottery_name']}"

    bonus_single = row["bonus_numbers"][0] if row.get("bonus_numbers") else None
    fireball = bonus_single if row.get("bonus_label") == "Fireball" else None
    bonus_num = bonus_single if row.get("bonus_label") != "Fireball" else None

    _, action = upsert_result(
        lottery_id,
        row["draw_name"],
        row.get("draw_time", ""),
        row["draw_date"],
        format_numbers(row["main_numbers"]),
        bonus_number=bonus_num,
        fireball_number=fireball,
        source_url=row["source_url"],
        confirmed=1,
        main_numbers=format_numbers(row["main_numbers"]),
        bonus_numbers=format_numbers(row["bonus_numbers"]) if row.get("bonus_numbers") else None,
        bonus_label=row.get("bonus_label"),
        game_name=row.get("game_name"),
    )
    return action, None


def _import_rows_grouped(rows, lotteries=None):
    """Importa filas agrupadas; un fallo por juego no detiene los demás."""
    lotteries = lotteries or get_all_lotteries()
    imported = updated = 0
    errors = []
    game_stats = {}

    by_game = {}
    for row in rows:
        key = row.get("lottery_name") or row.get("game_name") or "unknown"
        by_game.setdefault(key, []).append(row)

    for game_name, game_rows in by_game.items():
        g_imported = g_updated = 0
        try:
            for row in game_rows:
                try:
                    action, err = _upsert_illinois_row(row, lotteries)
                    if err:
                        errors.append(err)
                        continue
                    if action == "updated":
                        updated += 1
                        g_updated += 1
                    else:
                        imported += 1
                        g_imported += 1
                except Exception as e:
                    errors.append(f"{game_name} {row.get('draw_date')}: {e}")
        except Exception as e:
            errors.append(f"Error {game_name}: {e}")
            print(f"Error {game_name}: {e}")
        game_stats[game_name] = {"imported": g_imported, "updated": g_updated}

    return imported, updated, errors, game_stats


def _hub_fetch_meta(page: dict) -> dict:
    return {
        "hub_url": page.get("url") or RESULTS_HUB_URL,
        "status_code": page.get("status_code"),
        "from_cache": bool(page.get("from_cache")),
        "cache_saved_at": page.get("saved_at"),
        "hub_error": page.get("hub_error") or page.get("message"),
    }


def import_illinois_results_hub():
    """Importa/actualiza resultados desde results-hub oficial (todos los juegos)."""
    logger.info("Illinois Results Hub — iniciando importación url=%s", RESULTS_HUB_URL)
    try:
        ensure_scraper_deps()
    except ImportError as e:
        return {
            "ok": False,
            "message": str(e),
            "imported": 0,
            "updated": 0,
            "errors": [str(e)],
        }

    scraper = IllinoisResultsHubScraper()
    page = scraper.fetch_results_hub(allow_cache=True)
    meta = _hub_fetch_meta(page)

    if not page.get("ok"):
        logger.error(
            "Illinois Hub sin datos: url=%s status_code=%s error=%s from_cache=%s",
            meta.get("hub_url"),
            meta.get("status_code"),
            page.get("message"),
            meta.get("from_cache"),
        )
        return {
            "ok": False,
            "status": "hub_unreachable",
            "message": (
                "⚠️ Illinois Results Hub no respondió. "
                "Mostrando últimos resultados guardados."
            ),
            "imported": 0,
            "updated": 0,
            "errors": [page.get("message", "hub unreachable")],
            **meta,
        }

    if page.get("from_cache"):
        logger.info(
            "Illinois Hub: parseando desde caché (live status=%s error=%s)",
            page.get("live_status_code"),
            page.get("hub_error"),
        )

    try:
        rows = parse_results_hub_html(page["html"])
    except Exception as e:
        logger.exception("Illinois Hub parse error: %s", e)
        return {
            "ok": False,
            "message": f"Error al analizar Results Hub: {e}",
            "imported": 0,
            "updated": 0,
            "errors": [str(e)],
            **meta,
        }

    if not rows:
        msg = "No se detectaron sorteos nuevos en Results Hub."
        if page.get("from_cache"):
            msg = (
                "⚠️ Illinois Results Hub no respondió. "
                "Caché local sin sorteos parseables; use resultados guardados en BD."
            )
        return {
            "ok": True,
            "status": "no_new",
            "source": "illinois_results_hub",
            "imported": 0,
            "updated": 0,
            "errors": [],
            "message": msg,
            **meta,
        }

    imported, updated, errors, game_stats = _import_rows_grouped(rows)
    saved = imported + updated
    partial = bool(errors) and saved > 0

    print(f"Illinois Results Hub import OK — {imported} nuevos, {updated} actualizados")
    if errors:
        for err in errors[:10]:
            print(f"  ⚠ {err}")

    if saved == 0 and errors:
        return {
            "ok": False,
            "status": "error",
            "source": "illinois_results_hub",
            "imported": 0,
            "updated": 0,
            "errors": errors[:20],
            "game_stats": game_stats,
            "message": f"⚠️ Error temporal obteniendo resultados: {errors[0]}",
        }

    if page.get("from_cache"):
        msg = (
            f"⚠️ No se pudo actualizar en vivo (hub no respondió). "
            f"Datos desde caché local: {imported} nuevos, {updated} actualizados."
        )
    else:
        msg = f"✅ Resultados actualizados correctamente ({imported} nuevos, {updated} actualizados)."
    if partial:
        msg = (
            f"✅ Resultados actualizados ({imported} nuevos, {updated} actualizados). "
            f"⚠️ Algunos juegos con error: {'; '.join(errors[:3])}"
        )

    return {
        "ok": True,
        "status": "updated" if saved else "no_new",
        "partial": partial,
        "source": "illinois_results_hub",
        "imported": imported,
        "updated": updated,
        "errors": errors[:20],
        "game_stats": game_stats,
        "message": msg,
        **meta,
    }


def import_illinois_lottery_now(lottery_name):
    """Importa/actualiza desde Results Hub para una lotería Illinois (últimos en hub)."""
    meta = {}
    try:
        ensure_scraper_deps()
    except ImportError as e:
        return {
            "ok": False,
            "message": f"Error temporal en {lottery_name}: {e}",
            "imported": 0,
            "updated": 0,
            "errors": [str(e)],
        }

    scraper = IllinoisResultsHubScraper()
    try:
        page = scraper.fetch_results_hub(allow_cache=True)
        meta = _hub_fetch_meta(page)
        if not page.get("ok"):
            return {
                "ok": False,
                "status": "hub_unreachable",
                "message": (
                    "⚠️ Illinois Results Hub no respondió. "
                    "Mostrando últimos resultados guardados."
                ),
                "imported": 0,
                "updated": 0,
                **meta,
            }
        all_rows = parse_results_hub_html(page["html"])
    except Exception as e:
        print(f"Error {lottery_name}: {e}")
        return {
            "ok": False,
            "message": f"Error temporal en {lottery_name}: {e}",
            "imported": 0,
            "updated": 0,
            "errors": [str(e)],
        }

    rows = [
        r for r in all_rows
        if r.get("lottery_name", "").lower() == lottery_name.lower()
    ]
    if not rows:
        return {
            "ok": True,
            "status": "no_new",
            "source": "illinois_results_hub",
            "imported": 0,
            "updated": 0,
            "errors": [],
            "message": f"No hay sorteos recientes de {lottery_name} en Results Hub.",
        }

    imported, updated, errors, _ = _import_rows_grouped(rows)
    saved = imported + updated

    if errors and not saved:
        return {
            "ok": False,
            "status": "error",
            "imported": 0,
            "updated": 0,
            "errors": errors[:5],
            "message": f"⚠️ Error temporal en {lottery_name}: {errors[0]}",
        }

    if page.get("from_cache"):
        msg = (
            f"⚠️ No se pudo actualizar {lottery_name} en vivo; "
            f"caché local: {imported} nuevos, {updated} actualizados."
        )
    else:
        msg = f"✅ {lottery_name}: {imported} nuevos, {updated} actualizados."
    if errors:
        msg += f" ⚠️ {errors[0]}"

    return {
        "ok": True,
        "status": "updated" if saved else "no_new",
        "partial": bool(errors),
        "source": "illinois_results_hub",
        "imported": imported,
        "updated": updated,
        "errors": errors[:5],
        "message": msg,
        **meta,
    }


def import_illinois_all_games_safe():
    """
    Actualiza cada juego Illinois por separado; un fallo no detiene el resto.
    Usa una sola descarga del hub y reparte por lotería.
    """
    try:
        ensure_scraper_deps()
    except ImportError as e:
        return {
            "ok": False,
            "message": str(e),
            "imported": 0,
            "updated": 0,
            "errors": [str(e)],
        }

    hub = import_illinois_results_hub()
    if hub.get("ok"):
        return hub

    errors = list(hub.get("errors") or [])
    total_imported = hub.get("imported", 0)
    total_updated = hub.get("updated", 0)

    for _slug, cfg in ILLINOIS_GAMES.items():
        name = cfg["lottery_name"]
        try:
            result = import_illinois_lottery_now(name)
            total_imported += result.get("imported", 0)
            total_updated += result.get("updated", 0)
            if not result.get("ok"):
                errors.append(result.get("message") or f"Error {name}")
        except Exception as e:
            print(f"Error {name}: {e}")
            errors.append(f"{name}: {e}")

    saved = total_imported + total_updated
    if saved > 0:
        msg = f"✅ Resultados actualizados correctamente ({total_imported} nuevos, {total_updated} actualizados)."
        if errors:
            msg += f" ⚠️ Parcial: {'; '.join(errors[:3])}"
        return {
            "ok": True,
            "partial": bool(errors),
            "imported": total_imported,
            "updated": total_updated,
            "errors": errors[:20],
            "message": msg,
        }

    return {
        "ok": False,
        "imported": 0,
        "updated": 0,
        "errors": errors[:20],
        "message": errors[0] if errors else "⚠️ Error temporal obteniendo resultados",
    }
