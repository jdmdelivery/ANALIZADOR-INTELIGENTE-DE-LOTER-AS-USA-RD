import re
import cloudscraper
from services.leidsa_config import BROWSER_HEADERS

session = cloudscraper.create_scraper()
games = [
    ("Loto", "https://www.leidsa.com/results/Leidsa/Loto/1_2061"),
    ("LotoMas", "https://www.leidsa.com/results/Leidsa/LotoMas/1_2062"),
    ("SuperMas", "https://www.leidsa.com/results/Leidsa/SuperMas/1_2063"),
    ("SuperKino", "https://www.leidsa.com/results/Leidsa/SuperKino/1_2064"),
    ("Quiniela", "https://www.leidsa.com/results/Leidsa/Quiniela/1_2065"),
    ("Pega3", "https://www.leidsa.com/results/Leidsa/Pega3/1_2066"),
    ("LotoPool", "https://www.leidsa.com/results/Leidsa/LotoPool/1_2067"),
    ("SuperPale", "https://www.leidsa.com/results/Leidsa/SuperPale/1_2068"),
    ("QuinielaPale", "https://www.leidsa.com/results/Leidsa/QuinielaPale/1_2000"),
    ("Pega3Mas", "https://www.leidsa.com/results/Leidsa/Pega3Mas/1_2000"),
]

for name, url in games:
    try:
        r = session.get(url, headers=BROWSER_HEADERS, timeout=20)
        n = len(re.findall(
            r'\{\\"gameDrawId\\":\\"[^\\"]+\\",\\"gameFamilyName\\":\\"[^\\"]+\\"[^}]*?'
            r'\\"drawTime\\":\\"[^\\"]+\\"[^}]*?\\"drawnValues\\":\[\{\\"drawnValues\\":\[',
            r.text,
        ))
        fam = re.search(r'\\"gameFamilyName\\":\\"([^\\"]+)\\"', r.text[r.text.find("drawResults") :])
        print(name, r.status_code, "entries", n, "family", fam.group(1) if fam else "?")
    except Exception as e:
        print(name, "ERR", e)
