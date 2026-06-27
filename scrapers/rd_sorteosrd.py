"""Scraper SorteosRD.com — quinielas RD."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from scrapers.rd_http import fetch_rd_url
from services.rd_normalize import normalize_rd_row

logger = logging.getLogger(__name__)

BASE = "https://www.sorteosrd.com"
LOG = "[RD SCRAPER]"


def _parse_sorteosrd_html(html: str, *, source_url: str, year_hint: str) -> list[dict]:
    rows: list[dict] = []
    if not html:
        return rows

    # Bloques tipo: Nacional / Anguila + fecha + 3 números
    blocks = re.split(r"<(?:div|section|article)[^>]*>", html, flags=re.I)
    date_pat = re.compile(
        r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})|"
        r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})",
        re.I,
    )
    num_pat = re.compile(r"\b(\d{1,2})\b")

    for block in blocks:
        title_m = re.search(
            r"(nacional|anguil+a|loteka|real|primera|suerte|king|leidsa|lotedom)",
            block,
            re.I,
        )
        if not title_m:
            continue
        dm = date_pat.search(block)
        if not dm:
            continue
        if dm.group(1):
            d, m, y = dm.group(1), dm.group(2), dm.group(3)
            if len(y) == 2:
                y = "20" + y
            draw_date = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
        else:
            months = {
                "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
                "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
                "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
            }
            mo = months.get((dm.group(5) or "").lower(), "01")
            draw_date = f"{dm.group(6)}-{mo}-{int(dm.group(4)):02d}"

        nums = num_pat.findall(block)
        # Filtrar fechas pequeñas
        candidates = [n for n in nums if 0 <= int(n) <= 99]
        if len(candidates) < 3:
            continue
        pick = candidates[-3:]
        rows.append({
            "lottery_name": title_m.group(1),
            "draw_name": "tarde",
            "draw_date": draw_date,
            "numbers": pick,
            "source_url": source_url,
            "title": title_m.group(1),
        })
    return rows


def import_sorteosrd(lottery_name: str | None = None, days: int = 30, **_) -> dict:
    days = max(1, min(int(days or 30), 365))
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    paths = ["/", "/resultados", "/quinielas"]
    all_rows: list[dict] = []
    errors: list[str] = []
    year_hint = datetime.now().strftime("%Y")

    for path in paths:
        url = f"{BASE}{path}"
        resp = fetch_rd_url(url, source="sorteosrd", timeout=15)
        if not resp.get("ok"):
            errors.append(resp.get("error") or f"HTTP {resp.get('status_code')}")
            continue
        html = resp.get("text") or ""
        parsed = _parse_sorteosrd_html(html, source_url=url, year_hint=year_hint)
        for row in parsed:
            nr = normalize_rd_row(row)
            if not nr or nr["draw_date"] < cutoff:
                continue
            if lottery_name and nr["lottery_name"].lower() != lottery_name.lower():
                continue
            all_rows.append(nr)

    if not all_rows:
        return {
            "ok": False,
            "rows": [],
            "imported": 0,
            "updated": 0,
            "errors": errors[:5] or ["sin filas en SorteosRD"],
            "fuente_label": "SorteosRD.com",
            "parser": "sorteosrd-v1",
        }

    from services.rd_resultados_service import persist_rd_rows

    save = persist_rd_rows(all_rows, fuente="sorteosrd", days=days, lottery_name=lottery_name)
    return {
        **save,
        "rows": all_rows,
        "rows_found": len(all_rows),
        "fuente_label": "SorteosRD.com",
        "parser": "sorteosrd-v1",
        "errors": errors[:5],
    }
