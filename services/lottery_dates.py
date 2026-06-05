"""Utilidades de fechas compartidas para scrapers USA/RD."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

MONTHS_FULL = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}

MONTHS_ABBR = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def month_to_num(month: str) -> str | None:
    key = (month or "").strip().lower().rstrip(".")
    if not key:
        return None
    if key in MONTHS_FULL:
        return MONTHS_FULL[key]
    if key in MONTHS_ABBR:
        return MONTHS_ABBR[key]
    if len(key) >= 3 and key[:3] in MONTHS_ABBR:
        return MONTHS_ABBR[key[:3]]
    return None


def parse_card_date_text(text: str) -> str | None:
    """
    Parsea fechas tipo:
    - Wednesday, Jun 3, 2026
    - Monday, May 25, 2026
    - May 23 2026
    """
    text = (text or "").strip()
    if not text:
        return None
    m = re.search(
        r"(?:\w+day,?\s+)?(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})",
        text,
        re.I,
    )
    if not m:
        m = re.search(r"(\w+)\s+(\d{1,2})\s+(\d{4})", text, re.I)
    if not m:
        return None
    month, day, year = m.groups()
    mo = month_to_num(month)
    if not mo:
        return None
    return f"{year}-{mo}-{int(day):02d}"


def recent_cutoff(days: int = 60) -> str:
    return (datetime.now() - timedelta(days=max(1, days))).strftime("%Y-%m-%d")


def filter_recent_rows(rows: list[dict], *, days: int = 60, date_key: str = "draw_date") -> list[dict]:
    cutoff = recent_cutoff(days)
    return [r for r in rows if (r.get(date_key) or "") >= cutoff]


def max_draw_date_in_rows(rows: list[dict], date_key: str = "draw_date") -> str | None:
    dates = [r.get(date_key) for r in rows if r.get(date_key)]
    return max(dates) if dates else None
