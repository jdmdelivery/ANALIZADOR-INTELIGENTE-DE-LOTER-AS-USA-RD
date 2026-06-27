"""Múltiples sorteos el mismo día (tandas distintas) no se sobrescriben."""
from __future__ import annotations

import pytest

from models import (
    count_results_for_date,
    get_results_for_latest_date,
    migrate_db,
    upsert_result,
)
from services.lottery_normalize import find_lottery_in_list
from models import get_all_lotteries


@pytest.fixture(autouse=True)
def _migrate():
    migrate_db()


def _nacional_id() -> int:
    lot = find_lottery_in_list(get_all_lotteries(), "Lotería Nacional", country="RD")
    assert lot, "Lotería Nacional debe existir en BD de prueba"
    return lot["id"]


def test_upsert_three_draws_same_day_distinct():
    lid = _nacional_id()
    dd = "2099-01-15"
    draws = [
        ("tarde", "14:30", ["12", "34", "56"]),
        ("tardía", "18:00", ["11", "22", "33"]),
        ("noche", "21:00", ["44", "55", "66"]),
    ]
    for draw_name, draw_time, nums in draws:
        _, action = upsert_result(
            lid, draw_name, draw_time, dd, nums, fuente="test", confirmed=1
        )
        assert action in ("inserted", "updated")

    total = count_results_for_date(lid, dd)
    assert total == 3, f"esperaba 3 sorteos, hay {total}"

    results, latest = get_results_for_latest_date(lid, None)
    same_day = [r for r in results if r.get("draw_date") == dd]
    assert len(same_day) == 3
    times = {r["draw_time"] for r in same_day}
    assert times == {"14:30", "18:00", "21:00"}


def test_upsert_later_draw_does_not_overwrite_earlier():
    lid = _nacional_id()
    dd = "2099-02-20"
    upsert_result(lid, "tarde", "14:30", dd, ["01", "02", "03"], fuente="test")
    upsert_result(lid, "tardía", "18:00", dd, ["04", "05", "06"], fuente="test")
    upsert_result(lid, "noche", "21:00", dd, ["07", "08", "09"], fuente="test")

    # Actualizar solo tarde no debe borrar tardía/noche
    upsert_result(lid, "tarde", "14:30", dd, ["10", "11", "12"], fuente="test")
    assert count_results_for_date(lid, dd) == 3

    results, _ = get_results_for_latest_date(lid, None)
    tarde = next(r for r in results if r["draw_name"] == "tarde")
    assert "10" in tarde["numbers"]
