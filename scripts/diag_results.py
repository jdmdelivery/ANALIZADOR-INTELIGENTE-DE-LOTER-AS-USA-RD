import sqlite3
from datetime import datetime
from pathlib import Path

conn = sqlite3.connect("lottery.db")
conn.row_factory = sqlite3.Row
print("Today server:", datetime.now().strftime("%Y-%m-%d"))
rows = conn.execute("""
SELECT l.name, l.country, MAX(r.draw_date) as last_date, COUNT(*) as cnt
FROM lottery_results r JOIN lotteries l ON l.id=r.lottery_id
GROUP BY l.id ORDER BY last_date DESC
""").fetchall()
for r in rows:
    print(f"{r['country']:4} {r['name'][:35]:35} last={r['last_date']} cnt={r['cnt']}")

meta = Path("data/usa/illinois_cache/results_hub_meta.json")
if meta.exists():
    print("\nHub cache meta:", meta.read_text()[:300])
