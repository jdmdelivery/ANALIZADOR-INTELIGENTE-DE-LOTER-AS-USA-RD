"""
Parser resultados RD — plataforma Kiskoo/Nuxt (Conectate + LoteriasDominicanas).
Reemplaza el HTML legacy game-block/game-scores.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta

import requests

from services.rd_update_log import log_rd_update

logger = logging.getLogger(__name__)
LOG = "[RD SCRAPER]"
KISKOO_PARSER_VERSION = "nuxt-sessions-v2"
_HUB_ROWS_CACHE: dict[tuple, tuple[float, dict]] = {}
HUB_CACHE_TTL_SEC = 600
JSON_TIMEOUT_SEC = 20
SESSIONS_TIMEOUT_SEC = 18


def clear_hub_cache() -> None:
    _HUB_ROWS_CACHE.clear()

CONECTATE_API = "https://api.conectate.com.do"
LD_API = "https://api.loteriasdominicanas.com"
CONECTATE_PAYLOAD = "https://www.conectate.com.do/loterias/_payload.json"
LD_PAYLOAD = "https://loteriasdominicanas.com/_payload.json"

RD_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-DO,es;q=0.9,en;q=0.8",
    # Sin 'br' — requests no decodifica Brotli sin brotlicffi → HTML corrupto.
    "Accept-Encoding": "gzip, deflate",
}

# Título de juego/página Kiskoo → (lotería BD, tanda)
KISKOO_TITLE_MAP: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"anguila.*10|10:00\s*am|10\s*am", re.I), "Anguila", "mañana"),
    (re.compile(r"anguila.*1:00|1:00\s*pm|12\s*pm|medio\s*d[ií]a", re.I), "Anguila", "tarde"),
    (re.compile(r"anguila.*6|6:00\s*pm|6\s*pm|tarde.*6", re.I), "Anguila", "tardía"),
    (re.compile(r"anguila.*9|9:00\s*pm|9\s*pm", re.I), "Anguila", "noche"),
    (re.compile(r"^anguila\b", re.I), "Anguila", "mañana"),
    (re.compile(r"gana\s*m[aá]s", re.I), "Gana Más", "tarde"),
    (re.compile(r"nacional.*noche|noche.*nacional", re.I), "Lotería Nacional", "noche"),
    (re.compile(r"nacional.*tard[ií]a|juega.*pega", re.I), "Lotería Nacional", "tardía"),
    (re.compile(r"nacional", re.I), "Lotería Nacional", "tarde"),
    (re.compile(r"quiniela\s*real|real.*quiniela|loto\s*real", re.I), "Lotería Real", "tarde"),
    (re.compile(r"quiniela\s*loteka|loteka.*quiniela", re.I), "Loteka", "noche"),
    (re.compile(r"^loteka\b", re.I), "Loteka", "tarde"),
    (re.compile(r"lotedom", re.I), "Lotedom", "tarde"),
    (re.compile(r"la\s*primera.*noche|primera.*noche", re.I), "La Primera", "noche"),
    (re.compile(r"la\s*primera", re.I), "La Primera", "mañana"),
    (re.compile(r"la\s*suerte.*6|suerte.*6\s*pm", re.I), "Suerte Dominicana", "noche"),
    (re.compile(r"la\s*suerte|suerte\s*dom", re.I), "Suerte Dominicana", "tarde"),
    (re.compile(r"king\s*lottery.*noche|king.*7:30", re.I), "King Lottery", "noche"),
    (re.compile(r"king\s*lottery", re.I), "King Lottery", "tarde"),
    (re.compile(r"florida.*noche", re.I), "Florida", "noche"),
    (re.compile(r"florida", re.I), "Florida", "tarde"),
    (re.compile(r"new\s*york.*noche|nueva\s*york.*noche", re.I), "New York", "noche"),
    (re.compile(r"new\s*york|nueva\s*york", re.I), "New York", "tarde"),
    (re.compile(r"quiniela\s*leidsa|leidsa.*quiniela", re.I), "Leidsa", "noche"),
    (re.compile(r"leidsa", re.I), "Leidsa", "noche"),
]


def _pad(n: str) -> str:
    return str(int(str(n).lstrip("0") or "0")).zfill(2)


def valid_quiniela(nums: list[str]) -> bool:
    if len(nums) != 3:
        return False
    for raw in nums:
        try:
            v = int(str(raw).lstrip("0") or "0")
        except (TypeError, ValueError):
            return False
        if v < 0 or v > 99:
            return False
    return True


def map_kiskoo_title(title: str) -> tuple[str, str] | None:
    t = (title or "").strip()
    if not t:
        return None
    for pat, lottery, draw in KISKOO_TITLE_MAP:
        if pat.search(t):
            return lottery, draw
    return None


def parse_iso_date(val) -> str | None:
    if not val:
        return None
    s = str(val)
    m = re.match(r"(20\d{2}-\d{2}-\d{2})", s)
    return m.group(1) if m else None


def extract_devalue_pool(html: str) -> list | None:
    if not html:
        return None
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    if not scripts:
        return None
    big = max(scripts, key=len)
    if not big.startswith("[{"):
        return None
    try:
        return json.loads(big)
    except json.JSONDecodeError:
        return None


def resolve_devalue(pool: list, idx, seen: set | None = None):
    if seen is None:
        seen = set()
    if isinstance(idx, dict):
        return {k: resolve_devalue(pool, v, seen.copy()) for k, v in idx.items()}
    if isinstance(idx, list):
        return [resolve_devalue(pool, x, seen.copy()) for x in idx]
    if idx in seen:
        return None
    if not isinstance(idx, int) or idx < 0 or idx >= len(pool):
        return idx
    seen.add(idx)
    val = pool[idx]
    if isinstance(val, (str, bool)) or val is None:
        return val
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return val
    if isinstance(val, list):
        return [resolve_devalue(pool, x, seen.copy()) for x in val]
    if isinstance(val, dict):
        return {k: resolve_devalue(pool, v, seen.copy()) for k, v in val.items()}
    return val


def _flatten_score_numbers(score) -> list[str]:
    nums: list[str] = []

    def walk(x):
        if isinstance(x, list):
            for item in x:
                walk(item)
        elif isinstance(x, str) and re.match(r"^\d{1,2}$", x.strip()):
            nums.append(_pad(x.strip()))
        elif isinstance(x, int) and 0 <= x <= 99:
            nums.append(str(x).zfill(2))

    walk(score)
    return nums


def _game_is_quiniela(pool: list, game_idx) -> bool:
    if not isinstance(game_idx, int):
        return True
    obj = resolve_devalue(pool, game_idx)
    if not isinstance(obj, dict):
        return True
    if obj.get("is_quiniela") is True:
        return True
    stats = obj.get("statistics") or {}
    pos = stats.get("positions")
    if isinstance(pos, int):
        return pos == 3
    return True


def parse_quiniela_scores_from_pool(
    pool: list,
    *,
    cutoff: str | None = None,
    require_quiniela: bool = True,
) -> list[dict]:
    """Extrae sorteos quiniela (3 números) del pool Nuxt dehydratado."""
    rows: list[dict] = []
    seen: set[tuple] = set()

    for i, item in enumerate(pool):
        if not isinstance(item, dict) or "score" not in item or "date" not in item:
            continue
        if require_quiniela and not _game_is_quiniela(pool, item.get("game_id")):
            continue
        obj = resolve_devalue(pool, i)
        if not isinstance(obj, dict):
            continue
        nums = _flatten_score_numbers(obj.get("score"))
        if len(nums) < 3:
            continue
        nums = nums[:3]
        if not valid_quiniela(nums):
            continue
        draw_date = parse_iso_date(obj.get("date"))
        if not draw_date:
            continue
        if cutoff and draw_date < cutoff:
            continue
        game_id = obj.get("game_id")
        if isinstance(game_id, int) and 0 <= game_id < len(pool):
            gid_resolved = resolve_devalue(pool, game_id)
            game_id = gid_resolved if isinstance(gid_resolved, str) else game_id
        key = (draw_date, tuple(nums), str(game_id or ""))
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "draw_date": draw_date,
            "numbers": nums,
            "game_id": game_id,
        })
    return rows


def parse_page_quiniela_rows(html: str, source_url: str, *, days: int = 90) -> list[dict]:
    pool = extract_devalue_pool(html)
    if not pool:
        return []
    cutoff = (datetime.now() - timedelta(days=max(1, days))).strftime("%Y-%m-%d")
    return [
        {**r, "source_url": source_url}
        for r in parse_quiniela_scores_from_pool(pool, cutoff=cutoff)
    ]


def fetch_json(url: str, *, source: str = "kiskoo", timeout: int | None = None) -> dict:
    t0 = datetime.now()
    req_timeout = timeout if timeout is not None else JSON_TIMEOUT_SEC
    try:
        logger.info("%s GET %s | fuente=%s", LOG, url, source)
        resp = requests.get(url, headers=RD_FETCH_HEADERS, timeout=req_timeout)
        elapsed = (datetime.now() - t0).total_seconds()
        logger.info(
            "%s respuesta | url=%s | status=%s | bytes=%s | tiempo=%ss",
            LOG,
            url,
            resp.status_code,
            len(resp.content),
            round(elapsed, 2),
        )
        if resp.status_code >= 400:
            err = f"HTTP {resp.status_code}"
            log_rd_update(
                fuente=source,
                url=url,
                status=resp.status_code,
                tiempo=round(elapsed, 2),
                error=err,
            )
            return {
                "ok": False,
                "status_code": resp.status_code,
                "url": url,
                "elapsed": round(elapsed, 2),
                "error": err,
            }
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            err = f"JSON inválido: {exc}"
            log_rd_update(
                fuente=source,
                url=url,
                status=resp.status_code,
                tiempo=round(elapsed, 2),
                error=err,
            )
            return {
                "ok": False,
                "status_code": resp.status_code,
                "url": url,
                "elapsed": round(elapsed, 2),
                "error": err,
            }
        log_rd_update(
            fuente=source,
            url=url,
            status=resp.status_code,
            tiempo=round(elapsed, 2),
            resultados=len(data) if isinstance(data, list) else 1,
        )
        return {
            "ok": True,
            "data": data,
            "status_code": resp.status_code,
            "url": url,
            "elapsed": round(elapsed, 2),
        }
    except requests.RequestException as exc:
        elapsed = (datetime.now() - t0).total_seconds()
        logger.warning("%s error GET %s: %s", LOG, url, exc)
        err = str(exc)
        if "timeout" in err.lower() or "timed out" in err.lower():
            err = f"Timeout: {err}"
        log_rd_update(fuente=source, url=url, tiempo=round(elapsed, 2), error=err)
        return {
            "ok": False,
            "url": url,
            "elapsed": round(elapsed, 2),
            "error": err,
        }


def build_game_title_map(payload: list) -> dict[str, str]:
    """game_id (API) → título de página/juego desde _payload.json."""
    out: dict[str, str] = {}
    for i, item in enumerate(payload):
        if not isinstance(item, dict):
            continue
        obj = resolve_devalue(payload, i)
        if not isinstance(obj, dict):
            continue
        title = obj.get("title") or obj.get("mobile_title")
        gid = obj.get("game_id")
        if isinstance(gid, int):
            gid = resolve_devalue(payload, gid)
        if title and isinstance(gid, str) and len(gid) >= 20:
            out[gid] = str(title)
    return out


def fetch_sessions(api_base: str = CONECTATE_API, *, source: str = "conectate_api") -> dict:
    return fetch_json(
        f"{api_base.rstrip('/')}/conectate/sessions",
        source=source,
        timeout=SESSIONS_TIMEOUT_SEC,
    )


def sessions_to_rows(
    sessions: list,
    game_title_map: dict[str, str],
    *,
    cutoff: str,
    source_url: str,
) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple] = set()

    for item in sessions or []:
        if not isinstance(item, dict):
            continue
        gid = item.get("game_id")
        title = game_title_map.get(gid, "")
        mapping = map_kiskoo_title(title) if title else None
        if not mapping:
            continue
        lottery_name, draw_name = mapping

        for sess in item.get("sessions") or []:
            if not isinstance(sess, dict):
                continue
            draw_date = parse_iso_date(sess.get("date"))
            if not draw_date or draw_date < cutoff:
                continue
            nums = _flatten_score_numbers(sess.get("score"))
            if len(nums) < 3:
                continue
            nums = nums[:3]
            if not valid_quiniela(nums):
                continue
            key = (lottery_name, draw_name, draw_date, tuple(nums))
            if key in seen:
                continue
            seen.add(key)
            logger.info(
                "%s sorteo API | lotería=%s | tanda=%s | fecha=%s | nums=%s | juego=%s",
                LOG,
                lottery_name,
                draw_name,
                draw_date,
                nums,
                title,
            )
            rows.append({
                "lottery_name": lottery_name,
                "draw_name": draw_name,
                "draw_date": draw_date,
                "numbers": nums,
                "source_url": source_url,
                "game_title": title,
            })
    return rows


def fetch_hub_rows(
    *,
    api_base: str = CONECTATE_API,
    payload_url: str = CONECTATE_PAYLOAD,
    days: int = 30,
    source_label: str = "conectate_api",
) -> dict:
    """Todas las quinielas RD desde API sessions + mapa de títulos."""
    cache_key = (api_base, payload_url, int(days), source_label)
    now = time.monotonic()
    cached = _HUB_ROWS_CACHE.get(cache_key)
    if cached and (now - cached[0]) < HUB_CACHE_TTL_SEC:
        return cached[1]

    cutoff = (datetime.now() - timedelta(days=max(1, days))).strftime("%Y-%m-%d")
    payload_resp = fetch_json(payload_url, source=f"{source_label}_payload")
    if not payload_resp.get("ok"):
        out = {**payload_resp, "rows": [], "parser": KISKOO_PARSER_VERSION}
        return out

    payload = payload_resp["data"]
    if not isinstance(payload, list):
        out = {"ok": False, "error": "Payload inesperado", "rows": [], "parser": KISKOO_PARSER_VERSION}
        return out

    game_map = build_game_title_map(payload)
    sess_resp = fetch_sessions(api_base, source=source_label)
    if not sess_resp.get("ok"):
        out = {**sess_resp, "rows": [], "parser": KISKOO_PARSER_VERSION}
        return out

    rows = sessions_to_rows(
        sess_resp["data"],
        game_map,
        cutoff=cutoff,
        source_url=sess_resp.get("url", api_base),
    )
    elapsed = (payload_resp.get("elapsed") or 0) + (sess_resp.get("elapsed") or 0)
    out = {
        "ok": True,
        "rows": rows,
        "game_map_size": len(game_map),
        "status_code": sess_resp.get("status_code"),
        "url": sess_resp.get("url"),
        "elapsed": elapsed,
        "parser": KISKOO_PARSER_VERSION,
    }
    log_rd_update(
        fuente=source_label,
        url=out.get("url", ""),
        status=out.get("status_code"),
        tiempo=elapsed,
        resultados=len(rows),
        guardados=0,
        actualizados=0,
    )
    _HUB_ROWS_CACHE[cache_key] = (now, out)
    return out
