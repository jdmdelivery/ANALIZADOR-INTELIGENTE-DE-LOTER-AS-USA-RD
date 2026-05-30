import json
import re
import os

TRANSCRIPT = r"C:\Users\thene\.cursor\projects\c-Users-thene-OneDrive-Desktop-analizador-inteligente-de-loteria-USA-Y-RD\agent-transcripts\6a22187c-2490-4b20-8250-5aedebc112ff\6a22187c-2490-4b20-8250-5aedebc112ff.jsonl"
OUT = r"c:\Users\thene\OneDrive\Desktop\analizador inteligente de loteria USA Y RD\_reconstructed\static\js\app.js"

TARGET = "static/js/app.js"

def norm(p):
    return p.replace("\\", "/").endswith(TARGET)

ops = []
with open(TRANSCRIPT, encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        obj = json.loads(line)
        for item in obj.get("message", {}).get("content", []) or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if name not in ("Write", "StrReplace"):
                continue
            inp = item.get("input", {})
            if not norm(inp.get("path", "")):
                continue
            ops.append((i, name, inp))

content = ""
for ln, name, inp in ops:
    if name == "Write":
        content = inp["contents"]
    else:
        old = inp["old_string"]
        new = inp["new_string"]
        # strip motion corruption from patches
        old_clean = re.sub(r"</?motion>", "", old)
        new_clean = re.sub(r"</?motion>", "", new)
        if old in content:
            content = content.replace(old, new, 1)
        elif old_clean in content:
            content = content.replace(old_clean, new_clean, 1)
        else:
            print(f"FAIL L{ln}")

# cleanup any motion tags in final content
content = re.sub(r"</?motion>", "", content)
# remove accidental duplicate initNavActive block at top if present
content = re.sub(
    r"^\s*function initNavActive\(\).*?\}\s*\n\s*\^\(\?!.*?\(function \(\)",
    "(function ()",
    content,
    count=1,
    flags=re.DOTALL,
)
if content.startswith("    function initNavActive"):
    idx = content.find("(function ()")
    if idx > 0:
        content = content[idx:]

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(content)
print(f"Written {len(content)} chars, {content.count(chr(10))+1} lines")
for kw in ["renderBallSet", "Ver todos", "showAll", "grouped", "bonus"]:
    print(f"  {kw}: {kw.lower() in content.lower()}")
