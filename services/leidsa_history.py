"""
Historial LEIDSA — dropdown / drawResults en páginas de resultados.
Una petición por juego extrae ~100 sorteos embebidos en drawResults.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any

import requests

from services.leidsa_config import (
    BROWSER_HEADERS,
    DEBUG_DIR,
    FAMILY_NAME_ALIASES,
    FETCH_TIMEOUT,
    HISTORY_CACHE_HOURS,
    LEIDSA_GAMES,
    LEIDSA_HISTORY_GAMES,
    LEIDSA_TEST_MODE,
    SOURCE_NAME,
    SOURCE_URL,
)
from services.leidsa_service import (
    LOG_PREFIX,
    _fold_accents,
    _log,
    _now_rd,
    _rd_tz,
    _safe_response,
    normalize_lottery_slug,
    resolve_draw_name,
    save_leidsa_rows,
    utc_to_fecha_rd,
    utc_to_local_hm,
)

logger = logging.getLogger(__name__)
LOG_HISTORIAL = "[LEIDSA HISTORIAL]"


def _log_historial(
    *,
    url: str = "",
    status: str | int = "",
    juego: str = "",
    resultados: int | str = "",
    nuevos: int | str = "",
    actualizados: int | str = "",
    error: str | None = None,
) -> None:
    lines = [
        LOG_HISTORIAL,
        f"URL: {url}",
        f"status: {status}",
        f"juego: {juego}",
        f"resultados: {resultados}",
        f"nuevos: {nuevos}",
        f"actualizados: {actualizados}",
        f"error: {error or ''}",
    ]
    text = "\n".join(lines)
    if error:
        logger.error(text)
        print(text)
    else:
        logger.info(text)
        print(text)


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


def _invalidate_page_cache(url: str) -> None:
    path = _cache_path(url)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def fetch_page(url: str, use_cache: bool = True) -> dict[str, Any]:
    if not use_cache:
        _invalidate_page_cache(url)
    elif use_cache:
        cached = _read_page_cache(url)
        if cached:
            return _safe_response(ok=True, html=cached, method="cache", url=url, cached=True)

    from services.leidsa_http import fetch_leidsa_page

    out = fetch_leidsa_page(url, juego="historial", require_draw_data=True, min_bytes=5000)
    if out.get("ok"):
        _write_page_cache(url, out["html"])
        if LEIDSA_TEST_MODE:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe = re.sub(r"[^a-z0-9]+", "_", url.split("/")[-2].lower())[:30]
            with open(
                os.path.join(_cache_dir(), f"raw_{safe}_{ts}.html"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(out["html"])
        return _safe_response(
            ok=True,
            html=out["html"],
            method=out.get("method") or "cloudscraper",
            url=url,
            status_code=out.get("status_code"),
        )
    return _safe_response(
        ok=False,
        error=out.get("error") or "fetch failed",
        url=url,
        status_code=out.get("status_code"),
    )


def _is_stale_draw_id(draw_id: str, prefix: str = "") -> bool:
    """IDs tipo 3_1 son semillas viejas; los reales suelen ser >100 (p. ej. 3_6260)."""
    if not draw_id:
        return True
    if prefix and not str(draw_id).startswith(prefix):
        return True
    try:
        num = int(str(draw_id).split("_", 1)[1])
        return num < 50
    except (ValueError, IndexError):
        return True


def _draw_id_num(draw_id: str) -> int:
    try:
        return int(str(draw_id).split("_", 1)[1])
    except (ValueError, IndexError):
        return -1


def _canonical_family_name(family: str) -> str:
    """Normaliza 'Loto Más' / 'LotoMas' → family_name de config ('Loto')."""
    raw = family or ""
    folded = re.sub(r"[^a-z0-9]+", " ", _fold_accents(raw)).strip()
    nospace = folded.replace(" ", "")
    for key in (folded, nospace, folded.replace(" ", "-")):
        if key in FAMILY_NAME_ALIASES:
            return FAMILY_NAME_ALIASES[key]
    slug = normalize_lottery_slug(raw)
    if slug and slug in LEIDSA_GAMES:
        return LEIDSA_GAMES[slug]["family_name"]
    return raw.strip()


def _lookup_draw_id(game: dict, ids: dict[str, str]) -> str:
    """Busca drawId por family_name y alias del sitio."""
    family = game.get("family_name") or ""
    prefix = game.get("draw_id_prefix", "")
    slug = game.get("slug") or ""
    candidates: list[str] = []
    if family and family in ids:
        candidates.append(ids[family])
    for key, did in ids.items():
        if _canonical_family_name(key) == family:
            candidates.append(did)
        elif slug and normalize_lottery_slug(key) == slug:
            candidates.append(did)
    best = ""
    for did in candidates:
        if _is_stale_draw_id(did, prefix):
            continue
        if not best or _draw_id_num(did) > _draw_id_num(best):
            best = did
    if best:
        return best
    seed = game.get("seed_draw_id") or ""
    if seed and not _is_stale_draw_id(seed, prefix):
        return seed
    return ""


def discover_latest_draw_ids(*, retries: int = 3) -> dict[str, str]:
    """drawId más reciente por gameFamilyName desde la home."""
    from services.leidsa_http import warm_leidsa_session

    warm_leidsa_session()
    out: dict[str, str] = {}
    for attempt in range(max(1, retries)):
        fetch = fetch_page(SOURCE_URL, use_cache=False)
        if not fetch.get("ok"):
            time.sleep(1.5 * (attempt + 1))
            continue
        html = fetch.get("html", "")
        for block in html.split('{\\"gameId\\":')[1:]:
            if '\\"gameProvider\\":\\"Leidsa\\"' not in block[:800]:
                continue
            fam_m = re.search(r'\\"gameFamilyName\\":\\"([^\\"]+)', block)
            if not fam_m:
                continue
            family = fam_m.group(1).strip()
            draw_id = ""
            for pat in (
                r'\\"currentDrawDetails\\":\{[^}]*?\\"drawId\\":\\"([^\\"]+)',
                r'\\"previousDrawDetails\\":\{[^}]*?\\"drawId\\":\\"([^\\"]+)',
                r'\\"latestDrawDetails\\":\{[^}]*?\\"drawId\\":\\"([^\\"]+)',
                r'\\"drawId\\":\\"(\d+_\d+)"',
            ):
                did_m = re.search(pat, block[:2500])
                if did_m:
                    draw_id = did_m.group(1).strip()
                    break
            if family and draw_id and not _is_stale_draw_id(draw_id):
                # Guardar clave original + canónica (Loto Más → Loto)
                for key in {family, _canonical_family_name(family)}:
                    prev = out.get(key)
                    if not prev or _draw_id_num(draw_id) >= _draw_id_num(prev):
                        out[key] = draw_id
        if out:
            break
        time.sleep(1.5 * (attempt + 1))
    return out


def build_results_url(
    game: dict,
    draw_ids: dict[str, str] | None = None,
    *,
    path_override: str | None = None,
) -> str:
    path = path_override or game["path"]
    prefix = game.get("draw_id_prefix", "")
    ids = draw_ids or discover_latest_draw_ids()
    draw_id = _lookup_draw_id(game, ids)
    if not draw_id or _is_stale_draw_id(draw_id, prefix):
        fresh = discover_latest_draw_ids(retries=2)
        draw_id = _lookup_draw_id(game, fresh) or draw_id
        if fresh:
            ids.update(fresh)
    if not draw_id or _is_stale_draw_id(draw_id, prefix):
        # Último recurso: semilla baja (historial antiguo). El caller debe complementar en vivo.
        draw_id = f"{prefix}1" if prefix else "1_1"
        _log(
            f"drawId fresco no encontrado para {game.get('name') or path}; "
            f"usando semilla {draw_id}"
        )
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
    target_canon = _canonical_family_name(target)
    target_slug = slug or normalize_lottery_slug(target) or ""

    for game_draw_id, fam, draw_time, nums_raw, bonus_raw in _DRAW_ENTRY.findall(section):
        fam_s = fam.strip()
        if fam_s != target and _canonical_family_name(fam_s) != target_canon:
            if not (target_slug and normalize_lottery_slug(fam_s) == target_slug):
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


def _days_since_draw(fecha_rd: str | None) -> int | None:
    if not fecha_rd:
        return None
    try:
        draw_d = datetime.strptime(fecha_rd[:10], "%Y-%m-%d").date()
        today = _now_rd().date()
        return (today - draw_d).days
    except ValueError:
        return None


def _supplement_live_rows(slug: str, *, days: int = 90) -> dict[str, Any]:
    """Último sorteo en vivo (home / páginas) cuando el historial drawResults queda viejo."""
    from services.leidsa_service import scrape_leidsa_via_results_pages, save_leidsa_rows

    rows: list[dict] = []
    pages = scrape_leidsa_via_results_pages()
    if pages.get("ok"):
        rows = [r for r in (pages.get("results") or pages.get("rows") or []) if r.get("lottery") == slug]
    if not rows:
        try:
            from services.leidsa_fallback.orchestrator import scrape_leidsa_with_fallbacks

            fb = scrape_leidsa_with_fallbacks()
            rows = [
                r for r in (fb.get("results") or fb.get("rows") or [])
                if r.get("lottery") == slug
            ]
        except Exception as exc:
            logger.warning("%s supplement fallback %s: %s", LOG_HISTORIAL, slug, exc)
    cutoff = (_now_rd() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = [r for r in rows if (r.get("fecha_rd") or "") >= cutoff]
    if not rows:
        return {"inserted": 0, "updated": 0, "rows": []}
    batch = save_leidsa_rows(rows)
    batch["rows"] = rows
    return batch


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
    draw_ids = draw_ids or discover_latest_draw_ids()
    paths = [game["path"]] + [
        p for p in (game.get("path_aliases") or []) if p and p != game["path"]
    ]

    url = ""
    fetch: dict[str, Any] = {}
    html = ""
    rows: list[dict] = []
    options: list[dict] = []
    api_urls: list[str] = []
    parse_error = None

    for path in paths:
        url = build_results_url(game, draw_ids, path_override=path)
        _log(f"HISTORIAL {game['name']}: {url}")
        fetch = fetch_page(url, use_cache=use_cache)
        if not fetch.get("ok"):
            parse_error = fetch.get("error")
            continue
        html = fetch.get("html", "")
        options = extract_dropdown_options(html)
        api_urls = detect_ajax_endpoints(html)
        rows = parse_draw_results_history(
            html, family, days=days, limit=limit, slug=slug
        )
        if rows:
            parse_error = None
            break
        parse_error = (
            "Parser drawResults: 0 sorteos "
            f"(familia «{family}» no encontrada o HTML sin historial)"
        )

    if not fetch.get("ok") and not rows:
        return _safe_response(
            ok=False,
            error=parse_error or fetch.get("error"),
            game=game["name"],
            slug=slug,
            url=url,
            rows=[],
        )

    if not rows:
        try:
            from services.leidsa_fallback.orchestrator import scrape_leidsa_with_fallbacks

            fb = scrape_leidsa_with_fallbacks()
            fb_rows = [
                r for r in (fb.get("results") or fb.get("rows") or [])
                if r.get("lottery") == slug
            ]
            cutoff = (_now_rd() - timedelta(days=days)).strftime("%Y-%m-%d")
            for r in fb_rows:
                if (r.get("fecha_rd") or "") >= cutoff:
                    rows.append({
                        "lottery": slug,
                        "draw": r.get("draw") or "sorteo",
                        "fecha_rd": r.get("fecha_rd"),
                        "numeros": r.get("numeros") or [],
                        "bonus": r.get("bonus") or [],
                        "draw_time": r.get("draw_time", ""),
                        "fuente": r.get("fuente") or "leidsa_fallback",
                        "estado": "publicado",
                    })
            if rows:
                parse_error = None
                rows.sort(
                    key=lambda r: (r.get("fecha_rd", ""), r.get("draw_time", "")),
                    reverse=True,
                )
                if limit and len(rows) > limit:
                    rows = rows[:limit]
        except Exception as exc:
            logger.warning("%s fallback vivo %s: %s", LOG_HISTORIAL, game["name"], exc)

    if not rows and options:
        _log(f"  {game['name']}: sin drawResults, {len(options)} opciones dropdown detectadas")

    _log(f"  {game['name']}: {len(rows)} resultados ({len(options)} opciones dropdown)")

    status_code = fetch.get("status_code") or 200
    _log_historial(
        url=url,
        status=status_code if rows else (parse_error or fetch.get("error") or "sin_filas"),
        juego=game["name"],
        resultados=len(rows),
        nuevos=0,
        actualizados=0,
        error=parse_error or (fetch.get("error") if not fetch.get("ok") else None),
    )

    return _safe_response(
        ok=bool(rows),
        game=game["name"],
        slug=slug,
        url=url,
        rows=rows,
        results=rows,
        status_code=status_code,
        options_found=len(options),
        dropdown_options=options[:20],
        possible_api_urls=api_urls[:10],
        parser="drawResults",
        method=fetch.get("method"),
        error=parse_error or fetch.get("error"),
    )


def sync_leidsa_game_history(
    slug: str,
    *,
    days: int = 30,
    limit: int = 100,
    use_cache: bool = False,
    save: bool = True,
) -> dict[str, Any]:
    """Historial de un solo juego LEIDSA (rápido para API / Super Kino)."""
    game = next((g for g in LEIDSA_HISTORY_GAMES if g.get("slug") == slug), None)
    if not game:
        return _safe_response(
            ok=False,
            error=f"Juego LEIDSA desconocido: {slug}",
            slug=slug,
            inserted=0,
            updated=0,
        )
    res = fetch_leidsa_game_history(
        game,
        limit=max(limit, min(days + 20, 150)),
        days=days,
        use_cache=use_cache,
        draw_ids=discover_latest_draw_ids(),
    )
    rows = res.get("rows") or []
    inserted = updated = skipped = 0
    if save and rows:
        batch = save_leidsa_rows(rows)
        inserted = int(batch.get("inserted") or 0)
        updated = int(batch.get("updated") or 0)
        skipped = int(batch.get("skipped") or 0)
    latest = max((r.get("fecha_rd") for r in rows if r.get("fecha_rd")), default=None)
    age = _days_since_draw(latest)
    if save and (age is None or age > 2):
        _log(f"  {game['name']}: historial viejo (última={latest}) — complemento en vivo")
        sup = _supplement_live_rows(slug, days=days)
        inserted += int(sup.get("inserted") or 0)
        updated += int(sup.get("updated") or 0)
        if sup.get("rows"):
            sup_dates = [r.get("fecha_rd") for r in sup["rows"] if r.get("fecha_rd")]
            if sup_dates:
                latest = max(sup_dates + ([latest] if latest else []))
    ok = bool(rows) or bool(inserted + updated)
    return _safe_response(
        ok=ok,
        slug=slug,
        game=game["name"],
        results_found=len(rows),
        inserted=inserted,
        updated=updated,
        skipped=skipped,
        latest_date=latest,
        parser=res.get("parser"),
        url=res.get("url"),
        error=res.get("error"),
    )


def fetch_all_leidsa_history(
    days: int = 90,
    limit_per_game: int = 100,
    *,
    use_cache: bool = True,
    save: bool = True,
) -> dict[str, Any]:
    draw_ids = discover_latest_draw_ids()
    if not draw_ids:
        _log("discover_latest_draw_ids vacío — usando drawId por prefijo por juego")

    all_rows: list[dict] = []
    per_game: list[dict] = []
    inserted = updated = skipped = 0
    games_checked = 0
    errors: list[str] = []

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
        game_inserted = game_updated = 0
        game_error = res.get("error")

        if save and rows:
            try:
                batch = save_leidsa_rows(rows)
                game_inserted = int(batch.get("inserted") or 0)
                game_updated = int(batch.get("updated") or 0)
                skipped += int(batch.get("skipped") or 0)
                inserted += game_inserted
                updated += game_updated
                batch_errors = batch.get("errors") or []
                if batch_errors:
                    errors.extend(batch_errors[:3])
            except Exception as exc:
                game_error = f"Error guardando: {exc}"
                errors.append(f"{game['name']}: {exc}")
                logger.exception("%s guardado %s", LOG_HISTORIAL, game["name"])

        latest = max((r.get("fecha_rd") for r in rows if r.get("fecha_rd")), default=None)
        age = _days_since_draw(latest)
        if save and (age is None or age > 2):
            _log(f"  {game['name']}: historial viejo (última={latest}) — complemento en vivo")
            try:
                sup = _supplement_live_rows(game["slug"], days=days)
                si = int(sup.get("inserted") or 0)
                su = int(sup.get("updated") or 0)
                game_inserted += si
                game_updated += su
                inserted += si
                updated += su
                if sup.get("rows"):
                    rows = list(rows) + list(sup["rows"])
                    latest = max(
                        (r.get("fecha_rd") for r in rows if r.get("fecha_rd")),
                        default=latest,
                    )
                    game_error = None
            except Exception as exc:
                logger.warning("%s supplement %s: %s", LOG_HISTORIAL, game["name"], exc)

        _log_historial(
            url=res.get("url") or "",
            status=res.get("status_code") or ("ok" if rows else "error"),
            juego=game["name"],
            resultados=len(rows),
            nuevos=game_inserted,
            actualizados=game_updated,
            error=game_error,
        )

        per_game.append({
            "name": game["name"],
            "slug": game["slug"],
            "ok": bool(rows),
            "saved": game_inserted + game_updated > 0,
            "url": res.get("url"),
            "status_code": res.get("status_code"),
            "results_found": len(rows),
            "inserted": game_inserted,
            "updated": game_updated,
            "latest_date": latest,
            "options_found": res.get("options_found", 0),
            "error": game_error,
            "parser": res.get("parser"),
        })
        all_rows.extend(rows)

    results_found = len(all_rows)
    saved_total = inserted + updated
    failed = [g for g in per_game if not g.get("ok")]
    partial = bool(failed) and saved_total > 0

    if saved_total > 0:
        ok = True
    elif results_found > 0:
        ok = True
    else:
        ok = False

    if not ok and errors:
        err_summary = "; ".join(errors[:5])
    elif failed:
        err_summary = "; ".join(
            f"{g['name']}: {g.get('error') or 'sin filas'}" for g in failed[:6]
        )
    else:
        err_summary = None

    return _safe_response(
        ok=ok,
        partial=partial,
        games_checked=games_checked,
        results_found=results_found,
        inserted=inserted,
        updated=updated,
        skipped=skipped,
        games=per_game,
        games_failed=len(failed),
        days=days,
        error=err_summary if not ok else (err_summary if partial else None),
        errors=errors[:15],
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

        out = fetch_all_leidsa_history(
            days=int(days or 90),
            limit_per_game=max(100, min(int(days or 90) + 15, 120)),
            save=True,
            use_cache=False,
        )
        saved = int(out.get("inserted") or 0) + int(out.get("updated") or 0)
        found = int(out.get("results_found") or 0)

        if saved > 0:
            out["ok"] = True
        elif found > 0:
            out["ok"] = True
            out["warning"] = True
            out["message"] = (
                f"Historial LEIDSA: {found} sorteos encontrados pero ninguno nuevo guardado."
            )
        else:
            out["ok"] = False
            failed = out.get("games") or []
            details = [
                f"{g.get('name')}: {g.get('error') or 'sin filas'}"
                for g in failed
                if not g.get("ok")
            ]
            out["error"] = out.get("error") or (
                "; ".join(details[:6]) if details else "Ningún juego devolvió historial parseable"
            )
            out["detalle"] = out["error"]
            out["message"] = (
                f"No se pudo actualizar historial LEIDSA. {out['error']}"
            )

        if out.get("ok") and saved > 0:
            msg = (
                f"Historial LEIDSA: {found} sorteos, "
                f"{out.get('inserted', 0)} nuevos, {out.get('updated', 0)} actualizados."
            )
            if out.get("partial"):
                msg += f" Advertencia: {out.get('games_failed', 0)} juego(s) sin datos."
            out["message"] = msg

        log_leidsa_sync(
            ok=bool(out.get("ok")),
            message=out.get("message", ""),
            imported=out.get("inserted", 0),
            updated=out.get("updated", 0),
            error=out.get("error"),
        )
        out["status"] = (
            "updated" if saved else ("partial" if out.get("partial") else "no_new" if out.get("ok") else "error")
        )
        out["fuente"] = "leidsa.com"
        return out
    except Exception as exc:
        logger.exception("%s update_leidsa_history", LOG_HISTORIAL)
        _log(f"update_leidsa_history error: {exc}")
        return _safe_response(
            ok=False,
            error=str(exc),
            detalle=str(exc),
            message=f"Error interno actualizando historial LEIDSA: {exc}",
            games_checked=0,
            results_found=0,
            inserted=0,
            updated=0,
            skipped=0,
            fuente="leidsa.com",
            status="error",
        )
