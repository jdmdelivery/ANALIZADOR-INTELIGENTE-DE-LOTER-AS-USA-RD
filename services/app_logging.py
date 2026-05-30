"""Logging centralizado para la aplicación."""
from __future__ import annotations

import logging
import os
import sys


def setup_app_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    if os.environ.get("FLASK_DEBUG") == "1":
        level = logging.DEBUG

    root = logging.getLogger()
    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(level)

    logging.getLogger("werkzeug").setLevel(logging.WARNING if level > logging.DEBUG else logging.DEBUG)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
