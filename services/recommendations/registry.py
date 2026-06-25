"""Resolución de adaptador por lotería — RD y USA nunca mezclados."""
from __future__ import annotations

from services.recommendations.constants import (
    KINO_FAMILY,
    LOTTO_FAMILY,
    PICK_FAMILY,
    POWER_MEGA_FAMILY,
    QUINIELA_RD_EXACT,
)


def game_family(lottery: dict) -> str:
    country = (lottery.get("country") or "").upper()
    ltype = (lottery.get("type") or "").lower().strip()
    name = (lottery.get("name") or "").lower()

    if country == "USA":
        if ltype in PICK_FAMILY or "pick" in ltype:
            return "pick"
        if ltype in POWER_MEGA_FAMILY:
            return "power_mega"
        if ltype in LOTTO_FAMILY or ltype == "lotto":
            return "lotto"
        return "lotto"

    # República Dominicana
    if ltype in KINO_FAMILY or "kino" in name:
        return "kino"
    if ltype in LOTTO_FAMILY and "quiniela" not in name and "pale" not in name:
        if ltype in ("leidsa_loto_mas", "leidsa_loto_pool"):
            return "lotto"
    if ltype in POWER_MEGA_FAMILY:
        return "power_mega"
    if ltype in PICK_FAMILY:
        return "pick"
    if ltype in QUINIELA_RD_EXACT or ltype.startswith("rd_") or ltype == "quiniela":
        return "quiniela_rd"
    if "pale" in ltype or "pale" in name:
        return "quiniela_rd"
    return "quiniela_rd"


def resolve_adapter(lottery: dict):
    from services.recommendations.adapters.kino_adapter import KinoAdapter
    from services.recommendations.adapters.lotto_adapter import LottoAdapter
    from services.recommendations.adapters.pick_adapter import PickAdapter
    from services.recommendations.adapters.power_mega_adapter import PowerMegaAdapter
    from services.recommendations.adapters.quiniela_rd_adapter import QuinielaRDAdapter

    family = game_family(lottery)
    mapping = {
        "pick": PickAdapter,
        "quiniela_rd": QuinielaRDAdapter,
        "kino": KinoAdapter,
        "lotto": LottoAdapter,
        "power_mega": PowerMegaAdapter,
    }
    cls = mapping.get(family, QuinielaRDAdapter)
    return cls(), family


def resolve_config(lottery: dict) -> dict:
    """Config numérica sin mezclar países."""
    from analysis import _resolve_analysis_config

    return dict(_resolve_analysis_config(lottery))
