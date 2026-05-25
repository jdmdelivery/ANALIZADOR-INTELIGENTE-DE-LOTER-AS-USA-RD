"""Deep probe for LEIDSA history in RSC/JSON."""
import json
import re

import requests

try:
    import cloudscraper
    session = cloudscraper.create_scraper()
except ImportError:
    session = requests.Session()

from services.leidsa_config import BROWSER_HEADERS

URL = "https://www.leidsa.com/results/Leidsa/Loto/1_2061"
r = session.get(URL, headers=BROWSER_HEADERS, timeout=25)
html = r.text

# draw ids like 1_2061
ids = sorted(set(re.findall(r"\b1_\d{3,5}\b", html)))
print("draw ids 1_*:", len(ids), ids[:15], "..." if len(ids) > 15 else "")

# Sorteo date patterns in HTML
sorteos = re.findall(r"Sorteo:\s*(\d{1,2}/\d{1,2}/\d{2,4}[^\"\\]{0,20})", html)
print("Sorteo labels:", len(sorteos), sorteos[:10])

# drawnValues blocks with timestamps
for m in re.finditer(
    r'\\"drawId\\":\\"([^\\"]+)\\"[^}]{0,400}?\\"drawnValues\\":\[([^\]]*)\][^}]{0,200}?\\"drawTimestamp\\":\\"([^\\"]+)"',
    html,
):
    print("ESC", m.group(1), m.group(2)[:40], m.group(3))

# unescaped
for m in re.finditer(
    r'"drawId"\s*:\s*"([^"]+)"[^}]{0,400}?"drawnValues"\s*:\s*\[([^\]]*)\][^}]{0,200}?"drawTimestamp"\s*:\s*"([^"]+)"',
    html,
    re.DOTALL,
):
    if m.group(1).startswith("1_"):
        print("UN", m.group(1), m.group(2)[:40], m.group(3))

# Loto-specific family
loto_chunks = [c for c in html.split('{\\"gameId\\":') if 'Loto\\"' in c[:200] or 'gameFamilyName\\":\\"Loto\\"' in c[:800]]
print("loto escaped chunks:", len(loto_chunks))

# API patterns for draw history
for pat in [
    r"https?://[^\"'\\s]+draw[^\"'\\s]*",
    r"https?://[^\"'\\s]+result[^\"'\\s]*",
    r"/results/Leidsa/Loto/[^\"'\\s]+",
]:
    found = sorted(set(re.findall(pat, html, re.I)))[:8]
    if found:
        print("pat", pat[:30], found)

# drawIds with drawnValues in same page
esc_ids = set(re.findall(r'\\"drawId\\":\\"(1_\d+)\\"', html))
print("drawIds escaped:", len(esc_ids))
with_vals = 0
for did in esc_ids:
    pat = '\\"drawId\\":\\"' + did + '\\"'
    idx = html.find(pat)
    if idx >= 0 and "drawnValues" in html[idx : idx + 1200]:
        with_vals += 1
print("drawIds with nearby drawnValues:", with_vals)

# fetch another draw page
r2 = session.get("https://www.leidsa.com/results/Leidsa/Loto/1_2060", headers=BROWSER_HEADERS, timeout=25)
h2 = r2.text
print("page 2060 status", r2.status_code, "len", len(h2))
m = re.search(r'\\"drawnValues\\":\[([^\]]*)\]', h2)
print("2060 nums", (m.group(1)[:80] if m else "none"))
ids2 = set(re.findall(r"\b1_\d{3,5}\b", h2))
print("ids on 2060 page", len(ids2))
print("drawnValues count on 2061:", html.count("drawnValues"))
print("drawnValues count on 2060:", h2.count("drawnValues"))

# find draw list structure in RSC
for key in ["drawList", "drawsList", "historical", "drawHistory", "availableDraws", "drawOptions"]:
    print(key, html.count(key))

# option-like dates 5/23/26
dates = re.findall(r"(\d{1,2}/\d{1,2}/\d{2,4}),\s*(\d{1,2}:\d{2}\s*[AP]M)", html)
print("date+time pairs:", len(dates), dates[:8])

# try internal API
for api in [
    "https://www.leidsa.com/api/results",
    "https://www.leidsa.com/api/draws",
]:
    try:
        resp = session.get(api, headers={**BROWSER_HEADERS, "Accept": "application/json"}, timeout=10)
        print(api, resp.status_code, resp.text[:120].replace("\n", " "))
    except Exception as e:
        print(api, e)
