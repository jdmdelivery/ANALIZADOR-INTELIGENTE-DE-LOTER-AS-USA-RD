"""Registro y estado de fuentes RD — prioridad, timeouts y logs."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)

LOG_SCRAPER = "[RD_SCRAPER]"
LOG_FALLBACK = "[RD_FALLBACK]"
LOG_DUP = "[RD_DUPLICADO]"
LOG_RES = "[RD_RESULTADO]"

# (key, label, timeout_seg, solo_leidsa)
RD_FUENTES: list[tuple[str, str, int, bool]] = [
    ("conectate_sites_env", "Conectate API sites/env", 12, False),
    ("ld_sites_env", "Loterías Dominicanas API sites/env", 12, False),
    ("conectate_api", "Conectate API sessions", 18, False),
    ("conectate_html", "Conectate.com.do", 20, False),
    ("loteriasdominicanas", "LoteriasDominicanas.com", 18, False),
    ("loteriadominicana", "LoteriaDominicana.com.do", 18, False),
    ("sorteosrd", "SorteosRD.com", 15, False),
    ("enloteria", "EnLoteria.com", 15, False),
    ("leidsa", "LEIDSA.com", 25, True),
    ("loteriasdominicanas_us", "LoteriasDominicanas.us", 15, True),
]

_SOURCE_STATUS: dict[str, dict] = {}
_LAST_RD_UPDATE: str | None = None


def mark_rd_update() -> None:
    global _LAST_RD_UPDATE
    _LAST_RD_UPDATE = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_last_rd_update() -> str | None:
    return _LAST_RD_UPDATE


def get_fuentes_status() -> list[dict]:
    out = []
    for key, label, timeout, leidsa_only in RD_FUENTES:
        st = _SOURCE_STATUS.get(key, {})
        out.append({
            "key": key,
            "label": label,
            "timeout_sec": timeout,
            "leidsa_only": leidsa_only,
            "last_ok": st.get("ok"),
            "last_status": st.get("status_code"),
            "last_count": st.get("count", 0),
            "last_error": st.get("error"),
            "last_run": st.get("at"),
            "elapsed": st.get("elapsed"),
        })
    return out


def _record(key: str, result: dict) -> None:
    _SOURCE_STATUS[key] = {
        "ok": bool(result.get("ok")),
        "status_code": result.get("status_code"),
        "count": len(result.get("rows") or []),
        "error": result.get("error") or result.get("message"),
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed": result.get("elapsed"),
    }


def run_source(
    key: str,
    fn: Callable[..., dict],
    *,
    days: int = 30,
    lottery_name: str | None = None,
    fecha: str | None = None,
    **kwargs: Any,
) -> dict:
    """Ejecuta una fuente con timeout lógico y logging."""
    meta = next((f for f in RD_FUENTES if f[0] == key), None)
    label = meta[1] if meta else key
    t0 = time.monotonic()
    try:
        result = fn(days=days, lottery_name=lottery_name, fecha=fecha, **kwargs)
        result["elapsed"] = round(time.monotonic() - t0, 2)
        result.setdefault("fuente", key)
        result.setdefault("fuente_label", label)
        _record(key, result)
        fecha_log = fecha or datetime.now().strftime("%Y-%m-%d")
        count = len(result.get("rows") or [])
        status = "ok" if result.get("ok") else "error"
        logger.info(
            "%s fecha=%s fuente=%s status=%s encontrados=%s",
            LOG_SCRAPER, fecha_log, label, status, count,
        )
        print(f"{LOG_SCRAPER} fecha={fecha_log} fuente={label} status={status} encontrados={count}")
        if not result.get("ok"):
            err = result.get("error") or result.get("message") or "sin datos"
            logger.warning("%s fuente=%s — %s", LOG_FALLBACK, label, err)
            print(f"{LOG_FALLBACK} fuente={label} falló — {err}")
        return result
    except Exception as exc:
        elapsed = round(time.monotonic() - t0, 2)
        out = {"ok": False, "error": str(exc), "rows": [], "fuente": key, "elapsed": elapsed}
        _record(key, out)
        logger.exception("%s fuente=%s error", LOG_FALLBACK, label)
        print(f"{LOG_FALLBACK} fuente={label} excepción — {exc}")
        return out


def log_resultado(accion: str, row: dict, fuente: str) -> None:
    msg = (
        f"{LOG_RES} {accion} loteria={row.get('lottery_name')} "
        f"sorteo={row.get('draw_name')} fecha={row.get('draw_date')} "
        f"numeros={'-'.join(row.get('numbers') or [])} fuente={fuente}"
    )
    logger.info(msg)
    print(msg)
