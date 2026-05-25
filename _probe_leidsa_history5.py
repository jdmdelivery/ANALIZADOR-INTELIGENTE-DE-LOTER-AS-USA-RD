import re
import cloudscraper
from services.leidsa_config import BROWSER_HEADERS

html = cloudscraper.create_scraper().get(
    "https://www.leidsa.com/results/Leidsa/Loto/1_2061", headers=BROWSER_HEADERS, timeout=25
).text

# Parse drawResults array entries
entries = re.findall(
    r'\{\\"gameDrawId\\":\\"(1_\d+)\\",\\"gameFamilyName\\":\\"([^\\"]+)\\"[^}]*?'
    r'\\"drawTime\\":\\"([^\\"]+)\\"[^}]*?'
    r'\\"drawnValues\\":\[\{\\"drawnValues\\":\[([^\]]*)\]\}',
    html,
)
print("drawResults entries (main):", len(entries))
if entries:
    print("first", entries[0])
    print("last", entries[-1])

# Also count gameDrawId in drawResults section only
start = html.find("drawResults")
if start >= 0:
    section = html[start : start + 500000]
    ids = re.findall(r'\\"gameDrawId\\":\\"(1_\d+)\\"', section)
    print("gameDrawIds in drawResults section:", len(ids), "unique", len(set(ids)))
