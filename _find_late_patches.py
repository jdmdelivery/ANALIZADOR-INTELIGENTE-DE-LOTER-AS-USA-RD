import json
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TRANSCRIPT = r"C:\Users\thene\.cursor\projects\c-Users-thene-OneDrive-Desktop-analizador-inteligente-de-loteria-USA-Y-RD\agent-transcripts\6a22187c-2490-4b20-8250-5aedebc112ff\6a22187c-2490-4b20-8250-5aedebc112ff.jsonl"
KEYWORDS = ["get_max_draw", "grouped_by", "RD_DRAW", "Ver todos", "mode", "latest", "renderBallSet", "showAll", "api/results"]

with open(TRANSCRIPT, "r", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        if i < 150:
            continue
        try:
            obj = json.loads(line)
        except:
            continue
        s = json.dumps(obj, ensure_ascii=False)
        if not any(k.lower() in s.lower() for k in KEYWORDS):
            continue
        for item in obj.get("message", {}).get("content", []) or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            inp = item.get("input", {})
            p = inp.get("path", "").replace("\\", "/")
            if name == "StrReplace":
                ns = inp.get("new_string", "")
                if any(k.lower() in ns.lower() for k in KEYWORDS):
                    print(f"\n=== L{i} StrReplace {p.split('/')[-1]} ===")
                    print(ns[:3000])
                    if len(ns) > 3000:
                        print(f"... [{len(ns)} total chars]")
            elif name == "Write":
                c = inp.get("contents", "")
                if any(k.lower() in c.lower() for k in KEYWORDS) and any(x in p for x in ["models.py", "app.py", "app.js", "index.html"]):
                    print(f"\n=== L{i} Write {p.split('/')[-1]} len={len(c)} ===")
                    # print snippets around keywords
                    for k in KEYWORDS:
                        idx = c.lower().find(k.lower())
                        if idx >= 0:
                            print(f"  ...{k}...: {c[max(0,idx-100):idx+200]}")
