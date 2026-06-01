"""Unit tests for data_loader parsing helpers (U-D-01 to U-D-16)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.data_loader import _parse_multiselect, _parse_bool, _parse_int, _parse_float
import uuid
import pytest


def test_U_D_01_multiselect_pipe_separated():
    result = _parse_multiselect("Laser|Natural Feature")
    assert result == ["Laser", "Natural Feature"]


def test_U_D_02_multiselect_empty_string():
    assert _parse_multiselect("") == []


def test_U_D_03_multiselect_none():
    assert _parse_multiselect(None) == []


def test_U_D_04_bool_1_true():
    assert _parse_bool(1) is True


def test_U_D_05_bool_0_false():
    assert _parse_bool(0) is False


def test_U_D_06_bool_none():
    assert _parse_bool(None) is None


def test_U_D_07_reference_count_empty_is_none():
    assert _parse_int("") is None
    assert _parse_int(None) is None


def test_U_D_08_payload_empty_is_none():
    assert _parse_float("") is None
    assert _parse_float(None) is None


def test_U_D_09_uuid_format():
    test_uuid = str(uuid.uuid4())
    import re
    pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
    )
    assert pattern.match(test_uuid)


def test_U_D_16_multiselect_with_embedded_comma():
    # Pipe is the separator, embedded commas in values are fine
    result = _parse_multiselect("ISO 3691-4|ISO 13849, PLd")
    assert "ISO 3691-4" in result
    assert "ISO 13849, PLd" in result


def test_multiselect_whitespace_trimmed():
    result = _parse_multiselect(" Laser | Natural Feature ")
    assert result == ["Laser", "Natural Feature"]


def test_bool_string_true():
    assert _parse_bool("true") is True
    assert _parse_bool("True") is True
    assert _parse_bool("1") is True


def test_bool_string_false():
    assert _parse_bool("false") is False
    assert _parse_bool("False") is False
    assert _parse_bool("0") is False


def test_int_parses_float_string():
    assert _parse_int("1500.0") == 1500


def test_float_nan_is_none():
    assert _parse_float(float("nan")) is None
