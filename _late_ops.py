import json
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

path = r"C:\Users\thene\.cursor\projects\c-Users-thene-OneDrive-Desktop-analizador-inteligente-de-loteria-USA-Y-RD\agent-transcripts\6a22187c-2490-4b20-8250-5aedebc112ff\6a22187c-2490-4b20-8250-5aedebc112ff.jsonl"
OUT = r"c:\Users\thene\OneDrive\Desktop\analizador inteligente de loteria USA Y RD\_patches\late_ops.txt"

lines = open(path, encoding="utf-8").readlines()
with open(OUT, "w", encoding="utf-8") as out:
    for i in range(225, len(lines)):
        try:
            obj = json.loads(lines[i])
        except:
            continue
        for item in obj.get("message", {}).get("content", []) or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            if name not in ("Write", "StrReplace"):
                continue
            inp = item.get("input", {})
            p = inp.get("path", "")
            out.write(f"\n{'='*70}\nLINE {i+1} {name}\n{p}\n{'='*70}\n")
            if name == "Write":
                out.write(inp.get("contents", ""))
            else:
                out.write("--- OLD ---\n")
                out.write(inp.get("old_string", ""))
                out.write("\n--- NEW ---\n")
                out.write(inp.get("new_string", ""))
print("written", OUT)
