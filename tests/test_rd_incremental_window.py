from __future__ import annotations

from services import rd_results_service as svc


def test_effective_days_uses_latest_saved_plus_one(monkeypatch):
    monkeypatch.setattr(
        svc,
        "get_rd_lottery_config",
        lambda _name: {"draw_map": {"noche": "8:00 PM"}},
    )
    monkeypatch.setattr(
        svc,
        "get_latest_result_date_for_scope",
        lambda *_args, **_kwargs: "2026-08-16",
    )
    monkeypatch.setattr(svc, "get_max_draw_date", lambda *_args, **_kwargs: "2026-08-16")
    monkeypatch.setattr(svc, "today_rd_iso", lambda: "2026-08-20")

    days, start, end = svc._effective_days_from_last_date(
        1,
        30,
        lottery_name="LEIDSA Super Kino TV",
        force_days=0,
    )
    assert start == "2026-08-17"
    assert end == "2026-08-20"
    assert days >= 7


def test_effective_days_force_days_expands_window(monkeypatch):
    monkeypatch.setattr(
        svc,
        "get_rd_lottery_config",
        lambda _name: {"draw_map": {"noche": "8:00 PM"}},
    )
    monkeypatch.setattr(
        svc,
        "get_latest_result_date_for_scope",
        lambda *_args, **_kwargs: "2026-08-19",
    )
    monkeypatch.setattr(svc, "get_max_draw_date", lambda *_args, **_kwargs: "2026-08-19")
    monkeypatch.setattr(svc, "today_rd_iso", lambda: "2026-08-20")

    _days, start, _end = svc._effective_days_from_last_date(
        1,
        7,
        lottery_name="LEIDSA Super Kino TV",
        force_days=10,
    )
    assert start == "2026-08-10"
