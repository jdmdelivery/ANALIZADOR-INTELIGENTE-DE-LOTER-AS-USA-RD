"""Constantes del módulo de precisión."""

ALGORITHM_VERSION = "recommendations_v2.1"

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
