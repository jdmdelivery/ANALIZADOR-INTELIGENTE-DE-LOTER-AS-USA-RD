"""Metadatos última ejecución USA (debug / Render)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

META_DIRS = (
    Path(__file__).resolve().parents[2] / "data" / "illinois_cache",
    Path(__file__).resolve().parents[2] / "data" / "usa" / "illinois_cache",
)
META_NAME = "usa_last_run.json"


def _meta_paths() -> list[Path]:
    return [d / META_NAME for d in META_DIRS]


def save_last_run(
    *,
    fuente: str,
    status: str,
    cantidad_resultados: int,
    imported: int = 0,
    updated: int = 0,
    sources_tried: list[dict] | None = None,
    url: str = "",
    warning: bool = False,
    cache_used: bool = False,
) -> None:
    for d in META_DIRS:
        d.mkdir(parents=True, exist_ok=True)
    payload = {
        "fuente": fuente,
        "status": status,
        "fecha_actualizacion": datetime.now(timezone.utc).isoformat(),
        "cantidad_resultados": cantidad_resultados,
        "imported": imported,
        "updated": updated,
        "url": url,
        "warning": warning,
        "cache_used": cache_used,
        "sources_tried": sources_tried or [],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for path in _meta_paths():
        path.write_text(text, encoding="utf-8")


def load_last_run() -> dict:
    for path in _meta_paths():
        if not path.is_file():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
    return {}
