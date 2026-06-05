import sys
sys.path.insert(0, ".")

from scrapers.lotteryusa_scraper import LotteryUsaScraper


def test_pick3_parses_june_dates():
    scraper = LotteryUsaScraper()
    res = scraper.scrape_game("pick3", max_rows=5)
    assert res.get("ok"), res.get("message")
    dates = sorted({r["draw_date"] for r in res["rows"]}, reverse=True)
    assert dates[0] >= "2026-06-01", f"Expected June dates, got {dates}"
