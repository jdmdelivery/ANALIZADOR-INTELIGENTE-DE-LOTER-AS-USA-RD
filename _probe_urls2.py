import re
import cloudscraper
from services.leidsa_config import BROWSER_HEADERS

html = cloudscraper.create_scraper().get(
    "https://www.leidsa.com/", headers=BROWSER_HEADERS, timeout=25
).text

links = sorted(set(re.findall(r"/results/Leidsa/[A-Za-z0-9]+/[^\"\\]+", html)))
print("result links", len(links))
for L in links[:30]:
    print(L)

# per game family latest draw link
for game in ["LotoMas", "SuperMas", "KinoTV", "Quiniela", "LotoPool", "SuperPale", "Pega3"]:
    pat = f"/results/Leidsa/[^/]+/"
    m = re.search(rf"/results/Leidsa/[^\"]{{0,40}}{game}[^\"]*/(1_\d+)", html, re.I)
    if not m:
        m = re.search(rf"/results/Leidsa/([^/]+)/(1_\d+)", html)
    # find all paths containing game keyword
    paths = [x for x in links if game.lower() in x.lower()]
    print(game, "paths", paths[:3])
