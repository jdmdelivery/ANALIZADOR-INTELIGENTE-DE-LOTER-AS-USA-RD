"""Cliente HTTP compartido LEIDSA — cloudscraper + headers reales."""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

from services.leidsa_config import BROWSER_HEADERS, FETCH_RETRIES, FETCH_TIMEOUT, SOURCE_URL

logger = logging.getLogger(__name__)
LOG_TAG = "[LEIDSA SCRAPER]"

_session: Any = None
_warmed = False


def log_leidsa_scraper(
    *,
    url: str = "",
    status: str | int = "",
    tiempo: str | float = "",
    juego: str = "",
    resultados: int | str = "",
    nuevos: int | str = "",
    actualizados: int | str = "",
    error: str | None = None,
) -> None:
    lines = [
        LOG_TAG,
        f"URL: {url}",
        f"Status: {status}",
        f"Tiempo: {tiempo}s" if tiempo != "" else "Tiempo:",
        f"Juego: {juego}",
        f"Resultados encontrados: {resultados}",
        f"Nuevos: {nuevos}",
        f"Actualizados: {actualizados}",
        f"Error: {error or ''}",
    ]
    text = "\n".join(lines)
    if error:
        logger.error(text)
    else:
        logger.info(text)
    print(text)


def get_leidsa_session():
    global _session
    if _session is None:
        try:
            import cloudscraper  # noqa: WPS433

            _session = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False},
            )
        except ImportError:
            _session = requests.Session()
        _session.headers.update(BROWSER_HEADERS)
    return _session


def warm_leidsa_session() -> None:
    """Primera visita a home para cookies / challenge Cloudflare."""
    global _warmed
    if _warmed:
        return
    try:
        session = get_leidsa_session()
        resp = session.get(SOURCE_URL, timeout=FETCH_TIMEOUT)
        if resp.status_code == 200 and len(resp.text or "") > 5000:
            _warmed = True
    except Exception:
        pass


def fetch_leidsa_page(
    url: str,
    *,
    juego: str = "",
    use_cache: bool = False,
    min_bytes: int = 1000,
    require_draw_data: bool = False,
) -> dict[str, Any]:
    """
    GET a leidsa.com con reintentos.
    require_draw_data: en páginas /results/ exige drawnValues en HTML.
    """
    warm_leidsa_session()
    session = get_leidsa_session()
    last_error = None
    status_code = None
    t0 = time.monotonic()
    retries = int(os.environ.get("LEIDSA_FETCH_RETRIES", str(FETCH_RETRIES + 1)))

    for attempt in range(1, retries + 1):
        try:
            headers = {
                **BROWSER_HEADERS,
                "Referer": SOURCE_URL if url != SOURCE_URL else "https://www.google.com/",
            }
            resp = session.get(url, headers=headers, timeout=FETCH_TIMEOUT)
            status_code = resp.status_code
            html = resp.text or ""
            elapsed = round(time.monotonic() - t0, 2)

            if status_code != 200:
                last_error = f"HTTP {status_code}"
                log_leidsa_scraper(
                    url=url,
                    status=status_code,
                    tiempo=elapsed,
                    juego=juego or "fetch",
                    error=last_error,
                )
                time.sleep(1.2 * attempt)
                continue

            if len(html) < min_bytes:
                last_error = f"HTML demasiado corto ({len(html)} bytes)"
                log_leidsa_scraper(
                    url=url,
                    status=status_code,
                    tiempo=elapsed,
                    juego=juego or "fetch",
                    error=last_error,
                )
                time.sleep(1.0 * attempt)
                continue

            low = html.lower()
            if require_draw_data or "/results/" in url:
                if "drawnvalues" not in low and "gamedrawid" not in low and "drawresults" not in low:
                    last_error = "HTML sin drawResults/drawnValues (posible bloqueo WAF)"
                    log_leidsa_scraper(
                        url=url,
                        status=status_code,
                        tiempo=elapsed,
                        juego=juego or "fetch",
                        error=last_error,
                    )
                    time.sleep(1.0 * attempt)
                    continue

            if url.rstrip("/") == SOURCE_URL.rstrip("/"):
                if (
                    "drawnvalues" not in low
                    and "previousdrawdetails" not in low
                    and "latestdrawdetails" not in low
                ):
                    last_error = "HTML sin JSON embebido de sorteos"
                    log_leidsa_scraper(
                        url=url,
                        status=status_code,
                        tiempo=elapsed,
                        juego=juego or "home",
                        error=last_error,
                    )
                    time.sleep(1.0 * attempt)
                    continue

            method = "cloudscraper" if "cloudscraper" in type(session).__module__ else "requests"
            log_leidsa_scraper(
                url=url,
                status=status_code,
                tiempo=elapsed,
                juego=juego or "fetch",
                resultados="ok",
            )
            return {
                "ok": True,
                "html": html,
                "url": resp.url,
                "status_code": status_code,
                "elapsed": elapsed,
                "method": method,
                "size": len(html),
            }
        except requests.RequestException as exc:
            last_error = str(exc)
            log_leidsa_scraper(
                url=url,
                status=status_code or "error",
                tiempo=round(time.monotonic() - t0, 2),
                juego=juego or "fetch",
                error=last_error,
            )
            time.sleep(1.2 * attempt)

    elapsed = round(time.monotonic() - t0, 2)
    return {
        "ok": False,
        "html": "",
        "url": url,
        "status_code": status_code,
        "elapsed": elapsed,
        "error": last_error or "Error de red",
        "method": None,
    }
