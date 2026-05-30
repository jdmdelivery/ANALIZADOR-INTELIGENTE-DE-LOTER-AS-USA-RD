"""Punto de entrada USA — Illinois Results Hub."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
LOG_PREFIX = "[USA]"


def refresh_usa_illinois(lottery_name: str | None = None, refresh_all: bool = True):
    """
    Actualiza resultados Illinois. Nunca importa módulos RD.
    """
    if refresh_all or not lottery_name:
        from services.resultados.illinois_scraper import import_illinois_results_hub

        result = import_illinois_results_hub()
    else:
        from services.resultados.illinois_scraper import import_illinois_lottery_now

        result = import_illinois_lottery_now(lottery_name)

    if result.get("ok"):
        logger.info(
            "%s Illinois parser OK — %s nuevos, %s actualizados",
            LOG_PREFIX,
            result.get("imported", 0),
            result.get("updated", 0),
        )
    else:
        logger.warning("%s Illinois hub: %s", LOG_PREFIX, result.get("message"))
    return result


# Re-export scraper público
from services.resultados.illinois_scraper import (  # noqa: E402
    IllinoisResultsHubScraper,
    import_illinois_all_games_safe,
    import_illinois_lottery_now,
    import_illinois_results_hub,
)

__all__ = [
    "IllinoisResultsHubScraper",
    "import_illinois_results_hub",
    "import_illinois_lottery_now",
    "import_illinois_all_games_safe",
    "refresh_usa_illinois",
]
