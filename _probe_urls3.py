import re
import cloudscraper
from services.leidsa_config import BROWSER_HEADERS

session = cloudscraper.create_scraper()

def analyze(url, label):
    html = session.get(url, headers=BROWSER_HEADERS, timeout=25).text
    print("===", label, url, "len", len(html))
    if "Just a moment" in html or len(html) < 5000:
        print("  blocked?")
        return
    # all gameDrawId prefixes
    ids = re.findall(r'\\"gameDrawId\\":\\"([^\\"]+)\\"', html)
    prefixes = sorted(set(i.split("_")[0] for i in ids if "_" in i))
    print("  gameDrawId count", len(ids), "unique", len(set(ids)), "prefixes", prefixes[:10])
    families = sorted(set(re.findall(r'\\"gameFamilyName\\":\\"([^\\"]+)\\"', html)))
    print("  families", families[:15])
    n = len(re.findall(
        r'\\"drawTime\\":\\"[^\\"]+\\"[^}]*?\\"drawnValues\\":\[\{\\"drawnValues\\":\[',
        html,
    ))
    print("  draw entries regex", n)
    # params in RSC
    m = re.search(r'gameFamilyName\\":\\"([^\\"]+)\\",\\"drawId\\":\\"([^\\"]+)\\"', html)
    if m:
        print("  page params", m.group(1), m.group(2))

# Try discover LotoMas from Loto page - ticketName LotoMas might share
analyze("https://www.leidsa.com/results/Leidsa/Loto/1_2061", "Loto")

# Try alternate paths from site_slug in config
paths = [
    "https://www.leidsa.com/results/Leidsa/LotoMas/1_2061",
    "https://www.leidsa.com/results/Leidsa/Loto-Mas/1_2061",
    "https://www.leidsa.com/results/Leidsa/Super-Mas/1_2061",
    "https://www.leidsa.com/results/Leidsa/KinoTV/1_2061",
    "https://www.leidsa.com/results/Leidsa/Super-Kino-TV/1_2061",
    "https://www.leidsa.com/results/Leidsa/Quiniela-Pale/1_2061",
    "https://www.leidsa.com/results/Leidsa/QuinielaPale/1_2061",
    "https://www.leidsa.com/results/Leidsa/Loto-Pool/1_2061",
    "https://www.leidsa.com/results/Leidsa/LotoPool/1_2061",
    "https://www.leidsa.com/results/Leidsa/Super-Pale/1_2061",
    "https://www.leidsa.com/results/Leidsa/Pega3Mas/1_2061",
    "https://www.leidsa.com/results/Leidsa/Pega-3-Mas/1_2061",
]
for u in paths:
    analyze(u, u.split("/")[-2])
