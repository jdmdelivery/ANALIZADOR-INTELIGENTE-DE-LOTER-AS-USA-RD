"""Dependencias de scraping."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.scraper_deps import ensure_scraper_deps, get_beautiful_soup


class ScraperDepsTests(unittest.TestCase):
    def test_bs4_available(self):
        ensure_scraper_deps()
        BeautifulSoup = get_beautiful_soup()
        soup = BeautifulSoup("<html><body>ok</body></html>", "lxml")
        self.assertIn("ok", soup.get_text())


if __name__ == "__main__":
    unittest.main()
