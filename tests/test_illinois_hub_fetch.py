"""Conexión Illinois Results Hub (live, opcional)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.resultados.illinois_cache import load_hub_cache, save_hub_cache
from services.resultados.illinois_scraper import (
    RESULTS_HUB_URL,
    IllinoisResultsHubScraper,
    parse_results_hub_html,
)


@unittest.skipUnless(
    os.environ.get("RUN_LIVE_SCRAPER_TESTS") == "1",
    "Set RUN_LIVE_SCRAPER_TESTS=1 to hit illinoislottery.com",
)
class IllinoisHubLiveTests(unittest.TestCase):
    def test_fetch_results_hub_live(self):
        scraper = IllinoisResultsHubScraper()
        page = scraper.fetch_results_hub(allow_cache=False)
        self.assertTrue(page.get("ok"), page.get("message"))
        self.assertEqual(page.get("status_code"), 200)
        rows = parse_results_hub_html(page["html"])
        self.assertGreater(len(rows), 0, "debe parsear al menos un sorteo")


class IllinoisHubCacheTests(unittest.TestCase):
    def test_cache_roundtrip(self):
        html = (
            '<div class="results-container results-container--powerball">'
            '<div class="results-content">'
            '<div class="results-content__schedule">'
            '<span class="results-content__date">May 24 2026</span>'
            '</div>'
            '<div class="results-content__balls">'
            '<div class="results-content__primary-container">'
            '<span class="main-ball">1</span><span class="main-ball">2</span>'
            '<span class="main-ball">3</span><span class="main-ball">4</span>'
            '<span class="main-ball">5</span><span class="last-ball">6</span>'
            '</div></div></div></div>'
        )
        save_hub_cache(html, url=RESULTS_HUB_URL, status_code=200)
        cached = load_hub_cache()
        self.assertTrue(cached.get("ok"))
        self.assertTrue(cached.get("from_cache"))
        rows = parse_results_hub_html(cached["html"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["lottery_name"], "Powerball")


if __name__ == "__main__":
    unittest.main()
