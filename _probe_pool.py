import re
import cloudscraper
from services.leidsa_config import BROWSER_HEADERS

for path, did in [
    ("Loto-Pool", "2_9219"),
    ("LotoPool", "2_9219"),
    ("Loto Pool", "2_9219"),
    ("QuinielaPale", "5_10219"),
    ("SuperPale", "6_10216"),
]:
    url = f"https://www.leidsa.com/results/Leidsa/{path}/{did}"
    html = cloudscraper.create_scraper().get(url, headers=BROWSER_HEADERS, timeout=25).text
    print(path, "status len", len(html), "drawResults", "drawResults" in html)
    if "drawResults" in html:
        start = html.find("drawResults")
        chunk = html[start : start + 2000]
        print("  chunk", chunk[:400])
    entries = re.findall(r'\\"gameFamilyName\\":\\"([^\\"]+)\\"', html)
    from collections import Counter
    print("  families", Counter(entries).most_common(8))
