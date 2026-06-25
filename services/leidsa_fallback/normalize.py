"""Normalización de filas LEIDSA desde parsers externos."""
from __future__ import annotations

import re
from datetime import datetime

from services.leidsa_config import DRAW_NAME_SPECIAL, LEIDSA_GAMES, NAME_ALIASES

MONTHS_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

SOURCE_LABELS = {
    "leidsa_official": "LEIDSA.com",
    "enloteria": "EnLoteria",
    "loteriasdominicanas_us": "LoteriasDominicanas.us",
    "yelu": "Yelu.do",
    "nacionalloteria": "NacionalLoteria.com",
}

LDUS_CLASS_MAP = {
    "quiniela-pale": "leidsa_quiniela_pale",
    "pega-3-mas": "leidsa_pega3",
    "loto-pool-leidsa": "leidsa_loto_pool",
    "super-kino-tv": "leidsa_super_kino_tv",
    "loto-mas": "leidsa_loto_mas",
    "super-pale": "leidsa_super_pale",
}


def slug_from_text(text: str) -> str | None:
    raw = re.sub(r"[^a-z0-9áéíóúñ]+", " ", (text or "").strip().lower())
    raw = (
        raw.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )
    if raw in NAME_ALIASES:
        return NAME_ALIASES[raw]
    patterns = [
        (r"quiniela\s*pale|pale", "leidsa_quiniela_pale"),
        (r"pega\s*3", "leidsa_pega3"),
        (r"loto\s*pool", "leidsa_loto_pool"),
        (r"super\s*kino|kinotv|kino\s*tv", "leidsa_super_kino_tv"),
        (r"super\s*pale", "leidsa_super_pale"),
        (r"loto\s*mas|super\s*mas", "leidsa_loto_mas"),
    ]
    for pat, slug in patterns:
        if re.search(pat, raw):
            return slug
    compact = raw.replace(" ", "_")
    if compact in LEIDSA_GAMES:
        return compact
    return None


def parse_spanish_date(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(
        r"(\d{1,2})\s+de\s+(\w+)\s*,?\s*(\d{4})",
        text,
        re.I,
    )
    if m:
        day, month_name, year = m.groups()
        mo = MONTHS_ES.get(month_name.lower())
        if mo:
            return f"{year}-{mo:02d}-{int(day):02d}"
    return None


def draw_from_time_12h(time_12h: str, slug: str) -> str:
    t = (time_12h or "").strip().upper()
    if t in DRAW_NAME_SPECIAL:
        return DRAW_NAME_SPECIAL[t]
    m = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)", t)
    if m:
        h = int(m.group(1))
        mer = m.group(3)
        if mer == "PM" and h != 12:
            h += 12
        elif mer == "AM" and h == 12:
            h = 0
        if h < 15:
            return "tarde"
        return "noche"
    cfg = LEIDSA_GAMES.get(slug, {})
    draws = cfg.get("draws") or []
    if len(draws) == 1:
        return draws[0]["draw_name"]
    return draws[-1]["draw_name"] if draws else "noche"


def _valid_numbers(nums: list) -> bool:
    if not nums:
        return False
    if len(nums) > 25:
        return False
    return all(isinstance(n, int) and 0 <= n <= 99 for n in nums)


def build_row(
    slug: str,
    *,
    draw: str,
    fecha_rd: str,
    numeros: list[int],
    fuente: str,
    bonus: list[int] | None = None,
    draw_time: str = "",
) -> dict | None:
    if slug not in LEIDSA_GAMES or not _valid_numbers(numeros):
        return None
    cfg = LEIDSA_GAMES[slug]
    slot = next((d for d in cfg["draws"] if d["draw_name"] == draw), cfg["draws"][0])
    row = {
        "lottery": slug,
        "lottery_name": cfg["lottery_name"],
        "draw": draw,
        "fecha_rd": fecha_rd,
        "numeros": numeros,
        "draw_time": draw_time or slot.get("time_24h", ""),
        "time_display": slot.get("time", ""),
        "fuente": fuente,
        "estado": "publicado",
    }
    if bonus:
        row["bonus"] = bonus
    return row


def pick_latest_per_game(rows: list[dict]) -> list[dict]:
    """Una fila por (lottery, draw): la de fecha más reciente."""
    best: dict[tuple, dict] = {}
    for row in rows:
        if not row.get("lottery") or not row.get("numeros"):
            continue
        key = (row["lottery"], row.get("draw") or "noche")
        prev = best.get(key)
        if not prev or (row.get("fecha_rd", "") > prev.get("fecha_rd", "")):
            best[key] = row
    return list(best.values())


def latest_date_in_rows(rows: list[dict]) -> str | None:
    dates = [r.get("fecha_rd") for r in rows if r.get("fecha_rd")]
    return max(dates) if dates else None
