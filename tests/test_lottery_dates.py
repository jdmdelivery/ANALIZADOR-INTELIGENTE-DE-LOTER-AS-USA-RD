from services.lottery_dates import parse_card_date_text, month_to_num


def test_month_abbreviations():
    assert month_to_num("Jun") == "06"
    assert month_to_num("May") == "05"
    assert month_to_num("Dec") == "12"


def test_parse_jun_abbrev():
    assert parse_card_date_text("Wednesday, Jun 3, 2026") == "2026-06-03"
    assert parse_card_date_text("Sunday, May 31, 2026") == "2026-05-31"


def test_parse_full_month():
    assert parse_card_date_text("Monday, May 25, 2026") == "2026-05-25"
