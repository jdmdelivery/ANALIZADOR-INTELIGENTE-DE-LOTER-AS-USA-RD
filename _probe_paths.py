import re
from collections import Counter
import cloudscraper
from services.leidsa_config import BROWSER_HEADERS

def test(path, did):
    url = f"https://www.leidsa.com/results/Leidsa/{path}/{did}"
    html = cloudscraper.create_scraper().get(url, headers=BROWSER_HEADERS, timeout=25).text
    # Only parse drawResults array (after drawResult key with gameDrawId)
    idx = html.find('drawResults\\":[{')
    if idx < 0:
        idx = html.find('drawResults\\": [{')
    if idx < 0:
        return path, 0, {}
    section = html[idx : idx + 800000]
    entries = re.findall(
        r'\{\\"gameDrawId\\":\\"([^\\"]+)\\",\\"gameFamilyName\\":\\"([^\\"]+)\\"',
        section,
    )
    return path, len(entries), dict(Counter(e[1] for e in entries))

ids = {
    "Loto": "1_2062",
    "KinoTV": "3_6219",
    "Loto Pool": "2_9219",
    "Quiniela Pale": "5_10219",
    "Pega3Mas": "4_5219",
    "Super Pale": "6_10216",
}
for path, did in ids.items():
    print(test(path, did))
