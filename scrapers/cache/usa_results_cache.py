"""Caché JSON de resultados USA parseados (fallback si fallan ambas fuentes)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# data/illinois_cache/ (solicitado) + compat data/usa/illinois_cache/
CACHE_DIRS = (
    Path(__file__).resolve().parents[2] / "data" / "illinois_cache",
    Path(__file__).resolve().parents[2] / "data" / "usa" / "illinois_cache",
)
SNAPSHOT_NAME = "results_snapshot.json"


def _snapshot_paths() -> list[Path]:
    return [d / SNAPSHOT_NAME for d in CACHE_DIRS]


def _ensure_dirs() -> None:
    for d in CACHE_DIRS:
        d.mkdir(parents=True, exist_ok=True)


def save_results_snapshot(rows: list[dict], *, fuente: str, url: str = "") -> None:
    if not rows:
        return
    _ensure_dirs()
    payload = {
        "fecha": datetime.now(timezone.utc).isoformat(),
        "fuente": fuente,
        "url": url,
        "resultados": rows,
        "count": len(rows),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for path in _snapshot_paths():
        path.write_text(text, encoding="utf-8")


def load_results_snapshot() -> dict:
    for path in _snapshot_paths():
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            rows = data.get("resultados") or []
            if rows:
                data["ok"] = True
                data["from_cache"] = True
                data["cache_path"] = str(path)
                return data
        except (json.JSONDecodeError, OSError):
            continue
    return {"ok": False, "message": "Sin caché JSON de resultados USA."}
