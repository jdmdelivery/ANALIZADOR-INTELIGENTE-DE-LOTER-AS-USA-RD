import re
import cloudscraper
from services.leidsa_config import BROWSER_HEADERS

def count_entries(url):
    html = cloudscraper.create_scraper().get(url, headers=BROWSER_HEADERS, timeout=25).text
    entries = re.findall(
        r'\{\\"gameDrawId\\":\\"([^\\"]+)\\",\\"gameFamilyName\\":\\"([^\\"]+)\\"',
        html[html.find("drawResults") : html.find("drawResults") + 600000] if "drawResults" in html else html,
    )
    from collections import Counter
    return Counter(e[1] for e in entries), len(entries)

tests = [
    "https://www.leidsa.com/results/Leidsa/Loto/1_2062",
    "https://www.leidsa.com/results/Leidsa/LotoMas/1_2062",
    "https://www.leidsa.com/results/Leidsa/Loto-Mas/1_2062",
    "https://www.leidsa.com/results/Leidsa/SuperMas/1_2062",
    "https://www.leidsa.com/results/Leidsa/Super-Mas/1_2062",
    "https://www.leidsa.com/results/Leidsa/Loto-Pool/2_9219",
    "https://www.leidsa.com/results/Leidsa/LotoPool/2_9219",
    "https://www.leidsa.com/results/Leidsa/QuinielaPale/5_10219",
    "https://www.leidsa.com/results/Leidsa/Quiniela-Pale/5_10219",
    "https://www.leidsa.com/results/Leidsa/SuperPale/6_10216",
    "https://www.leidsa.com/results/Leidsa/Pega3Mas/4_5219",
]
for u in tests:
    c, n = count_entries(u)
    print(u.split("/")[-2], n, dict(c))
