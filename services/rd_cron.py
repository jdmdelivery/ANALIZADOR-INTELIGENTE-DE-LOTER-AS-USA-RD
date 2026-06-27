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
        logger.info("[RD_CRON] Completado en %.1fs", time.monotonic() - t0)
    except Exception:
        logger.exception("[RD_CRON] Error en job RD")
    finally:
        _last_run = time.time()


def _loop() -> None:
    while True:
        time.sleep(max(5, INTERVAL_MIN) * 60)
        if not ENABLED:
            continue
        if not _lock.acquire(blocking=False):
            logger.info("[RD_CRON] Job anterior aún en curso — omitiendo")
            continue
        try:
            _run_rd_job()
        finally:
            _lock.release()


def start_rd_cron() -> None:
    global _started
    if _started or not ENABLED:
        return
    _started = True
    th = threading.Thread(target=_loop, name="rd-cron", daemon=True)
    th.start()
    logger.info("[RD_CRON] Programado cada %s minutos", INTERVAL_MIN)


def run_rd_job_now() -> dict:
    """Ejecuta job RD una vez (admin)."""
    if not _lock.acquire(blocking=False):
        return {"ok": False, "message": "Job RD ya en ejecución"}
    try:
        _run_rd_job()
        return {"ok": True, "message": "Job RD completado"}
    finally:
        _lock.release()
