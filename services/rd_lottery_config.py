"""Configuración RD: fuente, horarios, páginas Conectate, nombres en DB."""
from __future__ import annotations

from services.lottery_normalize import normalize_lottery_name

# Fuente: conectate | leidsa | leidsa_game (por slug en type)
LOTTERY_CONFIG: dict[str, dict] = {
    "Florida": {
        "source": "conectate",
        "db_names": ["Florida"],
        "draws": ["1:30 PM", "9:45 PM"],
        "draw_map": {"tarde": "1:30 PM", "noche": "9:45 PM"},
        "enabled": True,
        "conectate_pages": [
            {"path": "/loterias/americanas/florida-dia", "draw_name": "tarde", "draw_time": "13:30"},
            {"path": "/loterias/americanas/florida-noche", "draw_name": "noche", "draw_time": "21:45"},
        ],
        "logo_keys": ["florida-dia", "florida-noche-quiniela"],
    },
    "King Lottery": {
        "source": "conectate",
        "db_names": ["King Lottery"],
        "draws": ["12:30 PM", "7:30 PM"],
        "draw_map": {"tarde": "12:30 PM", "noche": "7:30 PM"},
        "enabled": True,
        "conectate_pages": [
            {"path": "/loterias/king-lottery/quiniela-dia", "draw_name": "tarde", "draw_time": "12:30"},
            {"path": "/loterias/king-lottery/quiniela-noche", "draw_name": "noche", "draw_time": "19:30"},
        ],
        "logo_keys": ["quiniela-king-lottery-dia", "quiniela-king-lottery-noche"],
    },
    "Anguila": {
        "source": "conectate",
        "db_names": ["Anguila", "La Anguila"],
        "draws": ["10:00 AM", "1:00 PM", "6:00 PM", "9:00 PM"],
        "draw_map": {"mañana": "10:00 AM", "tarde": "1:00 PM", "tardía": "6:00 PM", "noche": "9:00 PM"},
        "enabled": True,
        "anguila": True,
    },
    "La Primera": {
        "source": "conectate",
        "db_names": ["La Primera"],
        "draws": ["12:00 PM", "7:00 PM"],
        "draw_map": {"mañana": "12:00 PM", "noche": "7:00 PM"},
        "enabled": True,
        "conectate_pages": [
            {"path": "/loterias/la-primera/quiniela-medio-dia", "draw_name": "mañana", "draw_time": "12:00"},
            {"path": "/loterias/la-primera/quiniela-noche", "draw_name": "noche", "draw_time": "20:00"},
        ],
        "logo_keys": ["la-primera-dia", "la-primera-noche"],
    },
    "La Suerte Dominicana": {
        "source": "conectate",
        "db_names": ["Suerte Dominicana", "La Suerte Dominicana"],
        "draws": ["12:30 PM", "6:00 PM"],
        "draw_map": {"tarde": "12:30 PM", "noche": "6:00 PM"},
        "enabled": True,
        "conectate_pages": [
            {"path": "/loterias/la-suerte-dominicana/quiniela-tarde", "draw_name": "tarde", "draw_time": "12:30"},
            {"path": "/loterias/la-suerte-dominicana/quiniela", "draw_name": "noche", "draw_time": "18:00"},
        ],
        "logo_keys": ["la-suerte-dia", "la-suerte-noche"],
    },
    "Leidsa": {
        "source": "leidsa",
        "db_names": ["Leidsa"],
        "draws": ["3:55 PM", "8:55 PM"],
        "enabled": True,
    },
    "Lotedom": {
        "source": "conectate",
        "db_names": ["Lotedom"],
        "draws": ["12:00 PM"],
        "draw_map": {"tarde": "12:00 PM"},
        "enabled": True,
        "conectate_pages": [
            {"path": "/loterias/lotedom/quiniela", "draw_name": "tarde", "draw_time": "13:55"},
        ],
        "logo_keys": ["quiniela-lotedom"],
    },
    "Loteka": {
        "source": "conectate",
        "db_names": ["Loteka"],
        "draws": ["12:55 PM", "7:55 PM"],
        "draw_map": {"tarde": "12:55 PM", "noche": "7:55 PM"},
        "enabled": True,
        "conectate_pages": [
            {"path": "/loterias/loteka/quiniela-mega-decenas", "draw_name": "noche", "draw_time": "19:55"},
        ],
        "logo_keys": ["quiniela-loteka"],
    },
    "Gana Más": {
        "source": "conectate",
        "db_names": ["Gana Más"],
        "draws": ["2:30 PM"],
        "draw_map": {"tarde": "2:30 PM"},
        "enabled": True,
        "conectate_pages": [
            {"path": "/loterias/nacional/gana-mas", "draw_name": "tarde", "draw_time": "14:30"},
        ],
        "logo_keys": ["gana-mas-loteria-nacional"],
    },
    "Lotería Nacional": {
        "source": "conectate",
        "db_names": ["Lotería Nacional"],
        "draws": ["2:30 PM", "6:00 PM", "9:00 PM"],
        "draw_map": {"tarde": "2:30 PM", "tardía": "6:00 PM", "noche": "9:00 PM"},
        "enabled": True,
        "conectate_pages": [
            {"path": "/loterias/nacional/quiniela", "draw_name": "tarde", "draw_time": "14:30"},
        ],
        "logo_keys": ["loteria-nacional"],
    },
    "New York": {
        "source": "conectate",
        "db_names": ["New York"],
        "draws": ["2:30 PM", "10:30 PM"],
        "draw_map": {"tarde": "2:30 PM", "noche": "10:30 PM"},
        "enabled": True,
        "conectate_pages": [
            {"path": "/loterias/americanas/new-york-medio-dia", "draw_name": "tarde", "draw_time": "14:30"},
            {"path": "/loterias/americanas/new-york-noche", "draw_name": "noche", "draw_time": "22:30"},
        ],
        "logo_keys": ["new-york-dia", "new-york-noche"],
    },
    "Quiniela Real": {
        "source": "conectate",
        "db_names": ["Lotería Real", "Quiniela Real"],
        "draws": ["12:55 PM", "8:00 PM"],
        "draw_map": {"tarde": "12:55 PM", "noche": "8:00 PM"},
        "enabled": True,
        "conectate_pages": [
            {"path": "/loterias/loto-real/quiniela", "draw_name": "tarde", "draw_time": "12:55"},
        ],
        "logo_keys": ["quiniela-real", "loto-real"],
    },
}

# Índice por clave normalizada
_CONFIG_BY_KEY: dict[str, tuple[str, dict]] = {}
for _label, _cfg in LOTTERY_CONFIG.items():
    _cfg = {**_cfg, "label": _label}
    keys = {normalize_lottery_name(_label)}
    for n in _cfg.get("db_names", []):
        keys.add(normalize_lottery_name(n))
    for k in keys:
        _CONFIG_BY_KEY[k] = (_label, _cfg)


def get_rd_lottery_config(lottery_name: str) -> dict | None:
    key = normalize_lottery_name(lottery_name)
    if not key:
        return None
    if key in _CONFIG_BY_KEY:
        return _CONFIG_BY_KEY[key][1]
    if key.startswith("leidsa_") or "leidsa" in key:
        return {**LOTTERY_CONFIG["Leidsa"], "source": "leidsa_game", "label": lottery_name}
    return None


def get_config_label(lottery_name: str) -> str | None:
    key = normalize_lottery_name(lottery_name)
    if key in _CONFIG_BY_KEY:
        return _CONFIG_BY_KEY[key][0]
    return None


def iter_enabled_conectate_configs() -> list[tuple[str, dict]]:
    out = []
    seen = set()
    for label, cfg in LOTTERY_CONFIG.items():
        if not cfg.get("enabled") or cfg.get("source") != "conectate":
            continue
        if label in seen:
            continue
        seen.add(label)
        out.append((label, cfg))
    return out


def build_conectate_draw_pages() -> list[dict]:
    """Lista plana para importación masiva Conectate."""
    pages = []
    for label, cfg in iter_enabled_conectate_configs():
        for page in cfg.get("conectate_pages") or []:
            pages.append({
                "lottery_name": cfg["db_names"][0],
                "path": page["path"],
                "draw_name": page["draw_name"],
                "draw_time": page["draw_time"],
            })
    return pages


_LOGO_MAIN_EXPLICIT: dict[str, tuple[str, str]] = {
    "florida-dia": ("Florida", "tarde"),
    "florida-noche-quiniela": ("Florida", "noche"),
    "quiniela-king-lottery-dia": ("King Lottery", "tarde"),
    "quiniela-king-lottery-noche": ("King Lottery", "noche"),
    "new-york-dia": ("New York", "tarde"),
    "new-york-noche": ("New York", "noche"),
    "la-suerte-dia": ("Suerte Dominicana", "tarde"),
    "la-suerte-noche": ("Suerte Dominicana", "noche"),
    "quiniela-la-suerte": ("Suerte Dominicana", "tarde"),
    "la-primera-dia": ("La Primera", "mañana"),
    "la-primera-noche": ("La Primera", "noche"),
    "quiniela-loteka": ("Loteka", "noche"),
    "quiniela-lotedom": ("Lotedom", "tarde"),
    "gana-mas-loteria-nacional": ("Gana Más", "tarde"),
    "loteria-nacional": ("Lotería Nacional", "tarde"),
    "quiniela-real": ("Lotería Real", "tarde"),
    "loto-real": ("Lotería Real", "tarde"),
    "quiniela-leidsa": ("Leidsa", "noche"),
}


def build_logo_main_page() -> dict[str, tuple[str, str]]:
    return dict(_LOGO_MAIN_EXPLICIT)
