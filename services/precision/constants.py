"""Constantes del módulo de precisión."""

ALGORITHM_VERSION = "recommendations_v2.2"

MAX_WEIGHT_DELTA = 0.05  # 5% máximo por ciclo de autoaprendizaje

STATUS_EXCELLENT = "excelente"
STATUS_GOOD = "bueno"
STATUS_REGULAR = "regular"
STATUS_BAD = "malo"

STATUS_LABELS = {
    STATUS_EXCELLENT: "Excelente",
    STATUS_GOOD: "Bueno",
    STATUS_REGULAR: "Regular",
    STATUS_BAD: "Malo",
}

STATUS_ICONS = {
    STATUS_EXCELLENT: "🟢",
    STATUS_GOOD: "🟡",
    STATUS_REGULAR: "🟠",
    STATUS_BAD: "🔴",
}

HISTORY_LIMITS = (100, 500, 1000, 5000)

GAME_FAMILY_LABELS = {
    "quiniela_rd": {"icon": "🎱", "label": "Quiniela RD"},
    "pick": {"icon": "🔢", "label": "Pick 3 / Pick 4"},
    "pick3": {"icon": "🔢", "label": "Pick 3"},
    "pick4": {"icon": "🔢", "label": "Pick 4"},
    "power_mega": {"icon": "🎯", "label": "Powerball / Mega Millions"},
    "powerball": {"icon": "🎯", "label": "Powerball"},
    "mega_millions": {"icon": "⭐", "label": "Mega Millions"},
    "kino": {"icon": "🎟", "label": "Kino / Super Kino"},
    "lotto": {"icon": "🍀", "label": "Lucky Day / Lotto"},
}

FACTOR_LABELS = {
    "freq_25": "Frecuencia reciente",
    "freq_100": "Frecuencia histórica",
    "trend_10": "Tendencia",
    "delay": "Atraso",
    "stability": "Estabilidad",
    "context": "Posición",
    "weekday": "Día de semana",
    "draw_slot": "Horario / tanda",
}

HIT_SUCCESS_THRESHOLD = 60  # % para contar como acierto

WEEKDAY_ES = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
