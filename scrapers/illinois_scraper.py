"""Wrapper Illinois Lottery — delega al scraper oficial en services."""
from __future__ import annotations

from services.resultados.illinois_scraper import (  # noqa: F401
    IllinoisResultsHubScraper,
    import_illinois_all_games_safe,
    import_illinois_lottery_now,
    import_illinois_results_hub,
    parse_results_hub_html,
)

__all__ = [
    "IllinoisResultsHubScraper",
    "import_illinois_results_hub",
    "import_illinois_lottery_now",
    "import_illinois_all_games_safe",
    "parse_results_hub_html",
]
