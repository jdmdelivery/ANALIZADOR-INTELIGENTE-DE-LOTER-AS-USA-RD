import re
from collections import Counter
import cloudscraper
from services.leidsa_config import BROWSER_HEADERS

html = cloudscraper.create_scraper().get(
    "https://www.leidsa.com/results/Leidsa/KinoTV/1_2061", headers=BROWSER_HEADERS, timeout=25
).text

entries = re.findall(
    r'\{\\"gameDrawId\\":\\"([^\\"]+)\\",\\"gameFamilyName\\":\\"([^\\"]+)\\"[^}]*?'
    r'\\"drawTime\\":\\"([^\\"]+)\\"[^}]*?'
    r'\\"drawnValues\\":\[\{\\"drawnValues\\":\[([^\]]*)\]\}',
    html,
)
print("total", len(entries))
print(Counter(e[1] for e in entries))
print("sample kino", [e for e in entries if "Kino" in e[1]][:2])
