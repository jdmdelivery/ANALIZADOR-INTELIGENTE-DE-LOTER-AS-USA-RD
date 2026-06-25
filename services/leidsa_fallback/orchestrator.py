"""Orquestador de fuentes fallback LEIDSA."""
from __future__ import annotations

import time
from typing import Any, Callable

from services.leidsa_config import SOURCE_NAME
from services.leidsa_fallback.enloteria_parser import (
    DEFAULT_URL as ENLOTERIA_URL,
    SOURCE_KEY as ENLOTERIA_KEY,
    SOURCE_LABEL as ENLOTERIA_LABEL,
    parse_enloteria_html,
)
from services.leidsa_fallback.leidsa_official_parser import (
    OFFICIAL_URL,
    SOURCE_KEY as OFFICIAL_KEY,
    SOURCE_LABEL as OFFICIAL_LABEL,
    fetch_official_page,
    parse_leidsa_official_html,
)
from services.leidsa_fallback.log import log_leidsa_fallback
from services.leidsa_fallback.loteriasdominicanas_us_parser import (
    DEFAULT_URL as LDUS_URL,
    SOURCE_KEY as LDUS_KEY,
    SOURCE_LABEL as LDUS_LABEL,
    parse_loteriasdominicanas_us_html,
)
from services.leidsa_fallback.nacionalloteria_parser import (
    DEFAULT_URL as NACIONAL_URL,
    SOURCE_KEY as NACIONAL_KEY,
    SOURCE_LABEL as NACIONAL_LABEL,
    parse_nacionalloteria_html,
)
from services.leidsa_fallback.normalize import latest_date_in_rows, pick_latest_per_game
from services.leidsa_fallback.yelu_parser import (
    DEFAULT_URL as YELU_URL,
    SOURCE_KEY as YELU_KEY,
    SOURCE_LABEL as YELU_LABEL,
    parse_yelu_html,
)

SourceSpec = tuple[str, str, str, Callable[[str, str], list[dict]]]


def _fetch_rd(url: str, source: str) -> dict[str, Any]:
    from scrapers.rd_http import fetch_rd_url

    return fetch_rd_url(url, source=source, min_bytes=400)


def _fetch_official(url: str) -> dict[str, Any]:
    return fetch_official_page(url)


def _fetch_ldus(url: str) -> dict[str, Any]:
    last: dict[str, Any] = {"ok": False, "error": "fetch failed"}
    for candidate in (url, "https://www.loteriasdominicanas.us/leidsa"):
        last = _fetch_rd(candidate, LDUS_KEY)
        if last.get("ok"):
            return last
    return last


def _fetch_source(key: str, url: str) -> dict[str, Any]:
    if key == OFFICIAL_KEY:
        return _fetch_official(url)
    if key == LDUS_KEY:
        return _fetch_ldus(url)
    return _fetch_rd(url, key)


SOURCE_CHAIN: list[SourceSpec] = [
    (OFFICIAL_KEY, OFFICIAL_LABEL, OFFICIAL_URL, parse_leidsa_official_html),
    (ENLOTERIA_KEY, ENLOTERIA_LABEL, ENLOTERIA_URL, parse_enloteria_html),
    (LDUS_KEY, LDUS_LABEL, LDUS_URL, parse_loteriasdominicanas_us_html),
    (YELU_KEY, YELU_LABEL, YELU_URL, parse_yelu_html),
    (NACIONAL_KEY, NACIONAL_LABEL, NACIONAL_URL, parse_nacionalloteria_html),
]


def scrape_leidsa_with_fallbacks() -> dict[str, Any]:
    """Intenta fuentes en orden; para en la primera con resultados válidos."""
    errors: list[str] = []
    attempts: list[dict] = []

    for key, label, url, parse_fn in SOURCE_CHAIN:
        t0 = time.monotonic()
        try:
            fetch = _fetch_source(key, url)
        except Exception as exc:
            elapsed = round(time.monotonic() - t0, 2)
            err = str(exc)
            log_leidsa_fallback(
                fuente=key,
                url=url,
                status="error",
                tiempo=elapsed,
                juego="todos",
                error=err,
            )
            errors.append(f"{label}: {err}")
            attempts.append({"fuente": key, "url": url, "error": err})
            continue

        elapsed = round(time.monotonic() - t0, 2)
        status = fetch.get("status_code") or ("ok" if fetch.get("ok") else "error")

        if not fetch.get("ok"):
            err = fetch.get("error") or f"HTTP {status}"
            log_leidsa_fallback(
                fuente=key,
                url=url,
                status=status,
                tiempo=elapsed,
                juego="todos",
                resultados_encontrados=0,
                error=err,
            )
            errors.append(f"{label}: {err}")
            attempts.append({"fuente": key, "url": url, "status": status, "error": err})
            continue

        html = fetch.get("html") or ""
        raw_rows = parse_fn(html, url)
        rows = pick_latest_per_game(raw_rows)

        if not rows:
            err = "parser sin resultados válidos"
            log_leidsa_fallback(
                fuente=key,
                url=url,
                status=status,
                tiempo=elapsed,
                juego="todos",
                resultados_encontrados=0,
                error=err,
            )
            errors.append(f"{label}: {err}")
            attempts.append({"fuente": key, "url": url, "status": status, "error": err})
            continue

        log_leidsa_fallback(
            fuente=key,
            url=url,
            status=status,
            tiempo=elapsed,
            juego="todos",
            resultados_encontrados=len(rows),
        )
        latest = latest_date_in_rows(rows)
        return {
            "ok": True,
            "source": label,
            "results": rows,
            "rows": rows,
            "error": None,
            "message": f"OK desde {label}",
            "parser": key,
            "fuente": key,
            "fuente_usada": key,
            "fuente_label": label,
            "status_code": fetch.get("status_code"),
            "method": fetch.get("method"),
            "html_length": len(html),
            "latest_date": latest,
            "url": url,
            "attempts": attempts,
            "fallback_used": key != OFFICIAL_KEY,
        }

    return {
        "ok": False,
        "source": SOURCE_NAME,
        "results": [],
        "rows": [],
        "error": "; ".join(errors[:5]) if errors else "Todas las fuentes LEIDSA fallaron",
        "message": "LEIDSA: todas las fuentes fallaron",
        "parser": "fallback_chain",
        "errors": errors,
        "attempts": attempts,
        "status_code": attempts[-1].get("status") if attempts else None,
        "blocking_type": "forbidden" if any("403" in e for e in errors) else None,
    }
