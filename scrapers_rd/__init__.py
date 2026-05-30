"""Scrapers República Dominicana (LEIDSA + Conectate). Aislados de USA."""
from scrapers_rd.conectate import (
    import_conectate_lottery_bulk_style,
    import_conectate_lottery_history,
    import_conectate_rd,
    import_conectate_rd_new_lotteries_only,
)
from scrapers_rd.leidsa import refresh_leidsa_now, scrape_leidsa_results

__all__ = [
    "refresh_leidsa_now",
    "scrape_leidsa_results",
    "import_conectate_rd",
    "import_conectate_lottery_history",
    "import_conectate_lottery_bulk_style",
    "import_conectate_rd_new_lotteries_only",
]
