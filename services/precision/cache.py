"""Caché de snapshot del dashboard — invalidar al evaluar nuevos resultados."""
from __future__ import annotations

import time
from typing import Any

_CACHE: dict[str, Any] = {"payload": None, "built_at": 0.0, "epoch": 0}
_TTL_SEC = 120


def get_cached() -> dict | None:
    if not _CACHE["payload"]:
        return None
    if time.time() - _CACHE["built_at"] > _TTL_SEC:
        return None
    out = dict(_CACHE["payload"])
    out["cache_hit"] = True
    out["cache_age_sec"] = int(time.time() - _CACHE["built_at"])
    return out


def set_cached(payload: dict) -> dict:
    payload = dict(payload)
    payload["cache_hit"] = False
    payload["cache_epoch"] = _CACHE["epoch"]
    _CACHE["payload"] = payload
    _CACHE["built_at"] = time.time()
    return payload


def invalidate() -> None:
    _CACHE["epoch"] += 1
    _CACHE["payload"] = None
    _CACHE["built_at"] = 0.0
