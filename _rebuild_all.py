import json
import re
import os

TRANSCRIPT = r"C:\Users\thene\.cursor\projects\c-Users-thene-OneDrive-Desktop-analizador-inteligente-de-loteria-USA-Y-RD\agent-transcripts\6a22187c-2490-4b20-8250-5aedebc112ff\6a22187c-2490-4b20-8250-5aedebc112ff.jsonl"
BASE = r"c:\Users\thene\OneDrive\Desktop\analizador inteligente de loteria USA Y RD\_reconstructed"

FILES = [
    "templates/index.html", "templates/base.html", "static/css/style.css",
    "analysis.py", "importers.py", "services/resultados/illinois_scraper.py",
]


def clean(s):
    return re.sub(r"</?motion>", "", s or "")


def rebuild(target_suffix):
    ops = []
    with open(TRANSCRIPT, encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            for item in obj.get("message", {}).get("content", []) or []:
                if not isinstance(item, dict) or item.get("name") not in ("Write", "StrReplace"):
                    continue
                p = item.get("input", {}).get("path", "").replace("\\", "/")
                if p.endswith(target_suffix):
                    ops.append((item["name"], item["input"]))

    content = ""
    failed = 0
    for name, inp in ops:
        if name == "Write":
            content = clean(inp.get("contents", ""))
        else:
            old = clean(inp.get("old_string", ""))
            new = clean(inp.get("new_string", ""))
            if not old:
                continue
            if "^(?!" in new:
                continue
            if old in content:
                content = content.replace(old, new, 1)
            else:
                failed += 1

    content = clean(content)
    out = os.path.join(BASE, target_suffix.replace("/", os.sep))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"{target_suffix}: {len(content)} chars failed={failed}")
    return content


for f in FILES:
    rebuild(f)
