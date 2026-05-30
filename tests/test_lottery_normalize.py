"""Pruebas normalización y config RD."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.lottery_normalize import lottery_names_match, normalize_lottery_name
from services.rd_lottery_config import get_rd_lottery_config


def test_normalize_accents():
    assert normalize_lottery_name("Lotería Nacional") == "loteria_nacional"
    assert normalize_lottery_name("  La Anguila  ") == "anguila"


def test_loteria_real_alias():
    assert lottery_names_match("Lotería Real", "Quiniela Real")
    assert lottery_names_match("Suerte Dominicana", "La Suerte Dominicana")


def test_florida_config():
    cfg = get_rd_lottery_config("Florida")
    assert cfg
    assert cfg["source"] == "conectate"
    assert len(cfg.get("conectate_pages", [])) == 2
