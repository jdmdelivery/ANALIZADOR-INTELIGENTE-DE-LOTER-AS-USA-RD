"""
Cliente HTTP compartido para scrapers USA (local + Render).
Cloudscraper, headers realistas, reintentos y logs detallados.
"""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)
LOG = "[USA SCRAPER]"

DEFAULT_TIMEOUT = int(os.environ.get("USA_FETCH_TIMEOUT", "35"))
DEFAULT_RETRIES = int(os.environ.get("USA_FETCH_RETRIES", "4"))

USA_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

_session = None


def create_usa_session():
    """Sesión cloudscraper tolerante a Cloudflare (Render/datacenter IPs)."""
    import cloudscraper

    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False},
        delay=10,
    )
    scraper.headers.update(USA_FETCH_HEADERS)
    return scraper


def get_usa_session():
    global _session
    if _session is None:
        _session = create_usa_session()
    return _session


def reset_usa_session():
    """Nueva sesión tras bloqueo 403 (p.ej. en Render)."""
    global _session
    _session = create_usa_session()
    return _session


def fetch_url(
    url: str,
    *,
    timeout: int | None = None,
    retries: int | None = None,
    min_bytes: int = 500,
    valid_markers: tuple[str, ...] = (),
    source: str = "usa",
) -> dict:
    """
    GET con reintentos. Devuelve dict con ok, html, status_code, elapsed, size, error.
    """
    timeout = timeout or DEFAULT_TIMEOUT
    retries = retries or DEFAULT_RETRIES
    session = get_usa_session()
    last_error = None
    status_code = None
    t0 = time.monotonic()

    for attempt in range(1, retries + 1):
        try:
            logger.info(
                "%s GET %s | fuente=%s | intento=%s/%s | timeout=%ss",
                LOG,
                url,
                source,
                attempt,
                retries,
                timeout,
            )
            resp = session.get(url, headers=USA_FETCH_HEADERS, timeout=timeout)
            status_code = resp.status_code
            elapsed = round(time.monotonic() - t0, 2)
            size = len(resp.text or "")
            logger.info(
                "%s respuesta | url=%s | status=%s | bytes=%s | tiempo=%ss",
                LOG,
                url,
                status_code,
                size,
                elapsed,
            )

            if status_code == 403:
                last_error = f"HTTP 403 Forbidden (posible bloqueo Cloudflare/IP datacenter)"
                reset_usa_session()
                time.sleep(2.0 * attempt)
                continue
            if status_code == 429:
                last_error = "HTTP 429 Too Many Requests"
                time.sleep(3.0 * attempt)
                continue
            if status_code >= 400:
                last_error = f"HTTP {status_code}"
                time.sleep(1.5 * attempt)
                continue

            html = resp.text or ""
            if len(html) < min_bytes:
                last_error = f"HTML demasiado corto ({size} bytes)"
                continue
            if valid_markers and not any(m in html for m in valid_markers):
                last_error = f"HTML sin marcadores esperados {valid_markers}"
                if "cloudflare" in html.lower() and "challenge" in html.lower():
                    last_error = "Página Cloudflare challenge detectada"
                    reset_usa_session()
                continue

            return {
                "ok": True,
                "html": html,
                "url": resp.url,
                "status_code": status_code,
                "elapsed": elapsed,
                "size": size,
                "source": source,
            }
        except Exception as exc:
            last_error = str(exc)
            logger.exception(
                "%s excepción | url=%s | intento=%s | error=%s",
                LOG,
                url,
                attempt,
                exc,
            )
            time.sleep(1.5 * attempt)

    elapsed = round(time.monotonic() - t0, 2)
    return {
        "ok": False,
        "message": last_error or "Error de red",
        "url": url,
        "status_code": status_code,
        "elapsed": elapsed,
        "source": source,
        "error": last_error,
    }
