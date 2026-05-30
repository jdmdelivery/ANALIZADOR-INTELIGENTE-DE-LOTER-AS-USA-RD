"""Normalización única de nombres de lotería (RD y búsquedas)."""
from __future__ import annotations

import re
import unicodedata

# clave normalizada -> nombres posibles en DB / scraper / UI
_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "anguila": ("anguila", "la anguila"),
    "florida": ("florida",),
    "king_lottery": ("king lottery", "king"),
    "la_primera": ("la primera", "primera"),
    "la_suerte": ("la suerte dominicana", "suerte dominicana", "suerte dom"),
    "leidsa": ("leidsa",),
    "lotedom": ("lotedom", "lote dom"),
    "loteka": ("loteka",),
    "gana_mas": ("gana mas", "gana más"),
    "loteria_nacional": ("loteria nacional", "lotería nacional", "nacional"),
    "new_york": ("new york", "nueva york", "ny"),
    "quiniela_real": ("quiniela real", "loteria real", "lotería real", "loto real"),
}


def _strip_accents(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def normalize_lottery_name(name: str) -> str:
    """Quita acentos, espacios extra; devuelve clave interna estable."""
    if not name:
        return ""
    text = _strip_accents(str(name).strip().lower())
    text = re.sub(r"\s+", " ", text)
    text = text.replace("leidsa ", "").strip() if text.startswith("leidsa ") else text
    for key, variants in _NAME_ALIASES.items():
        for v in variants:
            if text == v or text.endswith(v) or v in text:
                return key
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def lottery_names_match(name_a: str, name_b: str) -> bool:
    a, b = normalize_lottery_name(name_a), normalize_lottery_name(name_b)
    return bool(a) and a == b


def find_lottery_in_list(lotteries: list[dict], name: str, country: str = "RD") -> dict | None:
    """Busca lotería por nombre normalizado (cualquier variante en DB)."""
    target = normalize_lottery_name(name)
    if not target:
        return None
    for lot in lotteries:
        if country and (lot.get("country") or "").upper() != country.upper():
            continue
        if normalize_lottery_name(lot.get("name", "")) == target:
            return lot
        # LEIDSA por slug
        ltype = (lot.get("type") or "").lower()
        if target == "leidsa" and ltype.startswith("leidsa_"):
            continue
    return None
