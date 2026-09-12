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
_SOURCE_HEALTH: dict[str, dict] = {}


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


def _now_utc_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _health_row(source: str) -> dict:
    key = source or "rd"
    row = _SOURCE_HEALTH.get(key)
    if row is None:
        row = {
            "source": key,
            "success": 0,
            "failure": 0,
            "failure_count": 0,
            "last_success_at": None,
            "last_failure_at": None,
            "avg_latency_ms": None,
            "disabled_until": None,
            "reason": None,
        }
        _SOURCE_HEALTH[key] = row
    return row


def _update_health_success(source: str, elapsed_s: float) -> None:
    row = _health_row(source)
    row["success"] = int(row.get("success") or 0) + 1
    row["failure_count"] = 0
    row["last_success_at"] = _now_utc_naive().isoformat(timespec="seconds")
    prev = row.get("avg_latency_ms")
    sample = max(0.0, float(elapsed_s or 0) * 1000.0)
    row["avg_latency_ms"] = sample if prev is None else round((float(prev) * 0.7) + (sample * 0.3), 2)
    row["reason"] = None
    row["disabled_until"] = _SOURCE_DISABLED_UNTIL.get(source).isoformat(timespec="seconds") if _SOURCE_DISABLED_UNTIL.get(source) else None


def _update_health_failure(source: str, *, reason: str, elapsed_s: float | None = None) -> None:
    row = _health_row(source)
    row["failure"] = int(row.get("failure") or 0) + 1
    row["failure_count"] = int(row.get("failure_count") or 0) + 1
    row["last_failure_at"] = _now_utc_naive().isoformat(timespec="seconds")
    if elapsed_s is not None:
        prev = row.get("avg_latency_ms")
        sample = max(0.0, float(elapsed_s or 0) * 1000.0)
        row["avg_latency_ms"] = sample if prev is None else round((float(prev) * 0.8) + (sample * 0.2), 2)
    row["reason"] = reason
    row["disabled_until"] = _SOURCE_DISABLED_UNTIL.get(source).isoformat(timespec="seconds") if _SOURCE_DISABLED_UNTIL.get(source) else None


def _is_source_disabled(source: str) -> tuple[bool, str | None]:
    until = _SOURCE_DISABLED_UNTIL.get(source or "")
    if not until:
        return False, None
    now = _now_utc_naive()
    if now >= until:
        _SOURCE_DISABLED_UNTIL.pop(source, None)
        row = _health_row(source)
        row["disabled_until"] = None
        return False, None
    return True, until.isoformat(timespec="seconds")


def _mark_source_disabled(source: str, *, reason: str = "temporary_unavailable", ttl_minutes: int | None = None) -> None:
    if not source:
        return
    ttl = int(ttl_minutes or SOURCE_DISABLE_MINUTES)
    _SOURCE_DISABLED_UNTIL[source] = _now_utc_naive() + timedelta(minutes=ttl)
    row = _health_row(source)
    row["reason"] = reason
    row["disabled_until"] = _SOURCE_DISABLED_UNTIL[source].isoformat(timespec="seconds")


def mark_source_unavailable(source: str, *, reason: str, ttl_minutes: int | None = None) -> None:
    _mark_source_disabled(source, reason=reason, ttl_minutes=ttl_minutes)


def get_source_health_snapshot(source: str | None = None) -> dict:
    if source:
        return dict(_health_row(source))
    return {k: dict(v) for k, v in _SOURCE_HEALTH.items()}


def rank_sources(sources: list[str]) -> list[str]:
    ordered: list[tuple] = []
    for idx, src in enumerate(sources):
        disabled, _ = _is_source_disabled(src)
        row = _health_row(src)
        ok = int(row.get("success") or 0)
        fail = int(row.get("failure") or 0)
        total = ok + fail
        success_rate = (ok / total) if total else 0.5
        latency = float(row.get("avg_latency_ms") or 999999.0)
        ordered.append((1 if disabled else 0, -success_rate, latency, idx, src))
    ordered.sort()
    return [src for *_rest, src in ordered]


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
        _update_health_failure(source, reason=f"disabled_until={until}", elapsed_s=0.0)
        return {
            "ok": False,
            "html": "",
            "url": url,
            "status_code": 0,
            "elapsed": 0.0,
            "source": source,
            "disabled_until": until,
            "error": f"Fuente temporalmente deshabilitada hasta {until}",
            "message": f"Fuente temporalmente deshabilitada hasta {until}",
            "bytes": 0,
            "content_type": "",
            "source_health": dict(_health_row(source)),
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
                    _mark_source_disabled(source, reason=last_error)
                _update_health_failure(source, reason=last_error, elapsed_s=elapsed)
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
            _update_health_success(source, elapsed)
            return {
                "ok": True,
                "html": html,
                "url": resp.url,
                "status_code": status_code,
                "elapsed": elapsed,
                "source": source,
                "size": size,
                "bytes": len(resp.content or b""),
                "content_type": content_type,
                "source_health": dict(_health_row(source)),
            }
        except requests.RequestException as exc:
            last_error = str(exc)
            logger.warning("%s error GET %s: %s", LOG, url, exc)
            elapsed = round(time.monotonic() - t0, 2)
            err_low = last_error.lower()
            is_timeout = ("timeout" in err_low) or ("timed out" in err_low)
            _update_health_failure(source, reason=last_error, elapsed_s=elapsed)
            if is_timeout and attempt >= 1:
                _mark_source_disabled(source, reason="connect_timeout", ttl_minutes=SOURCE_DISABLE_MINUTES)
            if attempt >= min(retries, 2):
                break
            time.sleep(min(1.0 * attempt, 2.0))

    return {
        "ok": False,
        "html": "",
        "url": url,
        "status_code": status_code,
        "elapsed": round(time.monotonic() - t0, 2),
        "source": source,
        "disabled_until": _SOURCE_DISABLED_UNTIL.get(source).isoformat(timespec="seconds") if _SOURCE_DISABLED_UNTIL.get(source) else None,
        "error": last_error or "Error de red",
        "message": last_error or "Error de red",
        "bytes": 0,
        "content_type": "",
        "source_health": dict(_health_row(source)),
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
        _update_health_failure(source, reason=f"disabled_until={until}", elapsed_s=0.0)
        return {
            "ok": False,
            "url": url,
            "status_code": 0,
            "elapsed": 0.0,
            "source": source,
            "disabled_until": until,
            "error": f"Fuente temporalmente deshabilitada hasta {until}",
            "bytes": 0,
            "content_type": "",
            "source_health": dict(_health_row(source)),
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
                    _mark_source_disabled(source, reason=last_error)
                _update_health_failure(source, reason=last_error, elapsed_s=elapsed)
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
            _update_health_success(source, elapsed)
            return {
                "ok": True,
                "data": data,
                "status_code": status_code,
                "url": resp.url,
                "elapsed": elapsed,
                "source": source,
                "bytes": len(resp.content or b""),
                "content_type": content_type,
                "source_health": dict(_health_row(source)),
            }
        except requests.RequestException as exc:
            last_error = str(exc)
            logger.warning("%s error GET JSON %s: %s", LOG, url, exc)
            elapsed = round(time.monotonic() - t0, 2)
            err_low = last_error.lower()
            is_timeout = ("timeout" in err_low) or ("timed out" in err_low)
            _update_health_failure(source, reason=last_error, elapsed_s=elapsed)
            if is_timeout and attempt >= 1:
                _mark_source_disabled(source, reason="connect_timeout", ttl_minutes=SOURCE_DISABLE_MINUTES)
            if attempt >= min(retries, 2):
                break
            time.sleep(min(1.0 * attempt, 2.0))

    return {
        "ok": False,
        "url": url,
        "status_code": status_code,
        "elapsed": round(time.monotonic() - t0, 2),
        "source": source,
        "disabled_until": _SOURCE_DISABLED_UNTIL.get(source).isoformat(timespec="seconds") if _SOURCE_DISABLED_UNTIL.get(source) else None,
        "error": last_error or "Error de red",
        "bytes": 0,
        "content_type": "",
        "source_health": dict(_health_row(source)),
    }
