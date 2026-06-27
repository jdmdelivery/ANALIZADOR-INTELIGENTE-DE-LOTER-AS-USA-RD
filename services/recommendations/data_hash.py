"""Huella de los sorteos usados en un análisis — cambia si entran datos nuevos."""
from __future__ import annotations

import hashlib


def hash_draw_rows(rows: list[dict]) -> str:
  """SHA-256 corto sobre fecha+hora+números de cada fila (orden cronológico inverso)."""
  if not rows:
    return ""
  parts: list[str] = []
  for row in rows:
    nums = row.get("numbers") or row.get("main_numbers") or ""
    parts.append(
      "|".join(
        [
          str(row.get("draw_date") or ""),
          str(row.get("draw_time") or ""),
          str(row.get("draw_name") or ""),
          str(nums),
          str(row.get("id") or ""),
        ]
      )
    )
  payload = "\n".join(parts)
  return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
