"""Constantes del motor de recomendaciones."""

RECOMMENDATION_DISCLAIMER = (
    "La lotería es azar. Este análisis no garantiza premios. "
    "Solo usa historial, frecuencia y tendencia."
)

MIN_HISTORY = 10
INSUFFICIENT_HISTORY_MSG = "No hay resultados suficientes para esta tanda"

# Ventanas de análisis (sorteos recientes)
ANALYSIS_WINDOWS = (7, 15, 25, 50, 90)

# Pesos multi-ventana — prioriza reciente sin ignorar historial largo
DEFAULT_WEIGHTS = {
    "freq_7": 0.20,
    "freq_15": 0.16,
    "freq_25": 0.14,
    "freq_50": 0.10,
    "freq_90": 0.08,
    "trend_10": 0.12,
    "delay": 0.08,
    "stability": 0.04,
    "context": 0.04,
    "weekday": 0.02,
    "draw_slot": 0.02,
}

WEIGHT_MIN = 0.05
WEIGHT_MAX = 0.35

CONFIDENCE_HIGH_MIN = 80
CONFIDENCE_MED_MIN = 60
STRONG_RECOMMENDATION_MIN = 60

WINDOWS = (7, 15, 25, 30, 100)

PICK_FAMILY = frozenset({"pick2", "pick3", "pick4", "pick5"})
QUINIELA_RD_PREFIXES = ("rd_", "quiniela")
QUINIELA_RD_EXACT = frozenset({
    "quiniela",
    "leidsa_quiniela_pale",
    "leidsa_pega3",
})
KINO_FAMILY = frozenset({"leidsa_super_kino_tv", "pick10", "kino"})
LOTTO_FAMILY = frozenset({
    "lucky_day",
    "lotto",
    "leidsa_loto_mas",
    "leidsa_loto_pool",
    "leidsa_super_pale",
})
POWER_MEGA_FAMILY = frozenset({"powerball", "mega_millions"})

BONUS_LABELS = {
    "powerball": "Powerball",
    "mega_millions": "Mega Ball",
    "lotto": "Extra Shot",
    "pick3": "Fireball",
    "pick4": "Fireball",
    "pick2": "Fireball",
    "pick5": "Fireball",
}
