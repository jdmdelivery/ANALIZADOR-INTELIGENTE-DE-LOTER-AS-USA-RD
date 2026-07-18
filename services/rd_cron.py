"""Cron RD — actualización periódica segura para Render (no bloquea health check)."""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()
_last_run: float | None = None

INTERVAL_MIN = int(os.environ.get("RD_CRON_INTERVAL_MIN", "20"))
ENABLED = os.environ.get("RD_CRON_DISABLED", "").lower() not in ("1", "true", "yes")


def _run_rd_job() -> None:
    global _last_run
    t0 = time.monotonic()
    try:
        from services.rd_results_service import actualizar_rd_loteria

        logger.info("[RD_CRON] Iniciando actualización RD (%s min)", INTERVAL_MIN)
        actualizar_rd_loteria("Lotería Nacional", days=7)
        try:
            from services.leidsa_history import fetch_all_leidsa_history
            from services.leidsa_service import update_leidsa_now

            fetch_all_leidsa_history(days=14, limit_per_game=60, use_cache=False, save=True)
            update_leidsa_now()
        except Exception:
            logger.exception("[RD_CRON] LEIDSA update failed")
        logger.info("[RD_CRON] Completado en %.1fs", time.monotonic() - t0)
    except Exception:
        logger.exception("[RD_CRON] Error en job RD")
    finally:
        _last_run = time.time()


def _leidsa_needs_refresh(*, max_age_days: int = 3) -> bool:
    try:
        from models import get_all_lotteries, get_max_draw_date
        from services.leidsa_history import _days_since_draw

        for lot in get_all_lotteries():
            if (lot.get("country") or "").upper() != "RD":
                continue
            ltype = (lot.get("type") or "").lower()
            if not ltype.startswith("leidsa_"):
                continue
            latest = get_max_draw_date(lot["id"])
            age = _days_since_draw(latest) if latest else None
            if age is None or age > max_age_days:
                return True
        return False
    except Exception:
        logger.exception("[RD_CRON] No se pudo evaluar frescura LEIDSA")
        return True


def _loop() -> None:
    # Primer pase pronto tras el deploy (no esperar 20 min con BD vieja del repo)
    time.sleep(45)
    while True:
        if ENABLED:
            if not _lock.acquire(blocking=False):
                logger.info("[RD_CRON] Job anterior aún en curso — omitiendo")
            else:
                try:
                    if _leidsa_needs_refresh() or _last_run is None:
                        _run_rd_job()
                    else:
                        logger.info("[RD_CRON] LEIDSA reciente — omitiendo ciclo")
                finally:
                    _lock.release()
        time.sleep(max(5, INTERVAL_MIN) * 60)


def start_rd_cron() -> None:
    global _started
    if _started or not ENABLED:
        return
    _started = True
    th = threading.Thread(target=_loop, name="rd-cron", daemon=True)
    th.start()
    logger.info("[RD_CRON] Programado cada %s minutos (primer pase ~45s)", INTERVAL_MIN)


def run_rd_job_now() -> dict:
    """Ejecuta job RD una vez (admin)."""
    if not _lock.acquire(blocking=False):
        return {"ok": False, "message": "Job RD ya en ejecución"}
    try:
        _run_rd_job()
        return {"ok": True, "message": "Job RD completado"}
    finally:
        _lock.release()
