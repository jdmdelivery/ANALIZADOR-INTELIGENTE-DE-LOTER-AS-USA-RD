from __future__ import annotations

from services.rd_update_jobs import create_job, finish_job, get_job, start_job
from services.rd_validation import expected_numbers_count, validate_result


def test_expected_numbers_count_maps_known_games():
    assert expected_numbers_count(lottery_type="leidsa_super_kino_tv") == 20
    assert expected_numbers_count(lottery_type="leidsa_loto_mas") == 6
    assert expected_numbers_count(lottery_name="Lotería Real") == 3


def test_validate_result_rejects_wrong_count():
    ok, err = validate_result(
        {
            "lottery_name": "Lotería Real",
            "draw_name": "tarde",
            "draw_date": "2026-09-01",
            "numbers": ["01", "02", "03", "04", "05", "06"],
        },
        lottery_type="quiniela",
    )
    assert ok is False
    assert "esperado=3" in err


def test_validate_result_accepts_super_kino_20_numbers():
    ok, err = validate_result(
        {
            "lottery_name": "LEIDSA Super Kino TV",
            "draw_name": "noche",
            "draw_date": "2026-09-01",
            "numbers": [f"{n:02d}" for n in range(1, 21)],
        },
        lottery_type="leidsa_super_kino_tv",
    )
    assert ok is True
    assert err == ""


def test_rd_update_job_lifecycle():
    job = create_job({"pais": "RD", "loteria": "Lotería Real"})
    start_job(job["job_id"])
    finish_job(
        job["job_id"],
        result={
            "ok": True,
            "imported": 2,
            "updated": 1,
            "ignored": 3,
            "errors": [],
            "status": "updated",
            "sources_tried": [{"fuente": "conectate_api", "ok": True}],
        },
    )
    saved = get_job(job["job_id"])
    assert saved
    assert saved["status"] == "success"
    assert saved["inserted"] == 2
    assert saved["updated"] == 1
    assert saved["ignored"] == 3
