"""Tests LotteryPost parser (sin red)."""
from scrapers.lotterypost_scraper import parse_lotterypost_html

SAMPLE = """
<section>
<h2>Powerball</h2>
<time datetime="2026-05-27T21:59-06:00">Wednesday, May 27, 2026</time>
<div class="resultsnumbers">
<div class="resultsnumswrap">
<div class="resultsnumsrow">
<ul class="resultsnums"><li>5</li><li>14</li><li>21</li><li>31</li><li>51</li></ul>
</div>
<div class="resultsnumsrow">Powerball:
<ul class="resultsnums"><li class="red">13</li></ul>
</div>
</div>
</div>
</section>
<section>
<h2>Pick 3 Midday</h2>
<time datetime="2026-05-29T12:40-06:00">Friday, May 29, 2026</time>
<div class="resultsnumbers">
<div class="resultsnumswrap">
<div class="resultsnumsrow">
<ul class="resultsnums"><li>1</li><li>0</li><li>4</li></ul>
</div>
<div class="resultsnumsrow">Fireball:
<ul class="resultsnums"><li class="orange">9</li></ul>
</div>
</div>
</div>
</section>
"""


def test_parse_powerball_and_pick3():
    rows = parse_lotterypost_html(SAMPLE)
    assert len(rows) == 2
    pb = next(r for r in rows if r["lottery_name"] == "Powerball")
    assert pb["draw_date"] == "2026-05-27"
    assert pb["main_numbers"] == ["05", "14", "21", "31", "51"]
    assert pb["bonus_numbers"] == ["13"]
    p3 = next(r for r in rows if r["lottery_name"] == "Illinois Pick 3")
    assert p3["draw_name"] == "Midday"
    assert p3["main_numbers"] == ["1", "0", "4"]
    assert p3["bonus_numbers"] == ["9"]
