"""Unit tests for AGV type keyword fallback (U-K-01 to U-K-08)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.context_builder import product_type_keyword_fallback


def test_U_K_01_vna():
    assert product_type_keyword_fallback("We need a VNA robot for our warehouse.") == "Forklift AGV"


def test_U_K_02_schmalgangstapler():
    assert product_type_keyword_fallback("Schmalgangstapler mit 12m Hubhöhe gesucht.") == "Forklift AGV"


def test_U_K_03_routenzug():
    assert product_type_keyword_fallback("Routenzug für die Produktion gesucht.") == "Tugger AGV"


def test_U_K_04_milk_run():
    assert product_type_keyword_fallback("Milk run system for our assembly lines.") == "Tugger AGV"


def test_U_K_05_amr():
    assert product_type_keyword_fallback("AMR for warehouse transport required.") == "Mobile AMR"


def test_U_K_06_goods_to_person():
    assert product_type_keyword_fallback("Goods-to-Person picking system needed.") == "Mobile AMR"


def test_U_K_07_no_keywords():
    assert product_type_keyword_fallback("Office furniture and cleaning supplies.") is None


def test_U_K_08_only_first_5000_chars():
    long_text = "a" * 6000 + " VNA robot"
    # VNA is beyond 5000 chars — should return None
    assert product_type_keyword_fallback(long_text) is None
