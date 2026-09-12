"""Registro en memoria de jobs async para update RD."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime

_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}


def _now() -> str:
    try:
        from services.rd_time import now_rd

        return now_rd().isoformat(timespec="seconds")
    except Exception:
        return datetime.now().isoformat(timespec="seconds")


def create_job(payload: dict | None = None) -> dict:
    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "status": "queued",
        "started_at": None,
        "finished_at": None,
        "inserted": 0,
        "updated": 0,
        "ignored": 0,
        "rejected": 0,
        "errors": [],
        "sources": [],
        "request": payload or {},
    }
    with _LOCK:
        _JOBS[job_id] = job
    return job


def start_job(job_id: str) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id]["status"] = "running"
            _JOBS[job_id]["started_at"] = _now()


def finish_job(job_id: str, result: dict | None = None, error: str | None = None) -> None:
    result = result or {}
    with _LOCK:
        if job_id not in _JOBS:
            return
        job = _JOBS[job_id]
        if error:
            job["status"] = "failed"
            job["errors"] = [error]
        else:
            had_err = bool(result.get("errors"))
            has_new = int(result.get("imported") or result.get("inserted") or 0) > 0 or int(result.get("updated") or 0) > 0
            job["status"] = "partial" if had_err and has_new else ("success" if result.get("ok") else "failed")
            job["inserted"] = int(result.get("imported") or result.get("inserted") or 0)
            job["updated"] = int(result.get("updated") or 0)
            job["ignored"] = int(result.get("ignored") or 0)
            job["rejected"] = int(result.get("rejected") or 0)
            job["errors"] = list(result.get("errors") or [])
            job["sources"] = list(result.get("sources_tried") or [])
            job["latest_date"] = result.get("latest_date") or result.get("ultima_fecha")
            job["fecha_desde"] = result.get("fecha_desde")
            job["fecha_hasta"] = result.get("fecha_hasta")
            job["rows_found"] = int(result.get("rows_found") or result.get("results_found") or 0)
        job["finished_at"] = _now()


def get_job(job_id: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None
