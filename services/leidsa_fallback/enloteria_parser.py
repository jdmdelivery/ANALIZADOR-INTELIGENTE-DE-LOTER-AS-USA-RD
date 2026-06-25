"""Parser EnLoteria — resultados-leidsa."""
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from services.leidsa_fallback.normalize import (
    build_row,
    draw_from_time_12h,
    parse_spanish_date,
)

SOURCE_KEY = "enloteria"
SOURCE_LABEL = "EnLoteria"
DEFAULT_URL = "https://enloteria.com/resultados-leidsa"


def parse_enloteria_html(html: str, source_url: str = DEFAULT_URL) -> list[dict]:
    soup = BeautifulSoup(html or "", "lxml")
    rows: list[dict] = []
    today = datetime.now().strftime("%Y-%m-%d")

    for card in soup.select(".result-card"):
        txt = card.get_text(" ", strip=True)
        if re.search(r"av[ií]same|pendiente|proxim", txt, re.I):
            continue
        if not re.search(r"leidsa", txt, re.I):
            continue

        nums = re.findall(r"\b(\d{2})\b", txt)
        if len(nums) < 3:
            continue
        nums_int = [int(n) for n in nums[-3:]]

        time_m = re.search(r"(\d{1,2}:\d{2}\s*(?:AM|PM))", txt, re.I)
        time_12h = time_m.group(1).strip().upper() if time_m else ""

        slug = "leidsa_quiniela_pale"
        draw = draw_from_time_12h(time_12h, slug)
        fecha_rd = parse_spanish_date(txt) or today

        row = build_row(
            slug,
            draw=draw,
            fecha_rd=fecha_rd,
            numeros=nums_int,
            fuente=SOURCE_LABEL,
        )
        if row:
            row["source_url"] = source_url
            rows.append(row)

    return rows
