"""Cliente HTTP compartido para scrapers RD (local + Render)."""
from __future__ import annotations

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)
LOG = "[RD SCRAPER]"

RD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-DO,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

DEFAULT_TIMEOUT = int(os.environ.get("RD_FETCH_TIMEOUT", "20" if os.environ.get("RENDER") else "25"))
DEFAULT_RETRIES = int(os.environ.get("RD_FETCH_RETRIES", "2" if os.environ.get("RENDER") else "3"))

_session = None


def is_render_env() -> bool:
    return bool(os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"))


def get_rd_session():
    global _session
    if _session is None:
        try:
            import cloudscraper

            _session = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False},
            )
        except Exception:
            _session = requests.Session()
        _session.headers.update(RD_HEADERS)
    return _session


def fetch_rd_url(
    url: str,
    *,
    source: str = "rd",
    timeout: int | None = None,
    retries: int | None = None,
    min_bytes: int = 400,
) -> dict:
    timeout = timeout or DEFAULT_TIMEOUT
    retries = retries or DEFAULT_RETRIES
    session = get_rd_session()
    last_error = None
    status_code = None
    t0 = time.monotonic()

    for attempt in range(1, retries + 1):
        try:
            logger.info("%s GET %s | fuente=%s | intento=%s/%s", LOG, url, source, attempt, retries)
            resp = session.get(url, timeout=timeout)
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
            if status_code >= 400:
                last_error = f"HTTP {status_code}"
                time.sleep(1.5 * attempt)
                continue
            html = resp.text or ""
            if size < min_bytes:
                last_error = f"HTML vacío o muy corto ({size} bytes)"
                time.sleep(1.0 * attempt)
                continue
            return {
                "ok": True,
                "html": html,
                "url": resp.url,
                "status_code": status_code,
                "elapsed": elapsed,
                "size": size,
            }
        except requests.RequestException as exc:
            last_error = str(exc)
            logger.warning("%s error GET %s: %s", LOG, url, exc)
            time.sleep(1.5 * attempt)

    return {
        "ok": False,
        "html": "",
        "url": url,
        "status_code": status_code,
        "elapsed": round(time.monotonic() - t0, 2),
        "error": last_error or "Error de red",
        "message": last_error or "Error de red",
    }
