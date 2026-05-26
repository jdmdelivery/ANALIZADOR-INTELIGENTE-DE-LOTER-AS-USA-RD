"""
Configuración fija LEIDSA — sin dependencias de red ni scrapers.
"""

from __future__ import annotations

TZ_RD = "America/Santo_Domingo"
SOURCE_URL = "https://www.leidsa.com/"
SOURCE_NAME = "leidsa.com"
FETCH_TIMEOUT = 15
FETCH_RETRIES = 3
LEIDSA_TEST_MODE = False  # True: guarda HTML/JSON en debug/leidsa/
DEBUG_DIR = "debug/leidsa"
HISTORY_CACHE_HOURS = 6  # cache de páginas de resultados
HISTORY_DEFAULT_DAYS = 90
HISTORY_LIMIT_PER_GAME = 100

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.leidsa.com/",
    "Accept-Language": "es-DO,es;q=0.9,en;q=0.8",
}

# Lista canónica (cada juego solo sus horarios reales)
# path = segmento URL en /results/Leidsa/{path}/{drawId}
LEIDSA_GAMES_LIST: list[dict] = [
    {
        "name": "Quiniela Palé",
        "slug": "leidsa_quiniela_pale",
        "lottery_name": "LEIDSA Quiniela Palé",
        "family_name": "Quiniela Pale",
        "site_slug": "leidsa-quiniela-pale",
        "path": "Quiniela Pale",
        "draw_id_prefix": "5_",
        "lottery_type": "quiniela",
        "draws": ["2:30 PM", "8:55 PM"],
    },
    {
        "name": "Pega 3 Más",
        "slug": "leidsa_pega3",
        "lottery_name": "LEIDSA Pega 3 Más",
        "family_name": "Pega3Mas",
        "site_slug": "leidsa-pega3mas",
        "path": "Pega3Mas",
        "draw_id_prefix": "4_",
        "lottery_type": "pick3",
        "draws": ["3:00 PM", "9:00 PM"],
    },
    {
        "name": "Loto Pool",
        "slug": "leidsa_loto_pool",
        "lottery_name": "LEIDSA Loto Pool",
        "family_name": "Loto Pool",
        "site_slug": "leidsa-loto-pool",
        "path": "Loto Pool",
        "draw_id_prefix": "2_",
        "lottery_type": "lotto",
        "draws": ["9:00 PM"],
    },
    {
        "name": "Super Kino TV",
        "slug": "leidsa_super_kino_tv",
        "lottery_name": "LEIDSA Super Kino TV",
        "family_name": "KinoTV",
        "site_slug": "leidsa-kinotv",
        "path": "KinoTV",
        "draw_id_prefix": "3_",
        "lottery_type": "lotto",
        "draws": ["8:00 PM"],
    },
    {
        "name": "Super Palé",
        "slug": "leidsa_super_pale",
        "lottery_name": "LEIDSA Super Palé",
        "family_name": "Super Pale",
        "site_slug": "leidsa-super-pale",
        "path": "Super Pale",
        "draw_id_prefix": "6_",
        "lottery_type": "quiniela",
        "draws": ["8:00 PM"],
    },
    {
        "name": "Loto Más",
        "slug": "leidsa_loto_mas",
        "lottery_name": "LEIDSA Loto Más",
        "family_name": "Loto",
        "site_slug": "leidsa-loto",
        "path": "Loto",
        "draw_id_prefix": "1_",
        "lottery_type": "lotto",
        "draws": ["9:00 PM"],
        "extra_family": "Super Más",
    },
]

# Juegos con historial completo en dropdown/drawResults (misma lista, URLs de resultados)
LEIDSA_HISTORY_GAMES: list[dict] = [
    {
        "name": g["name"],
        "slug": g["slug"],
        "path": g["path"],
        "family_name": g["family_name"],
        "draw_id_prefix": g.get("draw_id_prefix", ""),
        "url": "",  # se construye en runtime con drawId actual
    }
    for g in LEIDSA_GAMES_LIST
]

DRAW_NAME_BY_INDEX = ("tarde", "noche", "tardía", "mañana")
DRAW_NAME_SPECIAL = {
    "9:00 PM": "noche",
    "8:00 PM": "noche",
    "8:55 PM": "noche",
    "2:30 PM": "tarde",
    "3:00 PM": "tarde",
}

NAME_ALIASES = {
    "leidsa": "leidsa_quiniela_pale",
    "leidsa quiniela pale": "leidsa_quiniela_pale",
    "quiniela pale": "leidsa_quiniela_pale",
    "pega 3 mas": "leidsa_pega3",
    "pega3mas": "leidsa_pega3",
    "pega 3 más": "leidsa_pega3",
    "leidsa_pega3_mas": "leidsa_pega3",
    "loto pool": "leidsa_loto_pool",
    "super kino tv": "leidsa_super_kino_tv",
    "kinotv": "leidsa_super_kino_tv",
    "super pale": "leidsa_super_pale",
    "loto mas": "leidsa_loto_mas",
    "super mas": "leidsa_loto_mas",
    "loto": "leidsa_loto_mas",
}


def time_12h_to_24h(time_12h: str) -> str:
    raw = (time_12h or "").strip().upper()
    if not raw:
        return ""
    try:
        part, meridiem = raw.split()
        h_s, m_s = part.split(":")
        h, m = int(h_s), int(m_s)
        if meridiem == "PM" and h != 12:
            h += 12
        elif meridiem == "AM" and h == 12:
            h = 0
        return f"{h:02d}:{m:02d}"
    except (ValueError, AttributeError):
        return ""


def _draw_name_for_time(time_12h: str, index: int) -> str:
    if time_12h in DRAW_NAME_SPECIAL:
        return DRAW_NAME_SPECIAL[time_12h]
    if index < len(DRAW_NAME_BY_INDEX):
        return DRAW_NAME_BY_INDEX[index]
    return "sorteo"


def _expand_draws(draw_strings: list) -> list[dict]:
    slots = []
    for i, t in enumerate(draw_strings):
        if isinstance(t, dict):
            slots.append(t)
            continue
        time_12h = str(t).strip()
        slots.append({
            "draw_name": _draw_name_for_time(time_12h, i),
            "time": time_12h,
            "time_24h": time_12h_to_24h(time_12h),
        })
    return slots


def build_leidsa_games_dict() -> dict[str, dict]:
    out = {}
    for g in LEIDSA_GAMES_LIST:
        slug = g["slug"]
        draws = _expand_draws(g.get("draws") or [])
        out[slug] = {
            "display_name": g["name"],
            "lottery_name": g["lottery_name"],
            "family_name": g.get("family_name", g["name"]),
            "site_slug": g.get("site_slug", slug.replace("_", "-")),
            "path": g.get("path", g["name"]),
            "draw_id_prefix": g.get("draw_id_prefix", ""),
            "lottery_type": g.get("lottery_type", "quiniela"),
            "draws": draws,
        }
    return out


# Dict usado por models / schedules (sin importar scraper)
LEIDSA_GAMES: dict[str, dict] = build_leidsa_games_dict()

LEIDSA_SLUGS: tuple[str, ...] = tuple(LEIDSA_GAMES.keys())


# Recomendación por juego (nombre exacto en tabla lotteries.name)
LEIDSA_RECOMMENDATION_CONFIG: dict[str, dict] = {
    "LEIDSA Super Kino TV": {
        "recommend_count": 20,
        "allow_duplicates": False,
        "min": 1,
        "max": 80,
        "pad": 2,
    },
    "LEIDSA Loto Más": {
        "recommend_count": 6,
        "allow_duplicates": False,
        "min": 1,
        "max": 49,
        "pad": 2,
    },
    "LEIDSA Loto": {
        "recommend_count": 6,
        "allow_duplicates": False,
        "min": 1,
        "max": 49,
        "pad": 2,
    },
    "LEIDSA Super Más": {
        "recommend_count": 6,
        "allow_duplicates": False,
        "min": 1,
        "max": 49,
        "pad": 2,
    },
    "LEIDSA Quiniela Palé": {
        "recommend_count": 3,
        "allow_duplicates": False,
        "min": 0,
        "max": 99,
        "pad": 2,
    },
    "LEIDSA Quiniela": {
        "recommend_count": 3,
        "allow_duplicates": False,
        "min": 0,
        "max": 99,
        "pad": 2,
    },
    "LEIDSA Pega 3 Más": {
        "recommend_count": 3,
        "allow_duplicates": False,
        "min": 0,
        "max": 50,
        "pad": 2,
    },
    "LEIDSA Loto Pool": {
        "recommend_count": 5,
        "allow_duplicates": False,
        "min": 1,
        "max": 31,
        "pad": 2,
    },
    "LEIDSA Super Palé": {
        "recommend_count": 2,
        "allow_duplicates": False,
        "min": 0,
        "max": 99,
        "pad": 2,
    },
}

# Alias nombre / slug → clave canónica en LEIDSA_RECOMMENDATION_CONFIG
_RECOMMENDATION_NAME_ALIASES: dict[str, str] = {
    "leidsa_super_kino_tv": "LEIDSA Super Kino TV",
    "leidsa_loto_mas": "LEIDSA Loto Más",
    "leidsa_loto": "LEIDSA Loto Más",
    "leidsa_quiniela_pale": "LEIDSA Quiniela Palé",
    "leidsa_pega3": "LEIDSA Pega 3 Más",
    "leidsa_loto_pool": "LEIDSA Loto Pool",
    "leidsa_super_pale": "LEIDSA Super Palé",
    "super kino tv": "LEIDSA Super Kino TV",
    "loto mas": "LEIDSA Loto Más",
    "loto": "LEIDSA Loto Más",
    "quiniela": "LEIDSA Quiniela Palé",
    "pega 3 mas": "LEIDSA Pega 3 Más",
}


def leidsa_recommend_to_analysis_config(cfg: dict) -> dict:
    """Convierte LEIDSA_RECOMMENDATION_CONFIG al formato interno de analysis."""
    pad = cfg.get("pad", 2)
    return {
        "count": int(cfg.get("recommend_count", 3)),
        "allow_repeat": bool(cfg.get("allow_duplicates", False)),
        "min": int(cfg.get("min", 0)),
        "max": int(cfg.get("max", 99)),
        "pad": pad,
    }


def resolve_leidsa_recommendation_config(
    lottery_name: str = "",
    lottery_type: str = "",
) -> dict | None:
    """Devuelve config de análisis si es lotería LEIDSA, si no None."""
    name = (lottery_name or "").strip()
    if name in LEIDSA_RECOMMENDATION_CONFIG:
        return leidsa_recommend_to_analysis_config(LEIDSA_RECOMMENDATION_CONFIG[name])

    slug = (lottery_type or "").strip().lower()
    if slug in _RECOMMENDATION_NAME_ALIASES:
        key = _RECOMMENDATION_NAME_ALIASES[slug]
        if key in LEIDSA_RECOMMENDATION_CONFIG:
            return leidsa_recommend_to_analysis_config(LEIDSA_RECOMMENDATION_CONFIG[key])

    for g in LEIDSA_GAMES.values():
        if g["lottery_name"] == name or g["display_name"].lower() == name.lower():
            key = g["lottery_name"]
            if key in LEIDSA_RECOMMENDATION_CONFIG:
                return leidsa_recommend_to_analysis_config(LEIDSA_RECOMMENDATION_CONFIG[key])

    low = name.lower()
    for alias, key in _RECOMMENDATION_NAME_ALIASES.items():
        if alias in low or low in alias:
            if key in LEIDSA_RECOMMENDATION_CONFIG:
                return leidsa_recommend_to_analysis_config(LEIDSA_RECOMMENDATION_CONFIG[key])
    return None


def get_game_schedule_for_ui(lottery_name: str) -> list[dict] | None:
    """Horarios para lottery_schedules / botones UI."""
    for slug, cfg in LEIDSA_GAMES.items():
        if cfg["lottery_name"] == lottery_name:
            return [
                {
                    "label": d["time"],
                    "time": d["time"],
                    "draw_name": d["draw_name"],
                }
                for d in cfg["draws"]
            ]
    return None
