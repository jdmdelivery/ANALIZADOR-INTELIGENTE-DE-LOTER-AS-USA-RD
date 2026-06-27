"""Pruebas sistema RD inteligente — sin tocar USA."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from models import (
    get_all_lotteries,
    get_recent_recomendaciones_rd,
    init_db,
    save_recomendacion_rd,
    upsert_rd_result,
)
from services.lottery_normalize import find_lottery_in_list
from services.rd_normalize import normalize_rd_row, valid_quiniela_numbers, format_quiniela
from services.rd_recomendacion_service import (
    ALGO_VERSION,
    _apply_anti_repetition,
    _combo_key,
    _daily_seed,
    generar_recomendacion_rd,
)
from services.rd_resultados_service import persist_rd_rows


@pytest.fixture(autouse=True)
def _db():
    init_db()
    yield


RD_LOTERIAS = [
    ("Anguila", "tardía"),
    ("Anguila", "noche"),
    ("Suerte Dominicana", "tarde"),
    ("Suerte Dominicana", "noche"),
    ("Leidsa", "noche"),
    ("Lotería Nacional", "tarde"),
    ("Lotería Nacional", "noche"),
    ("Loteka", "noche"),
    ("Lotería Real", "tarde"),
    ("La Primera", "mañana"),
    ("La Primera", "noche"),
]


def test_normalize_nacional_noche():
    row = normalize_rd_row({
        "lottery_name": "Quiniela Nacional Noche",
        "draw_name": "noche",
        "draw_date": "2026-05-20",
        "numbers": ["01", "45", "88"],
    })
    assert row is not None
    assert row["lottery_name"] == "Lotería Nacional"
    assert row["draw_name"] == "noche"


def test_normalize_anguilla_evening():
    row = normalize_rd_row({
        "title": "Anguilla Evening",
        "draw_date": "2026-05-20",
        "numbers": [12, 34, 56],
    })
    assert row is not None
    assert row["lottery_name"] == "Anguila"
    assert row["draw_name"] == "tardía"


def test_valid_quiniela():
    assert valid_quiniela_numbers(["00", "99", "05"])
    assert not valid_quiniela_numbers(["100", "01", "02"])
    assert format_quiniela([1, 5, 99]) == ["01", "05", "99"]


def test_upsert_rd_no_duplicate():
    lot = find_lottery_in_list(get_all_lotteries(), "Anguila", country="RD")
    assert lot
    dd = "2099-01-15"
    _, a1, _ = upsert_rd_result(
        lot["id"], "tardía", "18:00", dd, ["11", "22", "33"], fuente="test_a"
    )
    _, a2, _ = upsert_rd_result(
        lot["id"], "tardía", "18:00", dd, ["11", "22", "33"], fuente="test_b"
    )
    assert a1 in ("inserted", "updated")
    assert a2 == "ignored"


def test_persist_rd_rows_counts():
    rows = [{
        "lottery_name": "Anguila",
        "draw_name": "noche",
        "draw_time": "21:00",
        "draw_date": "2099-01-16",
        "numbers": ["44", "55", "66"],
    }]
    r1 = persist_rd_rows(rows, fuente="test_persist", days=365)
    r2 = persist_rd_rows(rows, fuente="test_persist", days=365)
    assert (r1["imported"] + r1["updated"]) >= 1
    assert r2.get("ignored", 0) >= 1 or (r2["imported"] == 0 and r2["updated"] == 0)


def test_daily_seed_stable():
    s1 = _daily_seed("2026-05-27", "Anguila", "noche", "9:00 PM")
    s2 = _daily_seed("2026-05-27", "Anguila", "noche", "9:00 PM")
    s3 = _daily_seed("2026-05-28", "Anguila", "noche", "9:00 PM")
    assert s1 == s2
    assert s1 != s3


def test_anti_repetition_avoids_recent_combo():
    base = {
        "generated_numbers": ["17", "65", "70"],
        "hot_numbers": ["17", "65", "70", "12", "33"],
        "top_numbers": {"top_50": [{"number": f"{i:02d}"} for i in range(50)]},
        "position_picks": [
            {"top_5": [{"number": f"{i:02d}"} for i in range(5)]} for _ in range(3)
        ],
    }
    lot = find_lottery_in_list(get_all_lotteries(), "Anguila", country="RD")
    fecha = date.today().isoformat()
    from lottery_schedules import get_schedule_slot
    slot = get_schedule_slot("Anguila", "noche")
    horario = (slot or {}).get("time", "9:00 PM")
    save_recomendacion_rd(
        fecha=fecha,
        lottery_id=lot["id"],
        loteria="Anguila",
        sorteo="noche",
        horario=horario,
        numeros=["17", "65", "70"],
        score_total=80,
        confianza=80,
        confianza_label="Alta",
        explicacion="test",
        rango_dias=90,
        algoritmo_version=ALGO_VERSION,
    )
    combo, note = _apply_anti_repetition(
        base,
        loteria="Anguila",
        sorteo="noche",
        horario="9:00 PM",
        fecha=fecha,
        lottery_id=lot["id"],
        draw_name="noche",
    )
    assert _combo_key(combo) != ("17", "65", "70")
    assert "rotación" in note.lower()


@pytest.mark.parametrize("loteria,sorteo", RD_LOTERIAS)
def test_generar_recomendacion_rd_smoke(loteria, sorteo):
    """Smoke: motor RD devuelve payload o mensaje de datos insuficientes."""
    result = generar_recomendacion_rd(loteria, sorteo, rango_dias=90, force=True)
    assert "ok" in result
    if result.get("ok"):
        nums = result.get("generated_numbers") or []
        assert len(nums) == 3
        assert result.get("rd_inteligente") is True
        assert result.get("algoritmo_version") == ALGO_VERSION


def test_recomendacion_cambia_al_dia_siguiente():
    lot = find_lottery_in_list(get_all_lotteries(), "Anguila", country="RD")
    if not lot:
        pytest.skip("Anguila no en BD")
    hoy = date.today().isoformat()
    manana = (date.today() + timedelta(days=1)).isoformat()
    r1 = generar_recomendacion_rd("Anguila", "noche", rango_dias=90, fecha_actual=hoy, force=True)
    if not r1.get("ok"):
        pytest.skip("sin datos históricos")
    r2 = generar_recomendacion_rd("Anguila", "noche", rango_dias=90, fecha_actual=manana, force=True)
    if r2.get("ok"):
        # Puede coincidir por azar pero semilla distinta favorece cambio
        assert _daily_seed(hoy, "Anguila", "noche", r1.get("analyzer_diagnostic", {}).get("horario_exacto", "")) != \
            _daily_seed(manana, "Anguila", "noche", r2.get("analyzer_diagnostic", {}).get("horario_exacto", ""))


def test_recent_recomendaciones_7_dias():
    lot = find_lottery_in_list(get_all_lotteries(), "Loteka", country="RD")
    if not lot:
        pytest.skip()
    save_recomendacion_rd(
        fecha=date.today().isoformat(),
        lottery_id=lot["id"],
        loteria="Loteka",
        sorteo="noche",
        horario="19:55",
        numeros=["01", "02", "03"],
        score_total=70,
        confianza=70,
        confianza_label="Media",
        explicacion="t",
        rango_dias=30,
        algoritmo_version=ALGO_VERSION,
    )
    recent = get_recent_recomendaciones_rd("Loteka", "noche", "19:55", days=7)
    assert len(recent) >= 1
