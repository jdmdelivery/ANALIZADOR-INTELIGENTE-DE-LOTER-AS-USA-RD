"""Tests Lucky Day Lotto — parsers dedicados."""
from scrapers.illinoislotterynumbers_luckyday import _valid_main, parse_iln_luckyday_html
from scrapers.lucky_day_sources import (
    parse_lottery_net_html,
    valid_lucky_day_main,
)

SAMPLE_ILN = """
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

SAMPLE_LOTTERY_NET = """
<h3>Saturday May 30th 2026</h3>
<ul class="illinois results lucky-day-lotto-midday">
<li class="ball">13</li><li class="ball">15</li><li class="ball">18</li><li class="ball">24</li><li class="ball">29</li>
</ul>
"""


def test_valid_range_1_45():
    assert valid_lucky_day_main(["01", "02", "03", "04", "05"])
    assert not valid_lucky_day_main(["01", "02", "03", "04", "46"])
    assert _valid_main(["01", "02", "03", "04", "05"])


def test_parse_iln_midday_evening():
    rows = parse_iln_luckyday_html(SAMPLE_ILN)
    assert len(rows) == 2
    midday = next(r for r in rows if r["draw_name"] == "Midday")
    assert midday["draw_date"] == "2026-05-29"
    assert midday["draw_time"] == "12:40"


def test_parse_lottery_net():
    rows = parse_lottery_net_html(SAMPLE_LOTTERY_NET, "Midday", "https://lottery.net/")
    assert len(rows) == 1
    assert rows[0]["main_numbers"] == ["13", "15", "18", "24", "29"]
    assert rows[0]["draw_name"] == "Midday"


def test_rejects_number_50():
    assert not valid_lucky_day_main(["01", "02", "03", "04", "50"])


def test_hub_stale_rows_rejected(monkeypatch):
    from scrapers import lucky_day_lotto_service as svc

    monkeypatch.setattr(svc, "_lucky_day_lottery_id", lambda: 99)
    monkeypatch.setattr(svc, "get_max_draw_date", lambda _lid: "2026-06-04")

    stale = {
        "ok": True,
        "imported": 0,
        "updated": 0,
        "rows_parsed": 2,
        "latest_date": "2026-01-04",
    }
    assert not svc._source_has_fresh_data(stale)

    fresh = {
        "ok": True,
        "imported": 3,
        "updated": 0,
        "rows_parsed": 10,
        "latest_date": "2026-06-04",
    }
    assert svc._source_has_fresh_data(fresh)
