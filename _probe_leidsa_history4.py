import re
import cloudscraper
from services.leidsa_config import BROWSER_HEADERS

html = cloudscraper.create_scraper().get(
    "https://www.leidsa.com/results/Leidsa/Loto/1_2061", headers=BROWSER_HEADERS, timeout=25
).text

idx = html.find("drawnValues")
for n in range(5):
    if idx < 0:
        break
    print("---", n, "---")
    print(html[max(0, idx - 200) : idx + 350].replace("\n", " ")[:500])
    idx = html.find("drawnValues", idx + 1)

# Maybe draw id format without escape
print("1_2061 count", html.count("1_2061"))
# pattern: previousDrawDetails vs drawDetails
print("previousDrawDetails", html.count("previousDrawDetails"))
print("drawDetails", html.count("drawDetails"))
