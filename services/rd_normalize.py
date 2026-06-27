"""Normalización de nombres RD — lotería, sorteo y horario unificados."""
from __future__ import annotations

import re
import unicodedata

from lottery_schedules import get_schedule_slot, slot_draw_name, time_12h_to_24h
from services.lottery_normalize import find_lottery_in_list, normalize_lottery_name

# alias entrada → (lotería canónica, draw_name interno, horario 12h opcional)
_RD_ALIASES: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"suerte\s*dom.*12:30|la\s*suerte\s*12", re.I), "Suerte Dominicana", "tarde", "12:30 PM"),
    (re.compile(r"suerte\s*dom.*6:00|la\s*suerte\s*6", re.I), "Suerte Dominicana", "noche", "6:00 PM"),
    (re.compile(r"suerte\s*dom", re.I), "Suerte Dominicana", "tarde", "12:30 PM"),
    (re.compile(r"anguil+l?a.*10|anguil+l?a.*mañana|morning", re.I), "Anguila", "mañana", "10:00 AM"),
    (re.compile(r"anguil+l?a.*1:00|anguil+l?a.*tarde(?!\s*6)", re.I), "Anguila", "tarde", "1:00 PM"),
    (re.compile(r"anguil+l?a.*6:00|evening", re.I), "Anguila", "tardía", "6:00 PM"),
    (re.compile(r"anguil+l?a.*9:00|anguil+l?a.*noche", re.I), "Anguila", "noche", "9:00 PM"),
    (re.compile(r"anguil+l?a", re.I), "Anguila", "mañana", "10:00 AM"),
    (re.compile(r"nacional.*noche|noche.*nacional", re.I), "Lotería Nacional", "noche", "9:00 PM"),
    (re.compile(r"quiniela\s*nacional|nacional.*2:30|gana\s*m[aá]s", re.I), "Lotería Nacional", "tarde", "2:30 PM"),
    (re.compile(r"nacional.*6|juega.*pega", re.I), "Lotería Nacional", "tardía", "6:00 PM"),
    (re.compile(r"nacional", re.I), "Lotería Nacional", "tarde", "2:30 PM"),
    (re.compile(r"loteka.*7|mega.*lotto.*loteka", re.I), "Loteka", "noche", "7:55 PM"),
    (re.compile(r"loteka", re.I), "Loteka", "tarde", "12:55 PM"),
    (re.compile(r"lotedom|lote\s*dom", re.I), "Lotedom", "tarde", "12:00 PM"),
    (re.compile(r"quiniela\s*real|loto\s*real|\breal\b", re.I), "Lotería Real", "tarde", "12:55 PM"),
    (re.compile(r"primera.*noche", re.I), "La Primera", "noche", "7:00 PM"),
    (re.compile(r"primera", re.I), "La Primera", "mañana", "12:00 PM"),
    (re.compile(r"king.*noche", re.I), "King Lottery", "noche", "7:30 PM"),
    (re.compile(r"king", re.I), "King Lottery", "tarde", "12:30 PM"),
    (re.compile(r"leidsa.*quiniela|quiniela.*leidsa|quiniela\s*pale", re.I), "Leidsa", "noche", "3:55 PM"),
    (re.compile(r"loto\s*pool|super\s*pale|pega\s*3|kino", re.I), "", "", ""),  # no mezclar con quiniela
    (re.compile(r"leidsa", re.I), "Leidsa", "noche", "3:55 PM"),
]

_LEIDSA_GAME_BLOCK = re.compile(
    r"loto\s*pool|super\s*kino|pega\s*3|mega\s*chances|super\s*pale",
    re.I,
)


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFD", (text or "").strip())
    return "".join(c for c in t if unicodedata.category(c) != "Mn").casefold()


def valid_quiniela_numbers(nums: list) -> bool:
    if len(nums) != 3:
        return False
    for raw in nums:
        try:
            n = int(str(raw).lstrip("0") or "0")
        except ValueError:
            return False
        if n < 0 or n > 99:
            return False
    return True


def format_quiniela(nums: list) -> list[str]:
    return [str(int(str(n).lstrip("0") or "0")).zfill(2) for n in nums]


def normalize_rd_row(row: dict) -> dict | None:
    """Normaliza fila cruda de cualquier fuente RD."""
    title = " ".join(
        filter(None, [row.get("lottery_name"), row.get("game_title"), row.get("title")])
    )
    if _LEIDSA_GAME_BLOCK.search(title) and "quiniela" not in title.lower():
        return None

    lot_name = (row.get("lottery_name") or "").strip()
    draw_name = (row.get("draw_name") or "").strip()
    time_hint = (row.get("draw_time") or row.get("time_display") or "").strip()
    blob = f"{title} {lot_name} {draw_name} {time_hint}".strip()

    canonical = ""
    resolved_draw = draw_name or "tarde"
    resolved_time = time_hint

    for pat, lot, dn, tm in _RD_ALIASES:
        if pat.search(blob):
            if not lot:
                return None
            canonical = lot
            if dn:
                resolved_draw = dn
            if tm:
                resolved_time = tm
            break

    if not canonical:
        key = normalize_lottery_name(lot_name or title)
        from services.rd_lottery_config import LOTTERY_CONFIG

        for cfg_name, cfg in LOTTERY_CONFIG.items():
            if normalize_lottery_name(cfg_name) == key:
                canonical = cfg["db_names"][0]
                break
        if not canonical and lot_name:
            canonical = lot_name

    if not canonical:
        return None

    slot = get_schedule_slot(canonical, resolved_draw)
    if slot:
        resolved_draw = slot_draw_name(slot)
        if not resolved_time or ":" not in str(resolved_time):
            resolved_time = slot.get("time", resolved_time)

    draw_time_24 = time_12h_to_24h(resolved_time) if resolved_time and "M" in str(resolved_time).upper() else (
        time_12h_to_24h(resolved_time) if resolved_time and len(str(resolved_time)) <= 5 else resolved_time
    )

    nums = row.get("numbers") or []
    if isinstance(nums, str):
        nums = re.findall(r"\d{1,2}", nums)
    nums = format_quiniela(nums)
    if not valid_quiniela_numbers(nums):
        return None

    dd = (row.get("draw_date") or "").strip()
    if not dd or len(dd) < 10:
        return None

    return {
        **row,
        "lottery_name": canonical,
        "draw_name": resolved_draw,
        "draw_time": draw_time_24 or row.get("draw_time", ""),
        "draw_date": dd[:10],
        "numbers": nums,
        "primera": nums[0],
        "segunda": nums[1],
        "tercera": nums[2],
        "pais": "RD",
    }


def resolve_rd_lottery_id(lottery_name: str, lotteries: list | None = None):
    from models import get_all_lotteries

    lots = lotteries or get_all_lotteries()
    return find_lottery_in_list(lots, lottery_name, country="RD")
