"""Configuración de entorno para desarrollo y producción."""
from __future__ import annotations

import os

# Base
FLASK_ENV = os.environ.get("FLASK_ENV", "development").lower()
IS_PRODUCTION = FLASK_ENV == "production" or os.environ.get("PRODUCTION", "") == "1"
DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1" and not IS_PRODUCTION

# Seguridad
SECRET_KEY = os.environ.get("SECRET_KEY", "")
DATABASE_PATH = os.environ.get("DATABASE_PATH", "lottery.db")

# Admin inicial (solo primer arranque si no hay usuarios)
INITIAL_ADMIN_USERNAME = os.environ.get("INITIAL_ADMIN_USERNAME", "jdmcashnow")
INITIAL_ADMIN_PASSWORD = os.environ.get("INITIAL_ADMIN_PASSWORD", "")

# Servidor
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "5000"))


def validate_production_config() -> list[str]:
    """Devuelve advertencias/errores de configuración."""
    issues: list[str] = []
    if IS_PRODUCTION:
        if not SECRET_KEY or len(SECRET_KEY) < 16:
            issues.append("SECRET_KEY debe definirse en producción (mín. 16 caracteres).")
        if not INITIAL_ADMIN_PASSWORD:
            issues.append(
                "INITIAL_ADMIN_PASSWORD recomendado en producción para el primer admin."
            )
    return issues
