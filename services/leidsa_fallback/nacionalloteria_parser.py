"""Parser NacionalLoteria.com — quiniela LEIDSA."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from services.leidsa_fallback.normalize import build_row

SOURCE_KEY = "nacionalloteria"
SOURCE_LABEL = "NacionalLoteria.com"
DEFAULT_URL = "https://www.nacionalloteria.com/republica-dominicana/quiniela-leidsa.php"


def parse_nacionalloteria_html(html: str, source_url: str = DEFAULT_URL) -> list[dict]:
    soup = BeautifulSoup(html or "", "lxml")
    rows: list[dict] = []
    slug = "leidsa_quiniela_pale"

    section = soup.select_one("#listaResultados") or soup
    for h2 in section.find_all("h2"):
        time_el = h2.find("time")
        fecha_rd = None
        if time_el and time_el.get("datetime"):
            fecha_rd = time_el["datetime"][:10]
        if not fecha_rd:
            fecha_rd = _fecha_from_h2(h2.get_text(" ", strip=True))
        if not fecha_rd:
            continue

        nums_div = h2.find_next("div", class_=re.compile(r"numeros"))
        if not nums_div:
            continue
        spans = nums_div.select("span.label-numero")
        if len(spans) < 3:
            continue
        nums_int = []
        for sp in spans[:3]:
            try:
                nums_int.append(int(sp.get_text(strip=True)))
            except ValueError:
                nums_int = []
                break
        if len(nums_int) != 3:
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
        break

    return rows


def _fecha_from_h2(text: str) -> str | None:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    from services.leidsa_fallback.normalize import parse_spanish_date

    return parse_spanish_date(text)
