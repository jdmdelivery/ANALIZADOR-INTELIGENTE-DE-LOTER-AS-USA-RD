import re
import cloudscraper
from services.leidsa_config import BROWSER_HEADERS

html = cloudscraper.create_scraper().get(
    "https://www.leidsa.com/", headers=BROWSER_HEADERS, timeout=25
).text

# previousDrawDetails per game on home
for block in html.split('{\\"gameId\\":')[1:]:
    if '\\"gameProvider\\":\\"Leidsa\\"' not in block[:500]:
        continue
    fam = re.search(r'\\"gameFamilyName\\":\\"([^\\"]+)', block)
    slug = re.search(r'\\"slug\\":\\"([^\\"]+)', block)
    did = re.search(r'\\"drawId\\":\\"([^\\"]+)', block)
    if fam:
        print(fam.group(1), "slug", slug.group(1) if slug else "", "drawId", did.group(1) if did else "")
