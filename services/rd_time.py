"""Helpers de fecha/hora para República Dominicana."""
from __future__ import annotations

from datetime import date, datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

RD_TZ_NAME = "America/Santo_Domingo"


def rd_tz():
    if ZoneInfo:
        try:
            return ZoneInfo(RD_TZ_NAME)
        except Exception:
            pass
    return None


def now_rd() -> datetime:
    tz = rd_tz()
    return datetime.now(tz) if tz else datetime.now()


def today_rd() -> date:
    return now_rd().date()


def today_rd_iso() -> str:
    return today_rd().isoformat()
