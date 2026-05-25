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
LOG_PREFIX = "[LEIDSA]"


def _log(msg: str) -> None:
    line = f"{LOG_PREFIX} {msg}"
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
        return ZoneInfo(TZ_RD)
    return None


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


def _build_fetch_clients() -> list[tuple[str, Any]]:
    clients: list[tuple[str, Any]] = []
    try:
        import cloudscraper  # noqa: WPS433
        for _ in range(FETCH_RETRIES):
            clients.append(("cloudscraper", cloudscraper.create_scraper()))
    except ImportError:
        _log("cloudscraper no instalado")
    for _ in range(FETCH_RETRIES):
        clients.append(("requests", requests.Session()))
    return clients


def fetch_leidsa_html() -> dict[str, Any]:
    """Hasta 3 reintentos: cloudscraper y requests."""
    _log(f"URL: {SOURCE_URL}")
    clients = _build_fetch_clients()
    last_error = None
    last_status = None
    last_html = ""

    for attempt, (method_name, client) in enumerate(clients, start=1):
        try:
            _log(f"Intento {attempt}/{len(clients)} — Método: {method_name}")
            resp = client.get(SOURCE_URL, headers=BROWSER_HEADERS, timeout=FETCH_TIMEOUT)
            last_status = resp.status_code
            html = resp.text or ""
            last_html = html
            _log(f"STATUS: {resp.status_code}")
            _log(f"HTML LENGTH: {len(html)}")
            _log(f"HTML PREVIEW: {html[:500].replace(chr(10), ' ')}")

            has_embedded = "drawnValues" in html or '\\"drawnValues\\"' in html
            blocking = detect_blocking(html, resp.status_code)
            if blocking and not has_embedded:
                last_error = f"{blocking} blocked request"
                _log(f"BLOQUEO DETECTADO: {blocking}")
                continue
            if blocking and has_embedded:
                _log(f"Advertencia {blocking} pero hay datos embebidos — parseando")
            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code}"
                continue
            if len(html) < 1000:
                last_error = "HTML demasiado corto"
                continue

            api_urls = detect_hidden_endpoints(html)
            _save_debug_raw(html, {"api_urls": api_urls}, "html")
            return _safe_response(
                ok=True,
                html=html,
                method=method_name,
                status_code=resp.status_code,
                html_length=len(html),
                html_detected=True,
                possible_api_urls=api_urls,
                blocking_type=None,
            )
        except Exception as exc:
            last_error = f"{method_name}: {exc}"
            _log(f"ERROR: {last_error}")
            logger.exception("LEIDSA fetch %s", method_name)

    blocking = detect_blocking(last_html, last_status)
    return _safe_response(
        ok=False,
        error=last_error or "No se pudo conectar con leidsa.com",
        status_code=last_status,
        html_length=len(last_html),
        html_detected=bool(last_html),
        html_preview=last_html[:1500],
        blocking_type=blocking,
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


def _parse_escaped_json_blocks(html: str) -> list[dict]:
    rows = []
    blocks = html.split('{\\"gameId\\":')
    for block in blocks[1:]:
        if '\\"gameProvider\\":\\"Leidsa\\"' not in block[:1200]:
            continue
        name_m = re.search(r'\\"gameFamilyName\\":\\"([^\\"]+)', block)
        slug_m = re.search(r'\\"slug\\":\\"([^\\"]+)', block)
        prev_m = re.search(
            r'\\"previousDrawDetails\\":\{'
            r'\\"drawId\\":\\"([^\\"]*)\\",'
            r'\\"drawnValues\\":\[([^\]]*)\]',
            block,
        )
        ts_m = re.search(r'\\"drawTimestamp\\":\\"([^\\"]+)', block)
        bonus_m = re.search(r'\\"bonusRoundsValues\\":\[([^\]]*)\]', block)
        if not name_m or not prev_m or not ts_m:
            continue
        row = _row_from_game_block(
            name_m.group(1),
            slug_m.group(1) if slug_m else "",
            prev_m.group(1),
            prev_m.group(2),
            bonus_m.group(1) if bonus_m else None,
            ts_m.group(1),
        )
        if row:
            rows.append(row)
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
        blob = json.dumps(data)
        for prev_m in re.finditer(
            r'"gameFamilyName"\s*:\s*"([^"]+)".{0,200}?"gameProvider"\s*:\s*"Leidsa".{0,1500}?'
            r'"drawnValues"\s*:\s*\[([^\]]*)\].{0,400}?"drawTimestamp"\s*:\s*"([^"]+)"',
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
        prev = obj.get("previousDrawDetails") or obj.get("previous_draw_details")
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
    """Parse seguro — BeautifulSoup + JSON embebido."""
    if not html:
        return _safe_response(ok=False, error="HTML vacío", parser="none")

    parsers = [
        ("escaped_json", _parse_escaped_json_blocks),
        ("unescaped_json", _parse_unescaped_json_blocks),
        ("next_data", _parse_next_data),
        ("BeautifulSoup", _parse_script_json_blobs),
    ]
    all_rows: list[dict] = []
    used = []
    for name, fn in parsers:
        try:
            chunk = fn(html)
            if chunk:
                used.append(name)
                all_rows.extend(chunk)
        except Exception as exc:
            _log(f"Parser {name} error: {exc}")

    rows = _dedupe_rows(all_rows)
    _log(f"RESULTS FOUND: {len(rows)} (parsers: {', '.join(used) or 'ninguno'})")

    if not rows:
        return _safe_response(
            ok=False,
            error="No se detectaron resultados válidos en leidsa.com",
            parser=",".join(used) or "none",
        )

    parser_label = "BeautifulSoup" if "BeautifulSoup" in used else ",".join(used)
    return _safe_response(ok=True, results=rows, parser=parser_label or "embedded_json")


def scrape_leidsa_results() -> dict[str, Any]:
    fetch = fetch_leidsa_html()
    if not fetch.get("ok"):
        return _safe_response(
            ok=False,
            error=fetch.get("error") or "Leidsa no respondió, intenta de nuevo",
            message="Leidsa no respondió, intenta de nuevo",
            rows=[],
            status_code=fetch.get("status_code"),
            blocking_type=fetch.get("blocking_type"),
            html_preview=fetch.get("html_preview", ""),
        )

    html = fetch.get("html", "")
    api_urls = fetch.get("possible_api_urls") or detect_hidden_endpoints(html)

    if api_urls:
        api_try = try_fetch_json_api(api_urls)
        if api_try.get("ok") and api_try.get("results"):
            return _safe_response(
                ok=True,
                rows=api_try["results"],
                results=api_try["results"],
                error=None,
                message="OK",
                parser=api_try.get("parser", "json_api"),
                method=fetch.get("method"),
                status_code=fetch.get("status_code"),
                html_length=fetch.get("html_length"),
                html_detected=True,
            )

    parsed = parse_leidsa_html(html)
    if not parsed.get("ok"):
        js_urls = [u for u in api_urls if u.endswith(".js")]
        if js_urls:
            js_parsed = fetch_js_and_extract_json(js_urls)
            if js_parsed.get("ok"):
                parsed = js_parsed

    if not parsed.get("ok"):
        return _safe_response(
            ok=False,
            error=parsed.get("error"),
            message="LEIDSA no respondió o cambió su formato.",
            rows=[],
            parser=parsed.get("parser"),
            status_code=fetch.get("status_code"),
            html_preview=html[:1500],
        )
    return _safe_response(
        ok=True,
        rows=parsed["results"],
        results=parsed["results"],
        error=None,
        message="OK",
        parser=parsed.get("parser"),
        method=fetch.get("method"),
        status_code=fetch.get("status_code"),
        html_length=fetch.get("html_length"),
        html_detected=True,
    )


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


def update_leidsa_now() -> dict[str, Any]:
    """Actualización manual — nunca lanza excepción."""
    try:
        from models import log_leidsa_sync

        scrape = scrape_leidsa_results()
        _log_fetch_result(scrape)

        if not scrape.get("ok"):
            msg = scrape.get("message") or "Leidsa no respondió, intenta de nuevo"
            if scrape.get("blocking_type") == "cloudflare":
                msg = "Cloudflare bloqueó acceso a leidsa.com"
            log_leidsa_sync(ok=False, message=msg, error=scrape.get("error"))
            return _safe_response(
                ok=False,
                status="error",
                message=msg,
                inserted=0,
                updated=0,
                skipped=0,
                error=scrape.get("error"),
                status_code=scrape.get("status_code"),
                parser=scrape.get("parser"),
                blocking_type=scrape.get("blocking_type"),
            )

        save = save_leidsa_rows(scrape.get("results") or scrape.get("rows") or [])
        msg = (
            f"LEIDSA: {save.get('inserted', 0)} nuevos, "
            f"{save.get('updated', 0)} actualizados."
        )
        log_leidsa_sync(
            ok=True,
            message=msg,
            imported=save.get("inserted", 0),
            updated=save.get("updated", 0),
        )
        return _safe_response(
            ok=True,
            status="updated" if save.get("inserted", 0) + save.get("updated", 0) else "no_new",
            message=msg,
            inserted=save.get("inserted", 0),
            updated=save.get("updated", 0),
            skipped=save.get("skipped", 0),
            games=len(scrape.get("results") or []),
            parser=scrape.get("parser"),
            results_found=len(scrape.get("results") or []),
            error=None,
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


def _build_debug_panel(fetch_log: dict | None, live_ok: bool) -> dict:
    fl = fetch_log or {}
    status = fl.get("status_code")
    if live_ok and status == 200:
        status_label = f"🟢 STATUS {status}"
    elif status:
        status_label = f"🔴 STATUS {status}"
    else:
        status_label = "🔴 STATUS ERROR"
    return {
        "status_label": status_label,
        "status_code": status,
        "parser": fl.get("parser") or "—",
        "method": fl.get("method") or "—",
        "results_found": fl.get("results_found", 0),
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
        debug = _build_debug_panel(fetch_log, live_ok=bool(fetch_log and fetch_log.get("ok")))

        live_ok = bool(fetch_log and fetch_log.get("ok") and (fetch_log.get("results_found") or 0) > 0)
        using_cache = not live_ok and len(board) > 0
        warning = None

        if fetch_log and not fetch_log.get("ok"):
            err = fetch_log.get("error") or fetch_log.get("blocking_type") or "Error desconocido"
            if fetch_log.get("blocking_type") == "cloudflare":
                err = "Cloudflare bloqueó acceso"
            warning = f"⚠️ LEIDSA temporalmente no disponible. {err}"
        elif not board and not historial:
            warning = "⚠️ LEIDSA temporalmente no disponible. Sin datos guardados aún."
        elif using_cache:
            warning = "⚠️ Usando últimos resultados guardados (cache)."

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
            results_found=fetch_log.get("results_found", 0) if fetch_log else len(board),
        )
    except Exception as exc:
        logger.exception("get_leidsa_dashboard")
        return _safe_response(
            ok=False,
            error=str(exc),
            warning="⚠️ LEIDSA temporalmente no disponible",
            board=[],
            historial=[],
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
