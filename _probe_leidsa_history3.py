"""Count all historical draws parseable from one Loto page."""
import re

import cloudscraper

from services.leidsa_config import BROWSER_HEADERS
from services.leidsa_service import _extract_rows_from_json_tree, _parse_escaped_json_blocks

session = cloudscraper.create_scraper()
url = "https://www.leidsa.com/results/Leidsa/Loto/1_2061"
html = session.get(url, headers=BROWSER_HEADERS, timeout=25).text

draw_ids = re.findall(r'\\"drawId\\":\\"(1_\d+)\\"', html)
print("drawId refs:", len(draw_ids), "unique", len(set(draw_ids)))

# find all drawnValues arrays near drawId 1_
chunks = []
for m in re.finditer(r'\\"drawId\\":\\"(1_\d+)\\"', html):
    start = m.start()
    chunk = html[start : start + 1500]
    if "drawnValues" in chunk:
        dv = re.search(r'\\"drawnValues\\":\[([^\]]*)\]', chunk)
        ts = re.search(r'\\"drawTimestamp\\":\\"([^\\"]+)"', chunk)
        if dv and ts:
            chunks.append((m.group(1), dv.group(1), ts.group(1)))

print("drawId+values+ts:", len(chunks))
print("sample first 3:", chunks[:3])
print("sample last 3:", chunks[-3:])

rows = _parse_escaped_json_blocks(html)
loto_rows = [r for r in rows if "loto" in r.get("lottery", "")]
print("escaped parser loto rows:", len(loto_rows), "total rows", len(rows))
