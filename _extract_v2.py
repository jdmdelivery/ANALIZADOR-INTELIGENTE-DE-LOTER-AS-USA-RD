import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TRANSCRIPT = r"C:\Users\thene\.cursor\projects\c-Users-thene-OneDrive-Desktop-analizador-inteligente-de-loteria-USA-Y-RD\agent-transcripts\6a22187c-2490-4b20-8250-5aedebc112ff\6a22187c-2490-4b20-8250-5aedebc112ff.jsonl"
OUT_DIR = r"c:\Users\thene\OneDrive\Desktop\analizador inteligente de loteria USA Y RD\_reconstructed"

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


def apply_all(content, ops):
    failed = []
    for ln, name, inp in ops:
        if name == "Write":
            content = inp.get("contents", "")
            continue
        old = inp.get("old_string", "")
        new = inp.get("new_string", "")
        if old in content:
            content = content.replace(old, new, 1)
        else:
            failed.append((ln, len(old), old[:80]))
    return content, failed


def score_content(t, content):
    checks = {
        "models.py": ["upsert_result", "enrich_result_row", "get_max_draw_date",
                      "get_results_for_latest_date", "get_results_grouped_by_date", "RD_DRAW_ORDER"],
        "app.py": ["/api/results", "mode", "latest", "illinois", "draw-times", "draw_times"],
        "static/js/app.js": ["Ver todos", "renderBallSet", "grouped", "bonus", "showAll"],
        "templates/index.html": ["recentResults", "Ver todos", "btnShowAll"],
        "templates/base.html": ["navbar", "premium-body", "block content"],
        "static/css/style.css": ["casino", "hero-section", "premium"],
        "analysis.py": ["analizar_loteria", "generar_jugada"],
        "importers.py": ["import_csv", "WebScraperImporter", "upsert"],
        "services/resultados/illinois_scraper.py": ["IllinoisResultsHubScraper", "import_illinois"],
    }
    syms = checks.get(t, [])
    return sum(1 for s in syms if s.lower() in content.lower()), syms


def main():
    file_ops = {t: [] for t in TARGETS}
    write_versions = {t: [] for t in TARGETS}

    with open(TRANSCRIPT, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            for item in obj.get("message", {}).get("content", []) or []:
                if not isinstance(item, dict):
                    continue
                name = item.get("name", "")
                if name not in ("Write", "StrReplace"):
                    continue
                inp = item.get("input", {})
                t = norm_path(inp.get("path", ""))
                if not t:
                    continue
                file_ops[t].append((i, name, inp))
                if name == "Write":
                    write_versions[t].append((i, inp.get("contents", "")))

    os.makedirs(OUT_DIR, exist_ok=True)

    for t in TARGETS:
        ops = file_ops[t]
        content, failed = apply_all("", ops)

        # Also try: start from each Write and apply subsequent StrReplace only
        best = content
        best_score, _ = score_content(t, content)

        for wln, wcontent in write_versions[t]:
            sub_ops = [(ln, n, inp) for ln, n, inp in ops if ln >= wln]
            c2, f2 = apply_all(wcontent, sub_ops)
            sc, _ = score_content(t, c2)
            if sc > best_score or (sc == best_score and len(c2) > len(best)):
                best = c2
                best_score = sc
                failed = f2

        out_path = os.path.join(OUT_DIR, t.replace("/", os.sep))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(best)

        sc, syms = score_content(t, best)
        print(f"\n=== {t} ===")
        print(f"  ops={len(ops)} writes={len(write_versions[t])} chars={len(best)} score={sc}/{len(syms)} failed={len(failed)}")
        for s in syms:
            ok = s.lower() in best.lower()
            print(f"    {'OK' if ok else 'MISSING'}: {s}")
        if failed[:3]:
            for ln, l, preview in failed[:3]:
                print(f"    FAIL L{ln} old_len={l} preview={preview!r}")


if __name__ == "__main__":
    main()
