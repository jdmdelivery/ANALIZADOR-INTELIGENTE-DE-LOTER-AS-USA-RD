"""Caché local del HTML de Illinois Results Hub (fallback si la red falla)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Caché USA aislado (no compartir con RD/LEIDSA)
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "usa" / "illinois_cache"
HTML_FILE = CACHE_DIR / "results_hub.html"
META_FILE = CACHE_DIR / "results_hub_meta.json"


def _ensure_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def save_hub_cache(html: str, *, url: str, status_code: int) -> None:
    _ensure_dir()
    HTML_FILE.write_text(html or "", encoding="utf-8")
    meta = {
        "url": url,
        "status_code": status_code,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "bytes": len(html or ""),
    }
    META_FILE.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def is_hub_cache_stale(max_age_hours: int = 36) -> bool:
    meta = cache_meta_summary()
    saved_at = meta.get("saved_at")
    if not saved_at:
        return True
    try:
        ts = datetime.fromisoformat(saved_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        return age_h > max_age_hours
    except (TypeError, ValueError):
        return True


def load_hub_cache(*, max_age_hours: int = 36):
    """
    Devuelve dict {ok, html, url, status_code, saved_at, from_cache} o {ok: False}.
    """
    if not HTML_FILE.is_file():
        return {"ok": False, "message": "Sin caché local de Illinois Results Hub."}
    if is_hub_cache_stale(max_age_hours):
        return {"ok": False, "message": "Caché Illinois Hub expirada (demasiado antigua)."}
    html = HTML_FILE.read_text(encoding="utf-8", errors="replace")
    if len(html) < 200:
        return {"ok": False, "message": "Caché local vacío o inválido."}
    meta = {}
    if META_FILE.is_file():
        try:
            meta = json.loads(META_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}
    return {
        "ok": True,
        "html": html,
        "url": meta.get("url") or "cache://illinois_results_hub",
        "status_code": meta.get("status_code"),
        "saved_at": meta.get("saved_at"),
        "from_cache": True,
    }


def cache_meta_summary() -> dict:
    if not META_FILE.is_file():
        return {}
    try:
        return json.loads(META_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
