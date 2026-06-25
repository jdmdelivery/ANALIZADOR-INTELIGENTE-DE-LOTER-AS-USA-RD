"""Parser fuente oficial LEIDSA — /en/results."""
from __future__ import annotations

from typing import Any

OFFICIAL_URL = "https://www.leidsa.com/en/results"
SOURCE_KEY = "leidsa_official"
SOURCE_LABEL = "LEIDSA.com"


def fetch_official_page(url: str = OFFICIAL_URL) -> dict[str, Any]:
    from services.leidsa_http import fetch_leidsa_page

    return fetch_leidsa_page(
        url,
        juego="official",
        min_bytes=5000,
        require_draw_data=True,
    )


def parse_leidsa_official_html(html: str, source_url: str = OFFICIAL_URL) -> list[dict]:
    from services.leidsa_service import parse_leidsa_html

    parsed = parse_leidsa_html(html)
    rows = list(parsed.get("results") or [])
    for row in rows:
        row["fuente"] = SOURCE_LABEL
        row["source_url"] = source_url
    return rows
