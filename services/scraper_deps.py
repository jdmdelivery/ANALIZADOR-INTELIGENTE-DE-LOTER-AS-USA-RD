"""Comprueba dependencias de scraping (BeautifulSoup, requests, lxml)."""


def ensure_scraper_deps():
    """
    Verifica que beautifulsoup4, requests y lxml estén instalados.
    Lanza ImportError con mensaje claro si falta alguno.
    """
    missing = []
    try:
        import bs4  # noqa: F401
    except ImportError:
        missing.append("beautifulsoup4")
    try:
        import requests  # noqa: F401
    except ImportError:
        missing.append("requests")
    try:
        import lxml  # noqa: F401
    except ImportError:
        missing.append("lxml")
    if missing:
        pkgs = " ".join(missing)
        raise ImportError(
            f"Faltan dependencias ({pkgs}). Ejecuta: pip install {pkgs}"
        )


def get_beautiful_soup():
    ensure_scraper_deps()
    from bs4 import BeautifulSoup

    return BeautifulSoup
