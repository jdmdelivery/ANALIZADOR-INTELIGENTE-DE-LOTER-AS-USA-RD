"""Loterías RD agregadas después — requieren import estilo bulk (como import_conectate_rd)."""
from __future__ import annotations

# Tipos slug en DB (seed_rd_conectate_lotteries)
NEW_RD_LOTTERY_TYPES = frozenset({
    "rd_florida",
    "rd_king_lottery",
    "rd_new_york",
})

NEW_RD_LOTTERY_NAMES = frozenset({
    "Florida",
    "King Lottery",
    "New York",
})


def is_new_rd_lottery(lot: dict | None) -> bool:
    if not lot or lot.get("country") != "RD":
        return False
    if (lot.get("type") or "") in NEW_RD_LOTTERY_TYPES:
        return True
    return (lot.get("name") or "") in NEW_RD_LOTTERY_NAMES


def list_new_rd_lotteries(active_only: bool = True) -> list[dict]:
    from models import get_all_lotteries

    return [
        lot for lot in get_all_lotteries(active_only=active_only)
        if is_new_rd_lottery(lot)
    ]
