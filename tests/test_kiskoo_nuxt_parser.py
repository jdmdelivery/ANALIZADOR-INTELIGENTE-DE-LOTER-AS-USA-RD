"""Tests parser Kiskoo/Nuxt RD."""
import json

from scrapers.kiskoo_nuxt_parser import (
    map_kiskoo_title,
    parse_iso_date,
    parse_quiniela_scores_from_pool,
    resolve_devalue,
    valid_quiniela,
)

SAMPLE_POOL = [
    {"statistics": {"positions": 3}, "is_quiniela": True},
    ["29", "01", "26"],
    "2026-06-24T04:00:00.000Z",
    {"_id": "g1", "game_id": 0, "score": 1, "date": 2, "is_quiniela": True},
]


def test_valid_quiniela():
    assert valid_quiniela(["01", "23", "07"])
    assert not valid_quiniela(["01", "23"])
    assert not valid_quiniela(["01", "23", "100"])


def test_map_kiskoo_title_loteka():
    assert map_kiskoo_title("Quiniela Loteka") == ("Loteka", "noche")
    assert map_kiskoo_title("Anguila 10:00 AM") == ("Anguila", "mañana")


def test_parse_iso_date():
    assert parse_iso_date("2026-06-24T04:00:00.000Z") == "2026-06-24"


def test_parse_quiniela_from_pool():
    rows = parse_quiniela_scores_from_pool(SAMPLE_POOL, cutoff="2026-01-01")
    assert len(rows) == 1
    assert rows[0]["numbers"] == ["29", "01", "26"]
    assert rows[0]["draw_date"] == "2026-06-24"


def test_resolve_devalue_score_array():
    nums = resolve_devalue(SAMPLE_POOL, 1)
    assert nums == ["29", "01", "26"]
