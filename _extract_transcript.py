import json
import os
import re

TRANSCRIPT = r"C:\Users\thene\.cursor\projects\c-Users-thene-OneDrive-Desktop-analizador-inteligente-de-loteria-USA-Y-RD\agent-transcripts\6a22187c-2490-4b20-8250-5aedebc112ff\6a22187c-2490-4b20-8250-5aedebc112ff.jsonl"
OUT_DIR = r"c:\Users\thene\OneDrive\Desktop\analizador inteligente de loteria USA Y RD\_reconstructed"

TARGETS = [
    "models.py",
    "app.py",
    "static/js/app.js",
    "templates/index.html",
    "templates/base.html",
    "static/css/style.css",
    "analysis.py",
    "importers.py",
    "services/resultados/illinois_scraper.py",
]


def norm_path(p: str) -> str:
    p = p.replace("\\", "/")
    for t in TARGETS:
        if p.endswith(t):
            return t
    return ""


def apply_ops(content: str, ops) -> str:
    for _, name, inp in ops:
        if name == "Write":
            content = inp.get("contents", "")
        elif name == "StrReplace":
            old = inp.get("old_string", "")
            new = inp.get("new_string", "")
            if old in content:
                content = content.replace(old, new, 1)
            else:
                print(f"    WARN: StrReplace old_string not found ({len(old)} chars)")
    return content


def main():
    file_ops = {t: [] for t in TARGETS}
    with open(TRANSCRIPT, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = obj.get("message", {})
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict):
                    continue
                name = item.get("name", "")
                if name not in ("Write", "StrReplace"):
                    continue
                inp = item.get("input", {})
                p = inp.get("path", "")
                t = norm_path(p)
                if t:
                    file_ops[t].append((i, name, inp))

    os.makedirs(OUT_DIR, exist_ok=True)
    for t in TARGETS:
        ops = file_ops[t]
        print(f"\n=== {t} ({len(ops)} ops) ===")
        if not ops:
            continue
        # Start from first Write or empty
        content = ""
        for ln, name, inp in ops:
            if name == "Write":
                content = inp.get("contents", "")
            elif name == "StrReplace":
                old = inp.get("old_string", "")
                new = inp.get("new_string", "")
                if old in content:
                    content = content.replace(old, new, 1)
                else:
                    print(f"  L{ln} StrReplace FAILED")
        out_path = os.path.join(OUT_DIR, t.replace("/", os.sep))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  Written {len(content)} chars -> {out_path}")

        # Check required symbols
        checks = {
            "models.py": ["upsert_result", "enrich_result_row", "get_max_draw_date", "get_results_for_latest_date", "get_results_grouped_by_date", "RD_DRAW_ORDER"],
            "app.py": ["/api/results", "mode=latest", "illinois", "draw-times"],
            "static/js/app.js": ["Ver todos", "renderBallSet", "grouped"],
            "templates/index.html": ["recentResults", "Ver todos"],
            "templates/base.html": ["navbar", "block content"],
            "static/css/style.css": ["casino", "hero"],
            "analysis.py": ["analizar_loteria", "generar_jugada"],
            "importers.py": ["import_csv", "WebScraperImporter"],
            "services/resultados/illinois_scraper.py": ["illinois", "scrape"],
        }
        if t in checks:
            for sym in checks[t]:
                found = sym.lower() in content.lower()
                print(f"  {'OK' if found else 'MISSING'}: {sym}")


if __name__ == "__main__":
    main()
