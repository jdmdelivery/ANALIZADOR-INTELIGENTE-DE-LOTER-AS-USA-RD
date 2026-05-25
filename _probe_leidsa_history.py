"""Probe LEIDSA results page structure."""
import json
import os
import re

import requests
from bs4 import BeautifulSoup

try:
    import cloudscraper
    session = cloudscraper.create_scraper()
except ImportError:
    session = requests.Session()

from services.leidsa_config import BROWSER_HEADERS

URL = "https://www.leidsa.com/results/Leidsa/Loto/1_2061"
r = session.get(URL, headers=BROWSER_HEADERS, timeout=25)
print("status", r.status_code, "len", len(r.text))
html = r.text
os.makedirs("debug/leidsa", exist_ok=True)
with open("debug/leidsa/_probe_loto.html", "w", encoding="utf-8") as f:
    f.write(html)

soup = BeautifulSoup(html, "lxml")
for sel in soup.find_all("select"):
    opts = sel.find_all("option")
    print("SELECT", sel.get("id"), sel.get("name"), "opts", len(opts))
    for o in opts[:8]:
        print("  ", repr(o.get("value")), o.text.strip()[:70])

m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
if m:
    data = json.loads(m.group(1))
    print("NEXT top keys:", list(data.keys())[:10])
    blob = json.dumps(data)
    print("drawnValues in NEXT:", blob.count("drawnValues"))
    print("drawHistory in NEXT:", "drawHistory" in blob or "draws" in blob[:5000])

# escaped json blocks
blocks = html.split('{\\"gameId\\":')
print("escaped game blocks:", len(blocks) - 1)
for pat in ["drawHistory", "historicalDraws", "allDraws", "drawOptions"]:
    print(pat, html.count(pat))
