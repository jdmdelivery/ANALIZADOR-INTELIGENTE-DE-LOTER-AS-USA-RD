"""Punto de entrada RD — Conectate.do (Loteka, Nacional, Florida RD, etc.)."""
from scrapers.conectate_rd import (  # noqa: F401
    ConectateRDScraper,
    import_conectate_lottery_bulk_style,
    import_conectate_lottery_history,
    import_conectate_rd,
    import_conectate_rd_new_lotteries_only,
)

__all__ = [
    "ConectateRDScraper",
    "import_conectate_rd",
    "import_conectate_lottery_history",
    "import_conectate_lottery_bulk_style",
    "import_conectate_rd_new_lotteries_only",
]
