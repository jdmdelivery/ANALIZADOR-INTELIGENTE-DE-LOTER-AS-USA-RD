import json
import os

TRANSCRIPT = r"C:\Users\thene\.cursor\projects\c-Users-thene-OneDrive-Desktop-analizador-inteligente-de-loteria-USA-Y-RD\agent-transcripts\6a22187c-2490-4b20-8250-5aedebc112ff\6a22187c-2490-4b20-8250-5aedebc112ff.jsonl"

TARGETS = [
    "models.py", "app.py", "static/js/app.js", "templates/index.html",
    "templates/base.html", "static/css/style.css", "analysis.py",
    "importers.py", "services/resultados/illinois_scraper.py",
]


def norm_path(p):
    p = p.replace("\\", "/")
    for t in TARGETS:
        if p.endswith(t):
            return t
    return None


def main():
    for t in TARGETS:
        print(f"\n=== {t} ===")
        with open(TRANSCRIPT, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = obj.get("message", {})
                for item in msg.get("content", []) or []:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name", "")
                    if name not in ("Write", "StrReplace"):
                        continue
                    inp = item.get("input", {})
                    if norm_path(inp.get("path", "")) != t:
                        continue
                    if name == "Write":
                        c = inp.get("contents", "")
                        syms = []
                        for s in ["get_max_draw_date", "RD_DRAW_ORDER", "mode=latest", "Ver todos", "illinois", "upsert_result", "renderBallSet", "grouped"]:
                            if s.lower() in c.lower():
                                syms.append(s)
                        print(f"  L{i} Write {len(c)} chars syms={syms}")
                    else:
                        old = inp.get("old_string", "")[:60].replace("\n", "\\n")
                        new = inp.get("new_string", "")[:60].replace("\n", "\\n")
                        print(f"  L{i} StrReplace old=[{old}...] new=[{new}...]")


if __name__ == "__main__":
    main()
