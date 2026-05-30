"""Tests parser Lucky Day — IllinoisLotteryNumbers.net."""
from scrapers.illinoislotterynumbers_luckyday import (
    _valid_main,
    parse_iln_luckyday_html,
)

SAMPLE = """
<div class="main-result wide blue-grad-wide">
  <div class="date"><strong>Friday,</strong> May 29, 2026</div>
  <div class="group-wrapper">
    <div class="box">
      <div class="h4">Midday</div>
      <ul class="balls"><li class="ball">3</li><li class="ball">4</li><li class="ball">7</li><li class="ball">23</li><li class="ball">33</li></ul>
    </div>
    <div class="box">
      <div class="h4">Evening</div>
      <ul class="balls"><li class="ball">5</li><li class="ball">17</li><li class="ball">32</li><li class="ball">35</li><li class="ball">37</li></ul>
    </div>
  </div>
</div>
"""


def test_parse_midday_evening():
    rows = parse_iln_luckyday_html(SAMPLE)
    assert len(rows) == 2
    midday = next(r for r in rows if r["draw_name"] == "Midday")
    assert midday["draw_date"] == "2026-05-29"
    assert midday["draw_time"] == "12:40"
    assert midday["main_numbers"] == ["03", "04", "07", "23", "33"]
    evening = next(r for r in rows if r["draw_name"] == "Evening")
    assert evening["draw_time"] == "21:22"


def test_valid_range_1_45():
    assert _valid_main(["01", "02", "03", "04", "05"])
    assert not _valid_main(["01", "02", "03", "04", "46"])
    assert not _valid_main(["01", "02", "03", "04"])
