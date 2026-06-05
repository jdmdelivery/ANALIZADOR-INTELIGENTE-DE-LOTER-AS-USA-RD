import re
from scrapers.usa_http import fetch_url
from scrapers.lotteryusa_scraper import LOTTERYUSA_GAMES, parse_lotteryusa_html

for slug, cfg in LOTTERYUSA_GAMES.items():
    page = fetch_url(
        f"https://www.lotteryusa.com{cfg['path']}",
        source="lotteryusa",
        min_bytes=500,
    )
    if not page.get("ok"):
        print(slug, "FETCH FAIL", page.get("error"))
        continue
    rows = parse_lotteryusa_html(page["html"], cfg, page["url"])
    dates = sorted({r["draw_date"] for r in rows}, reverse=True)
    print(slug, "rows", len(rows), "max", dates[0] if dates else None, "top5", dates[:5])
    # raw dates in HTML
    raw = re.findall(r"c-draw-card__draw-date[^>]*>.*?</time>", page["html"][:50000], re.S)
    print("  raw time tags sample:", len(raw))
