"""Parser loteriasdominicanas.us — página /leidsa."""
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from services.leidsa_fallback.normalize import LDUS_CLASS_MAP, build_row

SOURCE_KEY = "loteriasdominicanas_us"
SOURCE_LABEL = "LoteriasDominicanas.us"
DEFAULT_URL = "https://www.loteriasdominicanas.us/"


def parse_loteriasdominicanas_us_html(html: str, source_url: str = DEFAULT_URL) -> list[dict]:
    soup = BeautifulSoup(html or "", "lxml")
    rows: list[dict] = []
    today = datetime.now().strftime("%Y-%m-%d")

    for card in soup.select("div.card"):
        classes = card.get("class") or []
        slug = None
        for cls in classes:
            if cls in LDUS_CLASS_MAP:
                slug = LDUS_CLASS_MAP[cls]
                break
        if not slug:
            continue

        title_el = card.select_one(".title")
        title = title_el.get_text(strip=True) if title_el else ""
        num_els = card.select("ul.r li")
        if not num_els:
            continue
        nums = [int(re.sub(r"\D", "", n.get_text(strip=True)) or "0") for n in num_els]
        if not nums:
            continue

        bonus = None
        if slug == "leidsa_loto_mas" and len(nums) >= 8:
            bonus = nums[6:8]
            nums = nums[:6]
        elif slug == "leidsa_pega3":
            nums = nums[:3]
        elif slug == "leidsa_quiniela_pale":
            nums = nums[:3]
        elif slug == "leidsa_loto_pool":
            nums = nums[:5]

        cfg_draws = __import__(
            "services.leidsa_config", fromlist=["LEIDSA_GAMES"]
        ).LEIDSA_GAMES.get(slug, {}).get("draws") or []
        draw = cfg_draws[-1]["draw_name"] if cfg_draws else "noche"

        row = build_row(
            slug,
            draw=draw,
            fecha_rd=today,
            numeros=nums,
            fuente=SOURCE_LABEL,
            bonus=bonus,
        )
        if row:
            row["source_url"] = source_url
            if title:
                row["title"] = title
            rows.append(row)

    return rows
