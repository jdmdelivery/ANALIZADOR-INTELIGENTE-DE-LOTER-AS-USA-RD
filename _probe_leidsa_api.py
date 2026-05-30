import re
import json
import requests

try:
    import cloudscraper
    s = cloudscraper.create_scraper()
    r = s.get("https://www.leidsa.com/", timeout=20)
except Exception:
    r = requests.get("https://www.leidsa.com/", timeout=20, headers={"User-Agent": "Mozilla/5.0"})

print("status", r.status_code, "len", len(r.text))
text = r.text

# endpoints
patterns = [
    r'https?://[a-zA-Z0-9._/-]+(?:api|graphql|result|sorteo|draw|lottery|game)[a-zA-Z0-9._/-]*',
    r'"/[a-zA-Z0-9._/-]*(?:api|result|sorteo)[^"]*"',
    r"'/[a-zA-Z0-9._/-]*(?:api|result|sorteo)[^']*'",
]
found = set()
for p in patterns:
    for m in re.finditer(p, text, re.I):
        found.add(m.group(0).strip('"\''))

for u in sorted(found)[:40]:
    print("URL", u[:120])

# next chunks
if "__NEXT_DATA__" in text:
    print("HAS __NEXT_DATA__")
if 'gameProvider\\":\\"Leidsa' in text or 'gameProvider":"Leidsa' in text:
    print("HAS Leidsa games JSON")

# try common API paths
bases = ["https://www.leidsa.com", "https://leidsa.com", "https://api.leidsa.com"]
paths = ["/api/results", "/api/resultados", "/api/draws", "/api/games", "/api/v1/results"]
for b in bases:
    for p in paths:
        try:
            rr = s.get(b + p, timeout=8)
            if rr.status_code == 200 and len(rr.text) > 50:
                print("HIT", b+p, rr.status_code, rr.text[:200])
        except Exception:
            pass
