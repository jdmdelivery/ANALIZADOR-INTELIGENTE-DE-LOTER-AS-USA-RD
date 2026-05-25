"""
Historial LEIDSA — dropdown / drawResults en páginas de resultados.
Una petición por juego extrae ~100 sorteos embebidos en drawResults.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any

import requests

from services.leidsa_config import (
    BROWSER_HEADERS,
    DEBUG_DIR,
    FETCH_TIMEOUT,
    HISTORY_CACHE_HOURS,
    LEIDSA_HISTORY_GAMES,
    LEIDSA_TEST_MODE,
    SOURCE_NAME,
    SOURCE_URL,
)
from services.leidsa_service import (
    LOG_PREFIX,
    _log,
    _now_rd,
    _rd_tz,
    _safe_response,
    resolve_draw_name,
    save_leidsa_rows,
    utc_to_fecha_rd,
    utc_to_local_hm,
)

_DRAW_ENTRY = re.compile(
    r'\\"gameDrawId\\":\\"([^\\"]+)\\",\\"gameFamilyName\\":\\"([^\\"]+)\\"'
    r'.*?\\"drawTime\\":\\"([^\\"]+)\\"'
    r'.*?\\"drawnValues\\":\[.*?\\"drawnValues\\":\[([^\]]*)\]'
    r'(?:.*?\\"bonusDraws\\":\[([^\]]*)\])?',
    re.DOTALL,
)
_OPTION_SELECT = re.compile(
    r"<select[^>]*>(.*?)</select>",
    re.DOTALL | re.IGNORECASE,
)
_OPTION_TAG = re.compile(
    r'<option[^>]*value=["\']([^"\']*)["\'][^>]*>(.*?)</option>',
    re.DOTALL | re.IGNORECASE,
)
_SORTEO_LABEL = re.compile(
    r"Sorteo:\s*(\d{1,2}/\d{1,2}/\d{2,4}),\s*(\d{1,2}:\d{2}\s*[AP]M)",
    re.I,
)

_session: Any = None
_page_cache: dict[str, dict] = {}


def _cache_dir() -> str:
    base = os.path.join(os.path.dirname(os.path.dirname(__file__)), DEBUG_DIR, "cache")
    os.makedirs(base, exist_ok=True)
    return base


def _cache_path(url: str) -> str:
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    return os.path.join(_cache_dir(), f"page_{key}.json")


def _read_page_cache(url: str) -> str | None:
    path = _cache_path(url)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("ts", 0) > HISTORY_CACHE_HOURS * 3600:
            return None
        return data.get("html")
    except (OSError, json.JSONDecodeError):
        return None


def _write_page_cache(url: str, html: str) -> None:
    try:
        with open(_cache_path(url), "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "url": url, "html": html}, f)
    except OSError:
        pass


def get_http_session():
    global _session
    if _session is not None:
        return _session
    try:
        import cloudscraper  # noqa: WPS433
        _session = cloudscraper.create_scraper()
    except ImportError:
        _session = requests.Session()
    return _session


def fetch_page(url: str, use_cache: bool = True) -> dict[str, Any]:
    if use_cache:
        cached = _read_page_cache(url)
        if cached:
            return _safe_response(ok=True, html=cached, method="cache", url=url, cached=True)

    client = get_http_session()
    last_err = None
    for attempt in range(3):
        try:
            resp = client.get(url, headers=BROWSER_HEADERS, timeout=FETCH_TIMEOUT)
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}"
                continue
            html = resp.text or ""
            if len(html) < 5000:
                last_err = "HTML demasiado corto"
                continue
            _write_page_cache(url, html)
            if LEIDSA_TEST_MODE:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe = re.sub(r"[^a-z0-9]+", "_", url.split("/")[-2].lower())[:30]
                with open(
                    os.path.join(_cache_dir(), f"raw_{safe}_{ts}.html"),
                    "w",
                    encoding="utf-8",
                ) as f:
                    f.write(html)
            return _safe_response(
                ok=True,
                html=html,
                method="cloudscraper" if "cloudscraper" in type(client).__module__ else "requests",
                url=url,
                status_code=200,
            )
        except Exception as exc:
            last_err = str(exc)
    return _safe_response(ok=False, error=last_err or "fetch failed", url=url)


def discover_latest_draw_ids() -> dict[str, str]:
    """drawId más reciente por gameFamilyName desde la home."""
    fetch = fetch_page(SOURCE_URL, use_cache=False)
    if not fetch.get("ok"):
        return {}
    html = fetch.get("html", "")
    out: dict[str, str] = {}
    for block in html.split('{\\"gameId\\":')[1:]:
        if '\\"gameProvider\\":\\"Leidsa\\"' not in block[:800]:
            continue
        fam_m = re.search(r'\\"gameFamilyName\\":\\"([^\\"]+)', block)
        did_m = re.search(
            r'\\"previousDrawDetails\\":\{[^}]*?\\"drawId\\":\\"([^\\"]+)',
            block,
        )
        if fam_m and did_m:
            out[fam_m.group(1).strip()] = did_m.group(1).strip()
    return out


def build_results_url(game: dict, draw_ids: dict[str, str] | None = None) -> str:
    path = game["path"]
    family = game["family_name"]
    ids = draw_ids or discover_latest_draw_ids()
    draw_id = ids.get(family) or game.get("seed_draw_id", "")
    if not draw_id:
        prefix = game.get("draw_id_prefix", "")
        draw_id = f"{prefix}1" if prefix else "1_1"
    from urllib.parse import quote
    segment = quote(path, safe="")
    return f"https://www.leidsa.com/results/Leidsa/{segment}/{draw_id}"


def extract_dropdown_options(html: str) -> list[dict]:
    """Opciones <select> si existen en HTML estático."""
    options: list[dict] = []
    for sel_html in _OPTION_SELECT.findall(html):
        if "sorteo" not in sel_html.lower() and "draw" not in sel_html.lower():
            continue
        for value, text in _OPTION_TAG.findall(sel_html):
            text_clean = re.sub(r"<[^>]+>", "", text).strip()
            label = text_clean or value
            fecha, hora = "", ""
            m = _SORTEO_LABEL.search(label)
            if m:
                fecha, hora = m.group(1), m.group(2)
            options.append({
                "value": value.strip(),
                "text": label,
                "fecha": fecha,
                "hora": hora,
                "draw_id": value.strip() if value.strip() else None,
            })
    if not options:
        for m in _SORTEO_LABEL.finditer(html):
            options.append({
                "value": "",
                "text": m.group(0),
                "fecha": m.group(1),
                "hora": m.group(2),
                "draw_id": None,
            })
    return options


def detect_ajax_endpoints(html: str) -> list[str]:
    found: set[str] = set()
    patterns = [
        r'fetch\s*\(\s*["\']([^"\']+)["\']',
        r'axios\.[a-z]+\s*\(\s*["\']([^"\']+)["\']',
        r'"(/api/[^"\']+)"',
        r'onchange=["\'][^"\']*["\'][^>]*data-url=["\']([^"\']+)["\']',
    ]
    for pat in patterns:
        for m in re.finditer(pat, html, re.I):
            u = m.group(1)
            if u.startswith("/"):
                u = "https://www.leidsa.com" + u
            if "leidsa" in u.lower() or "/api/" in u.lower():
                found.add(u.split("\\")[0][:250])
    return sorted(found)


def _parse_bonus_numbers(bonus_raw: str | None) -> list[list[int]]:
    if not bonus_raw:
        return []
    out = []
    for m in re.finditer(r'\{\\"drawnValues\\":\[([^\]]*)\]', bonus_raw):
        nums = [int(x) for x in re.findall(r"\d+", m.group(1))]
        if nums:
            out.append(nums)
    return out


def parse_draw_results_history(
    html: str,
    family_name: str,
    *,
    days: int = 90,
    limit: int = 100,
    slug: str = "",
) -> list[dict]:
    """Extrae historial desde array drawResults embebido (RSC)."""
    if not html:
        return []

    cutoff = (_now_rd() - timedelta(days=days)).strftime("%Y-%m-%d")
    idx = html.find('drawResults\\":[{')
    if idx < 0:
        idx = html.find('drawResults\\": [{')
    if idx < 0:
        idx = html.find("drawResults\":[")
    section = html[idx : idx + 900000] if idx >= 0 else html

    rows: list[dict] = []
    target = family_name.strip()

    for game_draw_id, fam, draw_time, nums_raw, bonus_raw in _DRAW_ENTRY.findall(section):
        if fam.strip() != target:
            continue
        main_nums = [int(x) for x in re.findall(r"\d+", nums_raw or "")]
        if not main_nums:
            continue
        fecha_rd = utc_to_fecha_rd(draw_time)
        if fecha_rd < cutoff:
            continue
        h, m = utc_to_local_hm(draw_time)
        draw_name = resolve_draw_name(slug, draw_time) if slug else "sorteo"
        rows.append({
            "lottery": slug,
            "draw": draw_name,
            "fecha_rd": fecha_rd,
            "numeros": main_nums,
            "bonus": [],
            "draw_time": f"{h:02d}:{m:02d}",
            "fuente": SOURCE_NAME,
            "estado": "publicado",
            "draw_id": game_draw_id,
            "draw_timestamp": draw_time,
            "game_draw_id": game_draw_id,
        })

        bonuses = _parse_bonus_numbers(bonus_raw)
        if slug == "leidsa_loto_mas" and len(bonuses) >= 1:
            rows[-1]["bonus"] = bonuses[0]
        if slug == "leidsa_loto_mas" and len(bonuses) >= 2:
            pass

    rows.sort(key=lambda r: (r.get("fecha_rd", ""), r.get("draw_timestamp", "")), reverse=True)
    if limit and len(rows) > limit:
        rows = rows[:limit]
    return rows


def fetch_leidsa_game_history(
    game: dict,
    *,
    limit: int = 100,
    days: int = 90,
    draw_ids: dict[str, str] | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    slug = game["slug"]
    family = game["family_name"]
    url = build_results_url(game, draw_ids)

    _log(f"HISTORIAL {game['name']}: {url}")
    fetch = fetch_page(url, use_cache=use_cache)
    if not fetch.get("ok"):
        return _safe_response(
            ok=False,
            error=fetch.get("error"),
            game=game["name"],
            slug=slug,
            url=url,
            rows=[],
        )

    html = fetch.get("html", "")
    options = extract_dropdown_options(html)
    api_urls = detect_ajax_endpoints(html)

    rows = parse_draw_results_history(
        html, family, days=days, limit=limit, slug=slug
    )

    if not rows and options:
        _log(f"  {game['name']}: sin drawResults, {len(options)} opciones dropdown detectadas")

    _log(f"  {game['name']}: {len(rows)} resultados ({len(options)} opciones dropdown)")

    return _safe_response(
        ok=bool(rows),
        game=game["name"],
        slug=slug,
        url=url,
        rows=rows,
        results=rows,
        options_found=len(options),
        dropdown_options=options[:20],
        possible_api_urls=api_urls[:10],
        parser="drawResults",
        method=fetch.get("method"),
    )


def fetch_all_leidsa_history(
    days: int = 90,
    limit_per_game: int = 100,
    *,
    use_cache: bool = True,
    save: bool = True,
) -> dict[str, Any]:
    draw_ids = discover_latest_draw_ids()
    all_rows: list[dict] = []
    per_game: list[dict] = []
    inserted = updated = skipped = 0
    games_checked = 0

    for game in LEIDSA_HISTORY_GAMES:
        games_checked += 1
        res = fetch_leidsa_game_history(
            game,
            limit=limit_per_game,
            days=days,
            draw_ids=draw_ids,
            use_cache=use_cache,
        )
        rows = res.get("rows") or []
        per_game.append({
            "name": game["name"],
            "slug": game["slug"],
            "ok": res.get("ok"),
            "url": res.get("url"),
            "results_found": len(rows),
            "options_found": res.get("options_found", 0),
            "error": res.get("error"),
        })
        all_rows.extend(rows)

    if save and all_rows:
        batch = save_leidsa_rows(all_rows)
        inserted = batch.get("inserted", 0)
        updated = batch.get("updated", 0)
        skipped = batch.get("skipped", 0)

    return _safe_response(
        ok=bool(all_rows),
        games_checked=games_checked,
        results_found=len(all_rows),
        inserted=inserted,
        updated=updated,
        skipped=skipped,
        games=per_game,
        days=days,
    )


def debug_leidsa_dropdowns() -> dict[str, Any]:
    draw_ids = discover_latest_draw_ids()
    games_out = []
    for game in LEIDSA_HISTORY_GAMES:
        url = build_results_url(game, draw_ids)
        fetch = fetch_page(url, use_cache=True)
        html = fetch.get("html", "") if fetch.get("ok") else ""
        options = extract_dropdown_options(html) if html else []
        if not options and html:
            fam = game["family_name"]
            n = len(parse_draw_results_history(html, fam, days=365, limit=500, slug=game["slug"]))
            options_count = n
        else:
            options_count = len(options)
        games_out.append({
            "name": game["name"],
            "slug": game["slug"],
            "url": url,
            "dropdown_found": bool(options) or options_count > 1,
            "options_found": options_count,
            "html_ok": fetch.get("ok"),
            "error": fetch.get("error"),
        })
    return {"ok": True, "games": games_out, "draw_ids": draw_ids}


def debug_leidsa_history_sample(days: int = 90) -> dict[str, Any]:
    result = fetch_all_leidsa_history(days=days, save=False, use_cache=True)
    rows = []
    for g in LEIDSA_HISTORY_GAMES:
        res = fetch_leidsa_game_history(g, days=days, limit=5, use_cache=True)
        rows.extend((res.get("rows") or [])[:2])

    fechas = sorted({r.get("fecha_rd") for r in rows if r.get("fecha_rd")}, reverse=True)
    sorteos = len(rows)
    return {
        "ok": result.get("ok"),
        "total_results": result.get("results_found", 0),
        "games_checked": result.get("games_checked", 0),
        "fechas_encontradas": fechas[:30],
        "fechas_count": len(fechas),
        "sorteos_encontrados": sorteos,
        "sample_results": rows[:10],
        "games": result.get("games"),
        "days": days,
    }


def update_leidsa_history(days: int = 90) -> dict[str, Any]:
    """Endpoint principal: descarga y guarda historial completo."""
    try:
        from models import log_leidsa_sync

        out = fetch_all_leidsa_history(days=days, save=True)
        msg = (
            f"Historial LEIDSA: {out.get('results_found', 0)} sorteos, "
            f"{out.get('inserted', 0)} nuevos, {out.get('updated', 0)} actualizados."
        )
        log_leidsa_sync(
            ok=bool(out.get("ok")),
            message=msg,
            imported=out.get("inserted", 0),
            updated=out.get("updated", 0),
        )
        out["message"] = msg
        out["status"] = "updated" if out.get("inserted") or out.get("updated") else "no_new"
        return out
    except Exception as exc:
        _log(f"update_leidsa_history error: {exc}")
        return _safe_response(
            ok=False,
            error=str(exc),
            games_checked=0,
            results_found=0,
            inserted=0,
            updated=0,
            skipped=0,
        )
