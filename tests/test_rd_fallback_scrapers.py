"""Tests parsers fallback RD (sin red)."""
import unittest

from scrapers.rd_fallback_scrapers import (
    _parse_enloteria_html,
    _parse_loteriadominicana_html,
    _parse_kiskoo_main,
    _valid_quiniela,
)


KISKOO_SNIPPET = """
<div class="game-block company-block-1 x">
  <img data-src="https://cdn.example/quiniela-real.png"/>
  <div class="session-date">30-05</div>
  <div class="game-scores"><span class="score">49</span><span class="score">58</span><span class="score">08</span></div>
</div>
"""

LOTDOM_SNIPPET = """
<div class="result-item col-12">
  <div class="result-item-title">Quiniela Real</div>
  <div class="result-item-ball-content"><span>49</span><span>58</span><span>08</span></div>
  <span>30-05-2026</span>
</div>
"""

ENLOTERIA_SNIPPET = """
<div class="result-card">Real Sáb 30 de mayo, 2026 12:55PM 49 58 08</div>
"""


class TestRdFallbackParsers(unittest.TestCase):
    def test_valid_quiniela(self):
        self.assertTrue(_valid_quiniela(["01", "49", "99"]))
        self.assertFalse(_valid_quiniela(["01", "02"]))
        self.assertFalse(_valid_quiniela(["100", "02", "03"]))

    def test_kiskoo_main(self):
        rows = _parse_kiskoo_main(
            KISKOO_SNIPPET,
            "https://test/",
            {"quiniela-real": ("Lotería Real", "tarde")},
            "2026",
            "2026-05-30",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["numbers"], ["49", "58", "08"])

    def test_loteriadominicana(self):
        rows = _parse_loteriadominicana_html(LOTDOM_SNIPPET, "https://lotdom/")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["lottery_name"], "Lotería Real")

    def test_enloteria(self):
        rows = _parse_enloteria_html(ENLOTERIA_SNIPPET, "https://enloteria/")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["numbers"], ["49", "58", "08"])


if __name__ == "__main__":
    unittest.main()
