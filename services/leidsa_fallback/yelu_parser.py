"""Parser Yelu.do — quiniela palé."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from services.leidsa_fallback.normalize import build_row, parse_spanish_date

SOURCE_KEY = "yelu"
SOURCE_LABEL = "Yelu.do"
DEFAULT_URL = "https://www.yelu.do/leidsa/results/quiniela-pale"


def parse_yelu_html(html: str, source_url: str = DEFAULT_URL) -> list[dict]:
    soup = BeautifulSoup(html or "", "lxml")
    rows: list[dict] = []
    slug = "leidsa_quiniela_pale"

    for row_el in soup.select("table tr, .lotto-result, .result-row"):
        txt = row_el.get_text(" ", strip=True)
        if not re.search(r"quiniela|pale", txt, re.I):
            continue
        nums = re.findall(r"\b(\d{1,2})\b", txt)
        if len(nums) < 3:
            continue
        nums_int = [int(n) for n in nums[-3:]]
        fecha_rd = parse_spanish_date(txt)
        if not fecha_rd:
            continue
        row = build_row(
            slug,
            draw="noche",
            fecha_rd=fecha_rd,
            numeros=nums_int,
            fuente=SOURCE_LABEL,
        )
        if row:
            row["source_url"] = source_url
            rows.append(row)

    return rows
