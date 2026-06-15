"""Unit tests for source_confirms_value and _interpret_number_token (OI-30 / OI-4C-03)."""
import sys
import pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.json_repair import source_confirms_value, _interpret_number_token


# ---------------------------------------------------------------------------
# _interpret_number_token
# ---------------------------------------------------------------------------

def test_token_de_decimal_comma():
    assert 3.4 in _interpret_number_token("3,4")

def test_token_en_thousands_comma():
    assert 1000.0 in _interpret_number_token("1,000")

def test_token_de_mixed_separators():
    assert 1000.0 in _interpret_number_token("1.000,00")

def test_token_en_mixed_separators():
    assert 1000.0 in _interpret_number_token("1,000.00")

def test_token_plain_decimal():
    assert 3.4 in _interpret_number_token("3.4")

def test_token_de_thousands_period():
    assert 1000.0 in _interpret_number_token("1.000")

def test_token_integer():
    assert 42.0 in _interpret_number_token("42")


# ---------------------------------------------------------------------------
# source_confirms_value — locale correctness (OI-30 regression)
# ---------------------------------------------------------------------------

def test_U_SCV_01_de_decimal_comma_found():
    """Core OI-30 regression: German decimal comma must confirm the float value."""
    assert source_confirms_value(3.4, "Gangbreite min. 3,4 m (laut Planung)") is True

def test_U_SCV_02_de_decimal_comma_not_matched():
    assert source_confirms_value(3.4, "Gangbreite min. 5,6 m") is False

def test_U_SCV_03_en_decimal_point_found():
    assert source_confirms_value(3.4, "min aisle width 3.4 m") is True

def test_U_SCV_04_de_mixed_separators():
    assert source_confirms_value(1000.0, "Nutzlast 1.000,00 kg") is True

def test_U_SCV_05_en_mixed_separators():
    assert source_confirms_value(1000.0, "payload 1,000.00 kg") is True

def test_U_SCV_06_en_thousands_comma():
    assert source_confirms_value(1000.0, "max payload 1,000 kg") is True


# ---------------------------------------------------------------------------
# source_confirms_value — unit-scale tolerance (existing behaviour, no regression)
# ---------------------------------------------------------------------------

def test_U_SCV_07_mm_to_m_scale():
    """value=2.0 m matches 2000 in source (mm in document)."""
    assert source_confirms_value(2.0, "Hubhöhe 2000 mm") is True

def test_U_SCV_08_m_to_mm_scale():
    """value=2000 mm matches 2 in source (m in document)."""
    assert source_confirms_value(2000.0, "Hubhöhe 2 m") is True


# ---------------------------------------------------------------------------
# source_confirms_value — edge cases
# ---------------------------------------------------------------------------

def test_U_SCV_09_zero_always_passes():
    assert source_confirms_value(0, "keine Angabe") is True

def test_U_SCV_10_value_not_in_source():
    assert source_confirms_value(99.9, "Hubhöhe 2 m, Nutzlast 1000 kg") is False

def test_U_SCV_11_empty_source():
    assert source_confirms_value(3.4, "") is False

def test_U_SCV_12_none_value_nonempty_source():
    assert source_confirms_value(None, "some text") is True
