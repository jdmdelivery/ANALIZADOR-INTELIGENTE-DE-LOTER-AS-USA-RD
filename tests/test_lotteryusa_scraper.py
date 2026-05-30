"""Tests LotteryUSA parser (sin red)."""
from scrapers.lotteryusa_scraper import LOTTERYUSA_GAMES, parse_lotteryusa_html

SAMPLE_POWERBALL = """
<table>
<tr class="c-draw-card">
<th class="c-draw-card__date"><time class="c-draw-card__draw-date">
<span class="c-draw-card__draw-date-dow">Monday,</span>
<span class="c-draw-card__draw-date-sub">May 25, 2026</span>
</time></th>
<td class="c-draw-card__result">
<div class="c-draw-card__ball-box">
<ul class="c-result c-draw-card__ball-list">
<li class="c-ball c-ball--sm">17</li>
<li class="c-ball c-ball--sm">32</li>
<li class="c-ball c-ball--sm">48</li>
<li class="c-ball c-ball--sm">60</li>
<li class="c-ball c-ball--sm">64</li>
<li class="c-result__bonus">
<abbr title="Powerball">PB</abbr>
<span class="c-ball c-ball--red c-ball--sm">10</span>
</li>
</ul>
</div>
</td>
</tr>
</table>
"""


def test_parse_powerball_row():
    cfg = LOTTERYUSA_GAMES["powerball"]
    rows = parse_lotteryusa_html(SAMPLE_POWERBALL, cfg, "https://example.com/pb")
    assert len(rows) == 1
    row = rows[0]
    assert row["draw_date"] == "2026-05-25"
    assert row["main_numbers"] == ["17", "32", "48", "60", "64"]
    assert row["bonus_numbers"] == ["10"]
    assert row["lottery_name"] == "Powerball"
