"""
Servicio LEIDSA — scraping, historial, guardado y análisis.
Nunca importar cloudscraper a nivel de módulo (solo dentro de fetch).
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore

import requests
from bs4 import BeautifulSoup

from services.leidsa_config import (
    BROWSER_HEADERS,
    DEBUG_DIR,
    FETCH_RETRIES,
    FETCH_TIMEOUT,
    LEIDSA_GAMES,
    LEIDSA_TEST_MODE,
    NAME_ALIASES,
    SOURCE_NAME,
    SOURCE_URL,
    TZ_RD,
)

logger = logging.getLogger(__name__)
LOG_PREFIX = "[RD]"


def _log(msg: str) -> None:
    line = msg if msg.startswith(LOG_PREFIX) else f"{LOG_PREFIX} {msg}"
    logger.info(line)
    print(line)


def _safe_response(
    ok: bool = False,
    results: list | None = None,
    error: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    base = {
        "ok": bool(ok),
        "source": SOURCE_NAME,
        "results": list(results or []),
        "error": error,
    }
    base.update(extra)
    return base


def _rd_tz():
    if ZoneInfo:
        try:
            return ZoneInfo(TZ_RD)
        except Exception:
            pass
    try:
        import pytz

        return pytz.timezone(TZ_RD)
    except Exception:
        from datetime import timezone, timedelta

        return timezone(timedelta(hours=-4))


def _now_rd() -> datetime:
    tz = _rd_tz()
    return datetime.now(tz) if tz else datetime.now()


def normalize_lottery_slug(name: str = "", site_slug: str = "") -> str | None:
    if site_slug:
        for slug, cfg in LEIDSA_GAMES.items():
            if cfg.get("site_slug") == site_slug:
                return slug
    raw = re.sub(r"[^a-z0-9]+", " ", (name or "").strip().lower()).strip()
    if raw in LEIDSA_GAMES:
        return raw
    if raw in NAME_ALIASES:
        return NAME_ALIASES[raw]
    for slug, cfg in LEIDSA_GAMES.items():
        if cfg["family_name"].lower() == raw:
            return slug
        if cfg["display_name"].lower() == raw:
            return slug
    compact = raw.replace(" ", "_")
    if compact in LEIDSA_GAMES:
        return compact
    if compact in NAME_ALIASES:
        return NAME_ALIASES[compact]
    return None


def utc_to_fecha_rd(iso_ts: str) -> str:
    if not iso_ts:
        return _now_rd().strftime("%Y-%m-%d")
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if _rd_tz():
            dt = dt.astimezone(_rd_tz())
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return _now_rd().strftime("%Y-%m-%d")


def utc_to_local_hm(iso_ts: str) -> tuple[int, int]:
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if _rd_tz():
            dt = dt.astimezone(_rd_tz())
        return dt.hour, dt.minute
    except ValueError:
        return 0, 0


def _time_24_to_minutes(t24: str) -> int:
    try:
        h, m = map(int, t24.split(":"))
        return h * 60 + m
    except (ValueError, TypeError):
        return 0


def resolve_draw_name(game_slug: str, draw_timestamp: str) -> str:
    cfg = LEIDSA_GAMES.get(game_slug, {})
    draws = cfg.get("draws") or []
    if not draws:
        return "sorteo"
    if len(draws) == 1:
        return draws[0]["draw_name"]
    h, m = utc_to_local_hm(draw_timestamp)
    draw_min = h * 60 + m
    best = draws[0]["draw_name"]
    best_diff = 24 * 60
    for slot in draws:
        diff = abs(draw_min - _time_24_to_minutes(slot.get("time_24h", "")))
        if diff < best_diff:
            best_diff = diff
            best = slot["draw_name"]
    return best


def _format_time_display(draw_time: str, fallback: str = "") -> str:
    if not draw_time:
        return fallback
    try:
        h, m = map(int, str(draw_time).split(":")[:2])
        suffix = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d} {suffix}"
    except (ValueError, TypeError):
        return fallback or draw_time


def detect_blocking(html: str, status_code: int | None = None) -> str | None:
    if not html:
        return "empty_response"
    low = html.lower()[:8000]
    if status_code == 403:
        return "forbidden"
    if status_code == 503:
        return "service_unavailable"
    checks = [
        ("cloudflare", "cloudflare"),
        ("cf-browser-verification", "cloudflare"),
        ("attention required", "cloudflare"),
        ("captcha", "captcha"),
        ("access denied", "access_denied"),
        ("bot protection", "bot_protection"),
        ("forbidden", "forbidden"),
    ]
    for needle, label in checks:
        if needle in low:
            return label
    return None


def detect_hidden_endpoints(html: str) -> list[str]:
    """Busca APIs / fetch / ajax en HTML y scripts."""
    if not html:
        return []
    found: set[str] = set()
    patterns = [
        r'https?://[a-zA-Z0-9._/-]+(?:api|graphql|result|sorteo|draw|lottery|game)[a-zA-Z0-9._/?=&%-]*',
        r'"(/[^"\s]*(?:api|result|sorteo|graphql)[^"\s]*)"',
        r"'(/[^'\s]*(?:api|result|sorteo|graphql)[^'\s]*)'",
        r'fetch\s*\(\s*["\']([^"\']+)["\']',
        r'axios\.[a-z]+\s*\(\s*["\']([^"\']+)["\']',
    ]
    for pat in patterns:
        for m in re.finditer(pat, html, re.I):
            u = m.group(1) if m.lastindex else m.group(0)
            u = u.strip('"\'')
            if u.startswith("/"):
                u = "https://www.leidsa.com" + u
            if "leidsa" in u.lower() or "api" in u.lower():
                if not u.endswith((".png", ".jpg", ".css", ".js", ".woff", ".svg")):
                    found.add(u.split("\\")[0][:200])
    for m in re.finditer(r'/_next/static/chunks/[^"\']+\.js', html):
        found.add("https://www.leidsa.com" + m.group(0))
    urls = sorted(found)
    for u in urls:
        if "/api/" in u.lower() or "graphql" in u.lower() or "resultado" in u.lower():
            _log(f"API DETECTADA: {u}")
    return urls


def _save_debug_raw(html: str, json_data: Any = None, tag: str = "fetch") -> None:
    if not LEIDSA_TEST_MODE:
        return
    try:
        base = os.path.join(os.path.dirname(os.path.dirname(__file__)), DEBUG_DIR)
        os.makedirs(base, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if html:
            with open(os.path.join(base, f"{tag}_{ts}.html"), "w", encoding="utf-8") as f:
                f.write(html)
        if json_data is not None:
            with open(os.path.join(base, f"{tag}_{ts}.json"), "w", encoding="utf-8") as f:
                json.dump(json_data, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        _log(f"No se pudo guardar debug raw: {exc}")


def _save_debug_html_file(html: str) -> str:
    """Guarda siempre el último HTML en data/debug/leidsa_debug.html."""
    base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "debug")
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, "leidsa_debug.html")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html or "")
        _log(f"HTML debug guardado: {path}")
    except OSError as exc:
        _log(f"No se pudo guardar leidsa_debug.html: {exc}")
    return path


def _html_has_embedded_results(html: str) -> bool:
    if not html:
        return False
    low = html.lower()
    return (
        "drawnvalues" in low
        or "previousdrawdetails" in low
        or "latestdrawdetails" in low
    )


def fetch_leidsa_html() -> dict[str, Any]:
    """Descarga home leidsa.com — cloudscraper + reintentos."""
    from services.leidsa_http import fetch_leidsa_page, log_leidsa_scraper

    _log(f"URL: {SOURCE_URL}")
    out = fetch_leidsa_page(SOURCE_URL, juego="home", min_bytes=5000)
    if out.get("ok"):
        html = out["html"]
        _save_debug_html_file(html)
        api_urls = detect_hidden_endpoints(html)
        _save_debug_raw(html, {"api_urls": api_urls}, "html")
        return _safe_response(
            ok=True,
            html=html,
            method=out.get("method"),
            status_code=out.get("status_code"),
            html_length=len(html),
            html_detected=True,
            possible_api_urls=api_urls,
            blocking_type=None,
            elapsed=out.get("elapsed"),
        )

    blocking = detect_blocking(out.get("html", ""), out.get("status_code"))
    err = out.get("error") or "No se pudo conectar con leidsa.com"
    log_leidsa_scraper(
        url=SOURCE_URL,
        status=out.get("status_code") or "error",
        tiempo=out.get("elapsed"),
        juego="home",
        error=err,
    )
    return _safe_response(
        ok=False,
        error=err,
        status_code=out.get("status_code"),
        html_length=0,
        html_detected=False,
        blocking_type=blocking or ("forbidden" if out.get("status_code") == 403 else None),
        elapsed=out.get("elapsed"),
    )


def _valid_numbers(nums: list) -> bool:
    if not nums:
        return False
    if len(nums) > 25:
        return False
    return all(isinstance(n, int) and 0 <= n <= 99 for n in nums)


def _row_from_game_block(
    family: str,
    site_slug: str,
    draw_id: str,
    nums_raw: str,
    bonus_raw: str | None,
    ts: str,
) -> dict | None:
    game_slug = normalize_lottery_slug(family, site_slug)
    if not game_slug:
        return None
    main_nums = [int(x) for x in re.findall(r"\d+", nums_raw or "")]
    if not _valid_numbers(main_nums):
        return None
    bonus_nums = []
    if bonus_raw:
        bonus_nums = [int(x) for x in re.findall(r"\d+", bonus_raw)]
    draw_name = resolve_draw_name(game_slug, ts)
    cfg = LEIDSA_GAMES[game_slug]
    slot = next((d for d in cfg["draws"] if d["draw_name"] == draw_name), cfg["draws"][0])
    return {
        "lottery": game_slug,
        "lottery_name": cfg["lottery_name"],
        "draw": draw_name,
        "fecha_rd": utc_to_fecha_rd(ts),
        "numeros": main_nums,
        "bonus": bonus_nums,
        "draw_time": slot.get("time_24h", ""),
        "time_display": slot.get("time", ""),
        "fuente": SOURCE_NAME,
        "estado": "publicado",
        "draw_id": draw_id,
        "draw_timestamp": ts,
    }


def _parse_draw_detail_match(
    family: str,
    site_slug: str,
    draw_id: str,
    drawn_raw: str,
    bonus_raw: str | None,
    ts: str,
) -> dict | None:
    return _row_from_game_block(
        family,
        site_slug,
        draw_id,
        drawn_raw,
        bonus_raw,
        ts,
    )


def _parse_escaped_json_blocks(html: str) -> list[dict]:
    """JSON escapado en HTML de Next.js — sin límite de 1200 chars."""
    rows = []
    blocks = html.split('{\\"gameId\\":')
    for block in blocks[1:]:
        if "drawnValues" not in block and "drawnvalues" not in block.lower():
            continue
        if "Leidsa" not in block and '\\"gameProvider\\"' not in block:
            continue

        name_m = re.search(r'\\"gameFamilyName\\":\\"([^\\"]+)', block)
        if not name_m:
            continue
        family = name_m.group(1)
        slug_m = re.search(r'\\"slug\\":\\"([^\\"]+)', block)

        detail_pattern = re.compile(
            r'\\"(?:previous|latest)DrawDetails\\":\{(.*?)\\}(?=,\\"hasLeadZero\\"|,\\"gameId\\"|$)',
            re.DOTALL,
        )
        best_row = None
        best_ts = ""
        for det in detail_pattern.finditer(block):
            chunk = det.group(1)
            prev_m = re.search(
                r'\\"drawId\\":\\"([^\\"]*)\\",\\"drawnValues\\":\[([^\]]*)\]',
                chunk,
            )
            if not prev_m:
                prev_m = re.search(r'\\"drawnValues\\":\[([^\]]*)\]', chunk)
                if not prev_m:
                    continue
                draw_id, drawn_raw = "", prev_m.group(1)
            else:
                draw_id, drawn_raw = prev_m.group(1), prev_m.group(2)
            bonus_m = re.search(r'\\"bonusRoundsValues\\":\[([^\]]*)\]', chunk)
            ts_m = re.search(r'\\"drawTimestamp\\":\\"([^\\"]+)', chunk)
            ts = ts_m.group(1) if ts_m else ""
            row = _parse_draw_detail_match(
                family,
                slug_m.group(1) if slug_m else "",
                draw_id,
                drawn_raw,
                bonus_m.group(1) if bonus_m else None,
                ts,
            )
            if row and ts >= best_ts:
                best_ts = ts
                best_row = row

        if not best_row:
            prev_m = re.search(
                r'\\"drawnValues\\":\[([^\]]*)\].{0,500}?\\"drawTimestamp\\":\\"([^\\"]+)\\"',
                block,
                re.DOTALL,
            )
            if prev_m:
                bonus_m = re.search(r'\\"bonusRoundsValues\\":\[([^\]]*)\]', block)
                best_row = _parse_draw_detail_match(
                    family,
                    slug_m.group(1) if slug_m else "",
                    "",
                    prev_m.group(1),
                    bonus_m.group(1) if bonus_m else None,
                    prev_m.group(2),
                )

        if best_row:
            rows.append(best_row)
    return rows


def _parse_unescaped_json_blocks(html: str) -> list[dict]:
    rows = []
    for m in re.finditer(
        r'"gameFamilyName"\s*:\s*"([^"]+)"[^}]{0,800}?"gameProvider"\s*:\s*"Leidsa"',
        html,
        re.DOTALL,
    ):
        chunk = html[m.start(): m.start() + 2500]
        slug_m = re.search(r'"slug"\s*:\s*"([^"]+)"', chunk)
        prev_m = re.search(
            r'"previousDrawDetails"\s*:\s*\{[^}]*?"drawId"\s*:\s*"([^"]*)"'
            r'[^}]*?"drawnValues"\s*:\s*\[([^\]]*)\]',
            chunk,
            re.DOTALL,
        )
        ts_m = re.search(r'"drawTimestamp"\s*:\s*"([^"]+)"', chunk)
        bonus_m = re.search(r'"bonusRoundsValues"\s*:\s*\[([^\]]*)\]', chunk)
        if not prev_m or not ts_m:
            continue
        row = _row_from_game_block(
            m.group(1),
            slug_m.group(1) if slug_m else "",
            prev_m.group(1),
            prev_m.group(2),
            bonus_m.group(1) if bonus_m else None,
            ts_m.group(1),
        )
        if row:
            rows.append(row)
    return rows


def _parse_next_data(html: str) -> list[dict]:
    rows = []
    m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return rows
    try:
        data = json.loads(m.group(1))
        rows = _dedupe_rows(_extract_rows_from_json_tree(data))
        if rows:
            return rows
        blob = json.dumps(data)
        for prev_m in re.finditer(
            r'"gameFamilyName"\s*:\s*"([^"]+)".{0,200}?"gameProvider"\s*:\s*"Leidsa".{0,2000}?'
            r'"(?:previous|latest)DrawDetails"\s*:\s*\{[^}]*?"drawnValues"\s*:\s*\[([^\]]*)\]'
            r'.{0,400}?"drawTimestamp"\s*:\s*"([^"]+)"',
            blob,
            re.DOTALL,
        ):
            row = _row_from_game_block(
                prev_m.group(1), "", "", prev_m.group(2), None, prev_m.group(3)
            )
            if row:
                rows.append(row)
    except (json.JSONDecodeError, TypeError) as exc:
        _log(f"__NEXT_DATA__ parse error: {exc}")
    return rows


def _parse_regex_global_fallback(html: str) -> list[dict]:
    """Último recurso: regex sobre todo el HTML si hay drawnValues."""
    rows = []
    patterns = [
        (
            "escaped_bundle",
            re.compile(
                r'\\"gameFamilyName\\":\\"([^\\"]+)\\".{0,4000}?'
                r'\\"drawnValues\\":\[([^\]]*)\].{0,600}?'
                r'\\"drawTimestamp\\":\\"([^\\"]+)\\"',
                re.DOTALL,
            ),
        ),
        (
            "json_bundle",
            re.compile(
                r'"gameFamilyName"\s*:\s*"([^"]+)".{0,4000}?'
                r'"drawnValues"\s*:\s*\[([^\]]*)\].{0,600}?'
                r'"drawTimestamp"\s*:\s*"([^"]+)"',
                re.DOTALL,
            ),
        ),
    ]
    for label, pat in patterns:
        for m in pat.finditer(html):
            bonus_m = re.search(
                r'bonusRoundsValues\\":\[([^\]]*)\]|"bonusRoundsValues"\s*:\s*\[([^\]]*)\]',
                m.group(0),
            )
            bonus_raw = None
            if bonus_m:
                bonus_raw = bonus_m.group(1) or bonus_m.group(2)
            row = _row_from_game_block(
                m.group(1),
                "",
                "",
                m.group(2),
                bonus_raw,
                m.group(3),
            )
            if row:
                rows.append(row)
        if rows:
            _log(f"{LOG_PREFIX} Selector usado: regex_{label}")
    return rows


def _parse_script_json_blobs(html: str) -> list[dict]:
    rows = []
    soup = BeautifulSoup(html, "lxml")
    for script in soup.find_all("script"):
        text = script.string or ""
        if len(text) < 200 or "drawnValues" not in text:
            continue
        for prev_m in re.finditer(
            r'"drawnValues"\s*:\s*\[([^\]]+)\].{0,300}?"drawTimestamp"\s*:\s*"([^"]+)"',
            text,
            re.DOTALL,
        ):
            fam_m = re.search(r'"gameFamilyName"\s*:\s*"([^"]+)"', text)
            if not fam_m:
                continue
            row = _row_from_game_block(
                fam_m.group(1), "", "", prev_m.group(1), None, prev_m.group(2)
            )
            if row:
                rows.append(row)
    return rows


def _dedupe_rows(rows: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for r in rows:
        key = (r["lottery"], r["draw"], r["fecha_rd"], r.get("draw_id", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _extract_rows_from_json_tree(obj: Any, rows: list | None = None) -> list[dict]:
    """Recorre JSON buscando previousDrawDetails / drawnValues."""
    if rows is None:
        rows = []
    if isinstance(obj, dict):
        prev = None
        for key in (
            "previousDrawDetails",
            "latestDrawDetails",
            "previous_draw_details",
            "latest_draw_details",
        ):
            cand = obj.get(key)
            if isinstance(cand, dict) and cand.get("drawnValues"):
                prev = cand
                break
        if isinstance(prev, dict) and prev.get("drawnValues"):
            fam = obj.get("gameFamilyName") or (obj.get("gameId") or {}).get("gameFamilyName", "")
            slug = obj.get("slug", "")
            ts = prev.get("drawTimestamp", "")
            bonus = prev.get("bonusRoundsValues")
            row = _row_from_game_block(
                str(fam), str(slug), str(prev.get("drawId", "")),
                ",".join(str(x) for x in prev.get("drawnValues", [])),
                ",".join(str(x) for x in bonus) if bonus else None,
                str(ts),
            )
            if row:
                rows.append(row)
        for v in obj.values():
            _extract_rows_from_json_tree(v, rows)
    elif isinstance(obj, list):
        for item in obj:
            _extract_rows_from_json_tree(item, rows)
    return rows


def try_fetch_json_api(api_urls: list[str]) -> dict[str, Any]:
    """Si hay endpoint JSON real, usarlo antes que HTML (no chunks webpack)."""
    headers = {**BROWSER_HEADERS, "Accept": "application/json, text/plain, */*"}
    candidates = []
    for url in api_urls:
        low = url.lower()
        if "/_next/static/" in low or low.endswith(".js"):
            continue
        if any(k in low for k in ("/api/", "graphql", ".json", "resultado", "sorteo", "draw")):
            candidates.append(url)
    for url in candidates:
        if "storage.googleapis" in url or url.endswith((".png", ".jpg", ".css")):
            continue
        try:
            resp = requests.get(url, headers=headers, timeout=FETCH_TIMEOUT)
            if resp.status_code != 200:
                continue
            text = (resp.text or "").strip()
            if not text.startswith("{") and not text.startswith("["):
                continue
            data = resp.json()
            rows = _dedupe_rows(_extract_rows_from_json_tree(data))
            if rows:
                _log(f"JSON API OK: {url} -> {len(rows)} resultados")
                _save_debug_raw("", data, "api_json")
                return _safe_response(ok=True, results=rows, parser="json_api", api_url=url)
        except Exception as exc:
            _log(f"API falló {url}: {exc}")
    return _safe_response(ok=False, error="Sin API JSON utilizable", results=[])


def fetch_js_and_extract_json(js_urls: list[str], limit: int = 3) -> dict[str, Any]:
    """Fallback: leer scripts JS buscando JSON embebido."""
    headers = {**BROWSER_HEADERS, "Accept": "*/*"}
    for url in js_urls[:limit]:
        if not url.endswith(".js"):
            continue
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code != 200 or len(resp.text) < 500:
                continue
            parsed = parse_leidsa_html(resp.text)
            if parsed.get("ok") and parsed.get("results"):
                return parsed
        except Exception as exc:
            _log(f"JS parse falló {url}: {exc}")
    return _safe_response(ok=False, results=[])


def parse_leidsa_html(html: str) -> dict[str, Any]:
    """Parse tolerante — varias estrategias; nunca 0 si hay drawnValues en HTML."""
    if not html:
        return _safe_response(ok=False, error="HTML vacío", parser="none")

    embedded_count = html.lower().count("drawnvalues")
    _log(f"{LOG_PREFIX} drawnValues en HTML: {embedded_count}")

    parsers = [
        ("next_data_tree", _parse_next_data),
        ("escaped_json", _parse_escaped_json_blocks),
        ("unescaped_json", _parse_unescaped_json_blocks),
        ("script_json", _parse_script_json_blobs),
        ("regex_global", _parse_regex_global_fallback),
    ]
    all_rows: list[dict] = []
    used = []
    for name, fn in parsers:
        try:
            chunk = fn(html)
            if chunk:
                used.append(name)
                all_rows.extend(chunk)
                _log(f"{LOG_PREFIX} Selector usado: {name} (+{len(chunk)})")
        except Exception as exc:
            _log(f"Parser {name} error: {exc}")
            logger.exception("LEIDSA parser %s", name)

    rows = _dedupe_rows(all_rows)
    _log(f"{LOG_PREFIX} Resultados parseados: {len(rows)} (parsers: {', '.join(used) or 'ninguno'})")

    if not rows and embedded_count > 0:
        rows = _dedupe_rows(_parse_regex_global_fallback(html))
        if rows:
            used.append("regex_global_retry")
            _log(f"{LOG_PREFIX} Selector usado: regex_global_retry")

    if not rows:
        return _safe_response(
            ok=False,
            error="No se detectaron resultados válidos en leidsa.com",
            parser=",".join(used) or "none",
            html_has_drawnvalues=embedded_count,
        )

    parser_label = used[0] if used else "leidsa"
    _log(f"{LOG_PREFIX} Parser usado: {parser_label}")
    _log(f"{LOG_PREFIX} LEIDSA parser OK — resultados encontrados: {len(rows)}")
    return _safe_response(ok=True, results=rows, parser=parser_label or "leidsa")


def scrape_leidsa_via_results_pages() -> dict[str, Any]:
    """Fallback: último sorteo por juego desde /results/Leidsa/{juego}/{drawId}."""
    from services.leidsa_config import LEIDSA_HISTORY_GAMES
    from services.leidsa_history import build_results_url, discover_latest_draw_ids, parse_draw_results_history
    from services.leidsa_http import fetch_leidsa_page, log_leidsa_scraper

    draw_ids = discover_latest_draw_ids()
    rows: list[dict] = []
    errors: list[str] = []
    method = "results_pages"

    for game in LEIDSA_HISTORY_GAMES:
        url = build_results_url(game, draw_ids)
        fetch = fetch_leidsa_page(url, juego=game["name"], require_draw_data=True, min_bytes=5000)
        if not fetch.get("ok"):
            err = fetch.get("error") or "fetch failed"
            errors.append(f"{game['name']}: {err}")
            continue
        parsed = parse_draw_results_history(
            fetch["html"],
            game["family_name"],
            days=7,
            limit=2,
            slug=game["slug"],
        )
        if not parsed:
            parsed = parse_leidsa_html(fetch["html"]).get("results") or []
            parsed = [r for r in parsed if r.get("lottery") == game["slug"]][:1]
        if parsed:
            rows.append(parsed[0])
            log_leidsa_scraper(
                url=url,
                status=fetch.get("status_code"),
                tiempo=fetch.get("elapsed"),
                juego=game["name"],
                resultados=1,
            )
        else:
            errors.append(f"{game['name']}: parser sin filas")
            log_leidsa_scraper(
                url=url,
                status=fetch.get("status_code"),
                tiempo=fetch.get("elapsed"),
                juego=game["name"],
                resultados=0,
                error="parser sin filas",
            )

    rows = _dedupe_rows(rows)
    if rows:
        return _safe_response(
            ok=True,
            results=rows,
            rows=rows,
            parser="results_pages",
            method=method,
            errors=errors,
            message=f"OK vía páginas de resultados ({len(rows)} juegos)",
        )
    return _safe_response(
        ok=False,
        error="; ".join(errors[:6]) if errors else "Sin resultados en páginas LEIDSA",
        message="LEIDSA no respondió en home ni en páginas de resultados",
        rows=[],
        errors=errors,
        parser="results_pages",
        method=method,
    )


def scrape_leidsa_results() -> dict[str, Any]:
    """Cadena: LEIDSA oficial → EnLoteria → LD.us → Yelu → NacionalLoteria."""
    from services.leidsa_fallback.orchestrator import scrape_leidsa_with_fallbacks

    return scrape_leidsa_with_fallbacks()


def fetch_leidsa_history(limit_days: int = 30) -> dict[str, Any]:
    """
    Intenta obtener historial desde la página principal y JSON embebido.
    Nota: leidsa.com suele exponer el último sorteo por juego en home;
    el historial profundo se complementa con registros ya guardados en DB.
    """
    fetch = fetch_leidsa_html()
    if not fetch.get("ok"):
        return _safe_response(
            ok=False,
            error=fetch.get("error"),
            limit_days=limit_days,
        )

    html = fetch.get("html", "")
    parsed = parse_leidsa_html(html)
    rows = list(parsed.get("results") or [])

    api_urls = sorted(set(re.findall(
        r'https?://[^\s"\'<>]+(?:api|result|sorteo|quiniela|json)[^\s"\'<>]*',
        html,
        re.I,
    )))
    if api_urls:
        _log(f"API hints found: {len(api_urls)}")

    cutoff = (_now_rd() - timedelta(days=limit_days)).strftime("%Y-%m-%d")
    rows = [r for r in rows if r.get("fecha_rd", "") >= cutoff]

    try:
        from models import get_leidsa_history_from_db

        db_rows = get_leidsa_history_from_db(limit_days=limit_days)
        seen = {(r["lottery"], r["draw"], r["fecha_rd"]) for r in rows}
        for dr in db_rows:
            key = (dr.get("lottery_slug"), dr.get("draw_name"), dr.get("draw_date"))
            if key not in seen:
                rows.append({
                    "lottery": dr.get("lottery_slug"),
                    "lottery_name": dr.get("lottery_display"),
                    "draw": dr.get("draw_name"),
                    "fecha_rd": dr.get("draw_date"),
                    "numeros": dr.get("numeros_list", []),
                    "fuente": dr.get("fuente", SOURCE_NAME),
                    "estado": dr.get("estado", "publicado"),
                    "from_db": True,
                })
    except Exception as exc:
        _log(f"DB history merge skipped: {exc}")

    rows.sort(key=lambda r: (r.get("fecha_rd", ""), r.get("lottery", "")), reverse=True)
    return _safe_response(
        ok=True,
        results=rows,
        limit_days=limit_days,
        api_hints=api_urls[:10],
        count=len(rows),
    )


def _ensure_lottery_ids() -> dict[str, int]:
    from models import create_draw_time, get_draw_times, get_lottery_by_slug, seed_leidsa_lotteries

    seed_leidsa_lotteries()
    ids = {}
    for slug, cfg in LEIDSA_GAMES.items():
        lot = get_lottery_by_slug(slug)
        if not lot:
            continue
        ids[slug] = lot["id"]
        existing = {d["draw_name"] for d in get_draw_times(lot["id"])}
        for slot in cfg["draws"]:
            if slot["draw_name"] not in existing:
                create_draw_time(
                    lot["id"], slot["draw_name"], slot["time_24h"], TZ_RD, active=1
                )
    return ids


def save_leidsa_rows(rows: list[dict]) -> dict[str, Any]:
    from models import format_numbers, upsert_result

    lottery_ids = _ensure_lottery_ids()
    inserted = updated = skipped = 0
    errors: list[str] = []

    for row in rows:
        slug = row.get("lottery")
        if not slug or not row.get("numeros"):
            skipped += 1
            continue
        lid = lottery_ids.get(slug)
        if not lid:
            skipped += 1
            errors.append(f"Sin lotería: {slug}")
            continue
        if not _valid_numbers(row.get("numeros", [])):
            skipped += 1
            continue

        nums = format_numbers(row["numeros"])
        bonus = format_numbers(row.get("bonus", [])) if row.get("bonus") else None
        try:
            _, action = upsert_result(
                lid,
                row["draw"],
                row.get("draw_time", ""),
                row["fecha_rd"],
                nums,
                source_url=SOURCE_URL,
                confirmed=1,
                main_numbers=nums,
                bonus_numbers=bonus,
                game_name=slug,
                estado=row.get("estado", "publicado"),
                fuente=row.get("fuente", SOURCE_NAME),
            )
            if action == "inserted":
                inserted += 1
            else:
                updated += 1
        except Exception as exc:
            skipped += 1
            errors.append(f"{slug}/{row.get('draw')}: {exc}")

    return _safe_response(
        ok=True,
        inserted=inserted,
        updated=updated,
        skipped=skipped,
        errors=errors,
        imported=inserted,
    )


def _log_fetch_result(scrape: dict, fetch_extra: dict | None = None) -> None:
    from models import log_leidsa_fetch

    log_leidsa_fetch(
        ok=bool(scrape.get("ok")),
        status_code=scrape.get("status_code") or (fetch_extra or {}).get("status_code"),
        parser=scrape.get("parser", ""),
        method=scrape.get("method", ""),
        results_found=len(scrape.get("results") or scrape.get("rows") or []),
        html_length=scrape.get("html_length", 0),
        error=scrape.get("error"),
        blocking_type=scrape.get("blocking_type", ""),
        api_urls=scrape.get("possible_api_urls") or [],
    )


def _latest_saved_leidsa_date() -> str | None:
    try:
        from models import get_leidsa_history_from_db

        hist = get_leidsa_history_from_db(limit_days=365)
        dates = [r.get("draw_date") for r in hist if r.get("draw_date")]
        return max(dates) if dates else None
    except Exception:
        return None


def update_leidsa_now() -> dict[str, Any]:
    """Actualización manual — nunca lanza excepción."""
    try:
        from models import log_leidsa_sync

        scrape = scrape_leidsa_results()
        _log_fetch_result(scrape)

        if not scrape.get("ok"):
            err = scrape.get("error") or scrape.get("message") or "Leidsa no respondió"
            if scrape.get("blocking_type") == "cloudflare" or scrape.get("status_code") == 403:
                err = f"HTTP {scrape.get('status_code') or 403} — acceso bloqueado por leidsa.com/WAF"
            from models import get_leidsa_history_from_db

            saved = len(get_leidsa_history_from_db(limit_days=90))
            latest_date = _latest_saved_leidsa_date()
            if saved > 0:
                msg = "No se pudo actualizar en vivo. Mostrando últimos resultados guardados."
                if latest_date:
                    msg += f" Última fecha guardada: {latest_date}."
                _log(f"LEIDSA en vivo falló; {saved} resultados previos en BD (no se borran)")
            else:
                msg = f"❌ LEIDSA en vivo falló: {err}"
            log_leidsa_sync(ok=False, message=msg, error=err)
            return _safe_response(
                ok=False,
                live_failed=True,
                used_db_fallback=bool(saved),
                saved_count=saved,
                latest_date=latest_date,
                status="error",
                message=msg,
                inserted=0,
                updated=0,
                skipped=0,
                parser=scrape.get("parser") or "leidsa",
                results_found=0,
                error=err,
                detalle=err,
                status_code=scrape.get("status_code"),
                blocking_type=scrape.get("blocking_type"),
                errors=scrape.get("errors") or [],
                fuente=SOURCE_NAME,
                attempts=scrape.get("attempts") or [],
            )

        rows = scrape.get("results") or scrape.get("rows") or []
        if not rows:
            err = "Parser sin resultados — no se guardan filas vacías"
            log_leidsa_sync(ok=False, message=err, error=err)
            return _safe_response(
                ok=False,
                live_failed=True,
                status="error",
                message=err,
                error=err,
                detalle=err,
                inserted=0,
                updated=0,
                skipped=0,
                parser=scrape.get("parser") or "leidsa",
                status_code=scrape.get("status_code"),
                fuente=SOURCE_NAME,
            )

        save = save_leidsa_rows(rows)
        saved_total = int(save.get("inserted") or 0) + int(save.get("updated") or 0)
        if saved_total == 0 and not rows:
            err = "Sin resultados válidos para guardar"
            return _safe_response(ok=False, error=err, message=err, live_failed=True)

        fuente_label = scrape.get("fuente_label") or scrape.get("source") or SOURCE_NAME
        fuente_key = scrape.get("fuente_usada") or scrape.get("fuente") or "leidsa_official"
        latest_date = scrape.get("latest_date") or _latest_saved_leidsa_date()

        from services.leidsa_fallback.log import log_leidsa_fallback

        log_leidsa_fallback(
            fuente=fuente_key,
            url=scrape.get("url") or "",
            status=scrape.get("status_code") or 200,
            juego="todos",
            resultados_encontrados=len(rows),
            nuevos=save.get("inserted", 0),
            actualizados=save.get("updated", 0),
        )
        msg = (
            f"Actualizado desde: {fuente_label} — "
            f"{save.get('inserted', 0)} nuevos, {save.get('updated', 0)} actualizados."
        )
        log_leidsa_sync(
            ok=True,
            message=msg,
            imported=save.get("inserted", 0),
            updated=save.get("updated", 0),
        )
        n_found = len(scrape.get("results") or [])
        _log(f"Parser usado: {scrape.get('parser')} — resultados encontrados: {n_found}")
        return _safe_response(
            ok=True,
            status="updated" if save.get("inserted", 0) + save.get("updated", 0) else "no_new",
            message=msg,
            inserted=save.get("inserted", 0),
            updated=save.get("updated", 0),
            skipped=save.get("skipped", 0),
            games=n_found,
            parser=scrape.get("parser") or "leidsa",
            results_found=n_found,
            error=None,
            fuente=fuente_key,
            fuente_usada=fuente_key,
            fuente_label=fuente_label,
            latest_date=latest_date,
            fallback_used=bool(scrape.get("fallback_used")),
        )
    except Exception as exc:
        logger.exception("update_leidsa_now")
        try:
            from models import log_leidsa_sync, log_leidsa_fetch
            log_leidsa_sync(ok=False, message=str(exc), error=str(exc))
            log_leidsa_fetch(ok=False, error=str(exc), results_found=0)
        except Exception:
            pass
        return _safe_response(
            ok=False,
            status="error",
            message="LEIDSA no respondió o cambió su formato.",
            error=str(exc),
            inserted=0,
            updated=0,
            skipped=0,
        )


def get_leidsa_real_results_board(fecha: str | None = None) -> list[dict]:
    """Solo resultados REALES guardados (con números). Sin placeholders de horario."""
    from models import get_leidsa_history_from_db, get_leidsa_results_for_date

    fecha = fecha or _now_rd().strftime("%Y-%m-%d")
    stored = get_leidsa_results_for_date(fecha)
    if not stored:
        historial = get_leidsa_history_from_db(limit_days=14)
        seen_games = set()
        for r in historial:
            key = (r.get("lottery_slug"), r.get("draw_name"), r.get("draw_date"))
            if key in seen_games:
                continue
            seen_games.add(key)
            nums = r.get("numeros_list") or []
            if not nums:
                continue
            stored.append(r)
            if len(stored) >= 12:
                break

    board = []
    for r in stored:
        nums = r.get("numeros_list") or []
        if not nums:
            continue
        time_disp = _format_time_display(r.get("draw_time", ""), "")
        board.append({
            "lottery": r.get("lottery_slug", ""),
            "lottery_name": r.get("lottery_display", ""),
            "draw": r.get("draw_name", ""),
            "time": time_disp,
            "fecha_rd": r.get("draw_date", fecha),
            "estado": "publicado",
            "color": "verde",
            "numeros": nums,
            "fuente": r.get("fuente") or SOURCE_NAME,
            "cached": r.get("draw_date") != fecha,
        })
    return board


def _build_debug_panel(
    fetch_log: dict | None,
    live_ok: bool,
    *,
    using_cache: bool = False,
    saved_count: int = 0,
) -> dict:
    fl = fetch_log or {}
    status = fl.get("status_code")
    if using_cache and saved_count > 0:
        status_label = f"📦 BD ({saved_count} guardados)"
    elif live_ok and status == 200:
        status_label = f"🟢 STATUS {status}"
    elif status:
        status_label = f"🔴 STATUS {status}"
    else:
        status_label = "🔴 STATUS ERROR"
    results_found = fl.get("results_found", 0)
    if using_cache and saved_count:
        results_found = max(results_found, saved_count)
    return {
        "status_label": status_label,
        "status_code": status,
        "parser": (fl.get("parser") or ("db_cache" if using_cache else "—")),
        "method": fl.get("method") or ("cache" if using_cache else "—"),
        "results_found": results_found,
        "saved_count": saved_count,
        "last_attempt": fl.get("created_at", "—"),
        "error": fl.get("error") or fl.get("blocking_type") or "",
        "blocking_type": fl.get("blocking_type") or "",
        "html_length": fl.get("html_length", 0),
    }


def get_leidsa_dashboard(
    fecha: str | None = None,
    history_days: int | None = None,
) -> dict[str, Any]:
    """Payload API/UI con debug, cache e historial real."""
    try:
        from models import get_leidsa_history_from_db, get_last_leidsa_fetch, get_last_leidsa_sync
        from services.leidsa_config import HISTORY_DEFAULT_DAYS

        fecha = fecha or _now_rd().strftime("%Y-%m-%d")
        hist_days = history_days or HISTORY_DEFAULT_DAYS
        fetch_log = get_last_leidsa_fetch()
        last_sync = get_last_leidsa_sync()
        board = get_leidsa_real_results_board(fecha)
        historial = get_leidsa_history_from_db(limit_days=hist_days)
        saved_count = len(historial)
        has_saved = saved_count > 0 or len(board) > 0

        live_ok = bool(
            fetch_log
            and fetch_log.get("ok")
            and (fetch_log.get("results_found") or 0) > 0
        )
        using_cache = not live_ok and has_saved
        debug = _build_debug_panel(
            fetch_log,
            live_ok=live_ok,
            using_cache=using_cache,
            saved_count=saved_count,
        )

        warning = None
        show_unavailable = not has_saved
        if has_saved and not live_ok:
            warning = "⚠️ En vivo no disponible; mostrando últimos resultados guardados."
            _log(f"LEIDSA parser OK (BD) — resultados guardados: {saved_count}")
            show_unavailable = False
        elif not has_saved:
            if fetch_log and not fetch_log.get("ok"):
                err = fetch_log.get("error") or fetch_log.get("blocking_type") or "sin conexión"
                if fetch_log.get("blocking_type") == "cloudflare":
                    err = "Cloudflare bloqueó acceso"
                warning = f"LEIDSA temporalmente no disponible. {err}"
            else:
                warning = "LEIDSA temporalmente no disponible. Sin datos guardados aún."
            show_unavailable = True

        results_found = len(board)
        if fetch_log and fetch_log.get("results_found"):
            results_found = max(results_found, fetch_log.get("results_found", 0))
        if saved_count:
            results_found = max(results_found, saved_count)

        return _safe_response(
            ok=True,
            fecha_rd=fecha,
            board=board,
            historial=historial,
            last_sync=last_sync,
            last_fetch=fetch_log,
            debug=debug,
            warning=warning,
            using_cache=using_cache,
            live_ok=live_ok,
            has_saved=has_saved,
            show_unavailable=show_unavailable,
            results_found=results_found,
            saved_count=saved_count,
        )
    except Exception as exc:
        logger.exception("get_leidsa_dashboard")
        try:
            board = get_leidsa_real_results_board()
            historial = get_leidsa_history_from_db(limit_days=30)
            if board or historial:
                return _safe_response(
                    ok=True,
                    warning="⚠️ En vivo no disponible; mostrando últimos resultados guardados.",
                    board=board,
                    historial=historial,
                    using_cache=True,
                    has_saved=True,
                    debug=_build_debug_panel(None, False, using_cache=True, saved_count=len(historial)),
                )
        except Exception:
            pass
        return _safe_response(
            ok=True,
            error=str(exc),
            warning="Sin datos guardados. Error al leer panel LEIDSA.",
            board=[],
            historial=[],
            has_saved=False,
            debug=_build_debug_panel(None, False),
        )


def get_leidsa_analysis(tipo: str, draw_name: str | None = None) -> dict[str, Any]:
    try:
        from analysis import analizar_loteria_por_tanda, generar_jugada_inteligente
        from models import get_lottery_by_slug, seed_leidsa_lotteries

        tipo = (tipo or "recomendado").lower().strip()
        seed_leidsa_lotteries()
        out = _safe_response(ok=True, tipo=tipo, games=[], tandas={})

        for slug, cfg in LEIDSA_GAMES.items():
            lot = get_lottery_by_slug(slug)
            if not lot:
                continue
            game_entry = {"slug": slug, "name": cfg["display_name"], "draws": []}
            for slot in cfg["draws"]:
                dn = slot["draw_name"]
                if draw_name and dn != draw_name:
                    continue
                stats = analizar_loteria_por_tanda(lot["id"], dn)
                item = {
                    "draw_name": dn,
                    "time": slot["time"],
                    "stats_ok": bool(stats and stats.get("ok")),
                }
                if stats and stats.get("ok"):
                    if tipo == "caliente":
                        item["data"] = stats.get("hot_numbers_detail") or stats.get("hot_numbers")
                    elif tipo == "frio":
                        item["data"] = stats.get("cold_numbers_detail") or stats.get("cold_numbers")
                    elif tipo == "atrasado":
                        item["data"] = stats.get("overdue_numbers_detail") or stats.get("overdue_numbers")
                    else:
                        item["data"] = generar_jugada_inteligente(lot["id"], dn)
                    item["total_results"] = stats.get("total_results", 0)
                else:
                    item["data"] = []
                    item["message"] = (stats or {}).get("message", "Sin datos")
                game_entry["draws"].append(item)
                out["tandas"].setdefault(dn, []).append({
                    "slug": slug,
                    "name": cfg["display_name"],
                    "time": slot["time"],
                    "item": item,
                })
            out["games"].append(game_entry)
        return out
    except Exception as exc:
        return _safe_response(ok=False, error=str(exc), games=[], tandas={})


def debug_leidsa() -> dict[str, Any]:
    """Diagnóstico completo para /debug/leidsa — JSON real."""
    try:
        fetch = fetch_leidsa_html()
        html = fetch.get("html", "") if fetch.get("ok") else ""
        api_urls = fetch.get("possible_api_urls") or (detect_hidden_endpoints(html) if html else [])
        parsed = _safe_response(ok=False, results=[], parser=None, error="sin HTML")
        if html:
            api_try = try_fetch_json_api(api_urls) if api_urls else _safe_response(ok=False, results=[])
            if api_try.get("ok"):
                parsed = api_try
            else:
                parsed = parse_leidsa_html(html)

        results = parsed.get("results") or []
        blocking = fetch.get("blocking_type") or detect_blocking(html, fetch.get("status_code"))
        err_msg = fetch.get("error") or parsed.get("error")
        if blocking == "cloudflare":
            err_msg = "Cloudflare blocked request"

        out = {
            "ok": bool(fetch.get("ok") and len(results) > 0),
            "connection_ok": bool(fetch.get("ok")),
            "source": SOURCE_NAME,
            "url": SOURCE_URL,
            "status_code": fetch.get("status_code"),
            "method": fetch.get("method"),
            "html_detected": bool(html),
            "html_length": fetch.get("html_length", len(html)),
            "parser": parsed.get("parser"),
            "results_found": len(results),
            "results_count": len(results),
            "sample_results": results[:5],
            "possible_api_urls": api_urls[:20],
            "error": err_msg,
            "blocking_type": blocking,
            "html_preview": (html or fetch.get("html_preview", ""))[:1500],
        }
        _log_fetch_result(
            {**out, "results": results, "parser": parsed.get("parser")},
            fetch,
        )
        return out
    except Exception as exc:
        return {
            "ok": False,
            "connection_ok": False,
            "error": str(exc),
            "source": SOURCE_NAME,
            "html_detected": False,
            "html_length": 0,
            "results_found": 0,
            "sample_results": [],
            "possible_api_urls": [],
            "html_preview": "",
        }
