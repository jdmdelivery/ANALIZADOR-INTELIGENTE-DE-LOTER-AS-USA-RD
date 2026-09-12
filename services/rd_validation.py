"""Validación central de resultados RD previo a persistencia."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from services.rd_time import today_rd


_LEIDSA_EXPECTED = {
    "leidsa_super_kino_tv": 20,
    "leidsa_loto_mas": 6,
    "leidsa_loto_pool": 5,
    "leidsa_pega3": 3,
    "leidsa_quiniela_pale": 3,
    "leidsa_super_pale": 2,
}


def expected_numbers_count(*, lottery_type: str = "", lottery_name: str = "") -> int | None:
    lt = (lottery_type or "").strip().lower()
    if lt in _LEIDSA_EXPECTED:
        return _LEIDSA_EXPECTED[lt]
    if lt.startswith("leidsa_"):
        return None
    name = (lottery_name or "").lower()
    if "super kino" in name:
        return 20
    if any(k in name for k in ("loto mas", "loto más")):
        return 6
    if "loto pool" in name:
        return 5
    if "super pale" in name:
        return 2
    if "pega 3" in name or "quiniela" in name:
        return 3
    if "loteria real" in name or "lotería real" in name:
        return 3
    # RD no-LEIDSA vigente: quiniela estándar de 3 números.
    if not lt.startswith("leidsa_"):
        return 3
    return None


def validate_result(
    row: dict[str, Any],
    *,
    lottery_type: str = "",
    allow_unknown_schema: bool = False,
) -> tuple[bool, str]:
    draw_date = str(row.get("draw_date") or row.get("fecha_rd") or "").strip()
    if len(draw_date) < 10:
        return False, "draw_date inválida"
    try:
        d = datetime.strptime(draw_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return False, "draw_date inválida"
    if d > today_rd():
        return False, "draw_date futura"

    draw_name = str(row.get("draw_name") or row.get("draw") or "").strip()
    if not draw_name:
        return False, "draw_name vacío"
    nums = row.get("numbers") or row.get("numeros") or []
    if not isinstance(nums, list) or not nums:
        return False, "numbers vacío"
    try:
        norm_nums = [int(str(n)) for n in nums]
    except ValueError:
        return False, "numbers malformado"
    if any(n < 0 or n > 99 for n in norm_nums):
        return False, "numbers fuera de rango"

    expected = expected_numbers_count(
        lottery_type=lottery_type,
        lottery_name=str(row.get("lottery_name") or row.get("lottery") or ""),
    )
    if expected is None:
        if allow_unknown_schema:
            return True, ""
        return False, "schema desconocido"
    if len(norm_nums) != expected:
        return False, f"numbers_count esperado={expected} recibido={len(norm_nums)}"

    return True, ""
