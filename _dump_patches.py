import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TRANSCRIPT = r"C:\Users\thene\.cursor\projects\c-Users-thene-OneDrive-Desktop-analizador-inteligente-de-loteria-USA-Y-RD\agent-transcripts\6a22187c-2490-4b20-8250-5aedebc112ff\6a22187c-2490-4b20-8250-5aedebc112ff.jsonl"
PATCH_DIR = r"c:\Users\thene\OneDrive\Desktop\analizador inteligente de loteria USA Y RD\_patches"

TARGETS = [
    "models.py", "app.py", "static/js/app.js", "templates/index.html",
    "templates/base.html", "static/css/style.css", "analysis.py",
    "importers.py", "services/resultados/illinois_scraper.py",
]

os.makedirs(PATCH_DIR, exist_ok=True)

def norm_path(p):
    p = p.replace("\\", "/")
    for t in TARGETS:
        if p.endswith(t):
            return t
    return None

file_ops = {t: [] for t in TARGETS}

with open(TRANSCRIPT, "r", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        for item in obj.get("message", {}).get("content", []) or []:
            if not isinstance(item, dict) or item.get("name") not in ("Write", "StrReplace"):
                continue
            inp = item.get("input", {})
            t = norm_path(inp.get("path", ""))
            if t:
                file_ops[t].append((i, item.get("name"), inp))

# Save patch log
for t, ops in file_ops.items():
    log_path = os.path.join(PATCH_DIR, t.replace("/", "_") + "_ops.txt")
    with open(log_path, "w", encoding="utf-8") as log:
        for ln, name, inp in ops:
            log.write(f"\n{'='*60}\nL{ln} {name}\n{'='*60}\n")
            if name == "Write":
                log.write(inp.get("contents", ""))
            else:
                log.write("--- OLD ---\n")
                log.write(inp.get("old_string", ""))
                log.write("\n--- NEW ---\n")
                log.write(inp.get("new_string", ""))
    print(f"{t}: {len(ops)} ops -> {log_path}")

# Also dump any new_string containing specific fragments
fragments = ["get_max", "grouped", "RD_DRAW", "Ver todos", "mode=", "illinois", "renderGrouped"]
frag_path = os.path.join(PATCH_DIR, "fragments.txt")
with open(frag_path, "w", encoding="utf-8") as ff:
    with open(TRANSCRIPT, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if not any(x in line for x in fragments):
                continue
            try:
                obj = json.loads(line)
            except:
                continue
            for item in obj.get("message", {}).get("content", []) or []:
                if item.get("name") != "StrReplace":
                    continue
                ns = item.get("input", {}).get("new_string", "")
                if any(x.lower() in ns.lower() for x in fragments):
                    p = item.get("input", {}).get("path", "")
                    ff.write(f"\nL{i} {p}\n{ns}\n")
print(f"fragments -> {frag_path}")
