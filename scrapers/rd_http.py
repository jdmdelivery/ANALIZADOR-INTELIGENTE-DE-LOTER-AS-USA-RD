"""Cliente HTTP compartido para scrapers RD (local + Render)."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta

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
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

DEFAULT_CONNECT_TIMEOUT = float(os.environ.get("RD_FETCH_CONNECT_TIMEOUT", "8"))
DEFAULT_READ_TIMEOUT = float(os.environ.get("RD_FETCH_READ_TIMEOUT", "20"))
DEFAULT_RETRIES = int(os.environ.get("RD_FETCH_RETRIES", "2" if os.environ.get("RENDER") else "3"))
SOURCE_DISABLE_MINUTES = int(os.environ.get("RD_SOURCE_DISABLE_MINUTES", "10"))

_session = None
_SOURCE_DISABLED_UNTIL: dict[str, datetime] = {}


def is_render_env() -> bool:
    return bool(os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"))


def get_rd_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(RD_HEADERS)
    return _session


def _timeout_tuple(timeout: int | float | tuple | None):
    if isinstance(timeout, tuple):
        return timeout
    if timeout is None:
        return (DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT)
    t = float(timeout)
    return (min(t, DEFAULT_CONNECT_TIMEOUT), max(t, DEFAULT_READ_TIMEOUT))


def _should_retry_status(status_code: int | None, attempt: int, retries: int) -> bool:
    if not status_code:
        return attempt < retries
    if status_code in (400, 401, 403, 404):
        return False
    if status_code == 429:
        return attempt < min(retries, 2)
    if status_code >= 500:
        return attempt < retries
    return False


def _is_source_disabled(source: str) -> tuple[bool, str | None]:
    until = _SOURCE_DISABLED_UNTIL.get(source or "")
    if not until:
        return False, None
    now = datetime.now(UTC).replace(tzinfo=None)
    if now >= until:
        _SOURCE_DISABLED_UNTIL.pop(source, None)
        return False, None
    return True, until.isoformat(timespec="seconds")


def _mark_source_disabled(source: str) -> None:
    if not source:
        return
    _SOURCE_DISABLED_UNTIL[source] = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=SOURCE_DISABLE_MINUTES)


def fetch_rd_url(
    url: str,
    *,
    source: str = "rd",
    timeout: int | None = None,
    retries: int | None = None,
    min_bytes: int = 400,
) -> dict:
    timeout_tuple = _timeout_tuple(timeout)
    retries = retries or DEFAULT_RETRIES
    session = get_rd_session()
    last_error = None
    status_code = None
    t0 = time.monotonic()
    disabled, until = _is_source_disabled(source)
    if disabled:
        return {
            "ok": False,
            "html": "",
            "url": url,
            "status_code": 0,
            "elapsed": 0.0,
            "error": f"Fuente temporalmente deshabilitada hasta {until}",
            "message": f"Fuente temporalmente deshabilitada hasta {until}",
            "bytes": 0,
            "content_type": "",
        }

    for attempt in range(1, retries + 1):
        try:
            logger.info("%s GET %s | fuente=%s | intento=%s/%s", LOG, url, source, attempt, retries)
            resp = session.get(url, timeout=timeout_tuple)
            status_code = resp.status_code
            elapsed = round(time.monotonic() - t0, 2)
            size = len(resp.text or "")
            content_type = resp.headers.get("Content-Type", "")
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
                if status_code in (400, 401, 403, 404):
                    _mark_source_disabled(source)
                if not _should_retry_status(status_code, attempt, retries):
                    break
                time.sleep(min(1.2 * attempt, 2.5))
                continue
            html = resp.text or ""
            if size < min_bytes:
                last_error = f"HTML vacío o muy corto ({size} bytes)"
                if attempt >= retries:
                    break
                time.sleep(min(1.0 * attempt, 2.0))
                continue
            return {
                "ok": True,
                "html": html,
                "url": resp.url,
                "status_code": status_code,
                "elapsed": elapsed,
                "size": size,
                "bytes": len(resp.content or b""),
                "content_type": content_type,
            }
        except requests.RequestException as exc:
            last_error = str(exc)
            logger.warning("%s error GET %s: %s", LOG, url, exc)
            if attempt >= min(retries, 2):
                break
            time.sleep(min(1.0 * attempt, 2.0))

    return {
        "ok": False,
        "html": "",
        "url": url,
        "status_code": status_code,
        "elapsed": round(time.monotonic() - t0, 2),
        "error": last_error or "Error de red",
        "message": last_error or "Error de red",
        "bytes": 0,
        "content_type": "",
    }


def fetch_rd_json(
    url: str,
    *,
    source: str = "rd",
    timeout: int | None = None,
    retries: int | None = None,
) -> dict:
    """GET JSON con cloudscraper (misma sesión que HTML). Evita HTTP 403 en Render."""
    timeout_tuple = _timeout_tuple(timeout)
    retries = retries or DEFAULT_RETRIES
    session = get_rd_session()
    headers = {
        **RD_HEADERS,
        "Accept": "application/json, text/plain, */*",
    }
    last_error = None
    status_code = None
    t0 = time.monotonic()
    disabled, until = _is_source_disabled(source)
    if disabled:
        return {
            "ok": False,
            "url": url,
            "status_code": 0,
            "elapsed": 0.0,
            "error": f"Fuente temporalmente deshabilitada hasta {until}",
            "bytes": 0,
            "content_type": "",
        }

    for attempt in range(1, retries + 1):
        try:
            logger.info("%s GET JSON %s | fuente=%s | intento=%s/%s", LOG, url, source, attempt, retries)
            resp = session.get(url, headers=headers, timeout=timeout_tuple)
            status_code = resp.status_code
            elapsed = round(time.monotonic() - t0, 2)
            content_type = resp.headers.get("Content-Type", "")
            logger.info(
                "%s respuesta JSON | url=%s | status=%s | bytes=%s | tiempo=%ss",
                LOG,
                url,
                status_code,
                len(resp.content),
                elapsed,
            )
            if status_code >= 400:
                last_error = f"HTTP {status_code}"
                if status_code in (400, 401, 403, 404):
                    _mark_source_disabled(source)
                if not _should_retry_status(status_code, attempt, retries):
                    break
                time.sleep(min(1.2 * attempt, 2.5))
                continue
            try:
                data = resp.json()
            except json.JSONDecodeError as exc:
                last_error = f"JSON inválido: {exc}"
                if attempt >= retries:
                    break
                time.sleep(min(1.0 * attempt, 2.0))
                continue
            return {
                "ok": True,
                "data": data,
                "status_code": status_code,
                "url": resp.url,
                "elapsed": elapsed,
                "bytes": len(resp.content or b""),
                "content_type": content_type,
            }
        except requests.RequestException as exc:
            last_error = str(exc)
            logger.warning("%s error GET JSON %s: %s", LOG, url, exc)
            if attempt >= min(retries, 2):
                break
            time.sleep(min(1.0 * attempt, 2.0))

    return {
        "ok": False,
        "url": url,
        "status_code": status_code,
        "elapsed": round(time.monotonic() - t0, 2),
        "error": last_error or "Error de red",
        "bytes": 0,
        "content_type": "",
    }
