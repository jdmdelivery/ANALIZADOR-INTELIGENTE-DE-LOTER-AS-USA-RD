import json
import re
import os

TRANSCRIPT = r"C:\Users\thene\.cursor\projects\c-Users-thene-OneDrive-Desktop-analizador-inteligente-de-loteria-USA-Y-RD\agent-transcripts\6a22187c-2490-4b20-8250-5aedebc112ff\6a22187c-2490-4b20-8250-5aedebc112ff.jsonl"
OUT = r"c:\Users\thene\OneDrive\Desktop\analizador inteligente de loteria USA Y RD\_reconstructed\static\js\app.js"
TARGET = "static/js/app.js"


def clean(s):
    if not s:
        return s
    s = re.sub(r"</?motion>", "", s)
    s = re.sub(
        r"document\.createElement\([^)]*motion[^)]*\)",
        "document.createElement('div')",
        s,
    )
    s = s.replace("</p></motion></motion></motion></div>", "</div>")
    s = s.replace("</p></div>", "</div>")
    return s


ops = []
with open(TRANSCRIPT, encoding="utf-8") as f:
    for line in f:
        obj = json.loads(line)
        for item in obj.get("message", {}).get("content", []) or []:
            if not isinstance(item, dict) or item.get("name") not in ("Write", "StrReplace"):
                continue
            p = item.get("input", {}).get("path", "").replace("\\", "/")
            if p.endswith(TARGET):
                ops.append((item["name"], item["input"]))

content = ""
failed = 0
for name, inp in ops:
    if name == "Write":
        content = clean(inp["contents"])
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
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(content)
print(f"chars={len(content)} failed={failed}")
print("renderBallSet", "renderBallSet" in content)
print("initNavActive", "initNavActive" in content)
