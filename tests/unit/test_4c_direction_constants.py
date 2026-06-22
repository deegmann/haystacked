"""Unit tests for Pass 4c module-level startup constants from app.py (U-C-xx).

Tests that _4C_EXTRACTION_DIRECTION, _NUMERIC_KO_FIELD_HINTS, and _SHARED_SHEET
are non-empty, correctly typed, and internally consistent.

These constants are built at app startup from field_levels.json. An empty or
mismatched constant means the source-span guard and Pass 4c are silently inactive.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from app import (
    _4C_EXTRACTION_DIRECTION,
    _NUMERIC_KO_FIELD_HINTS,
    _NUMERIC_KO_TENDER_KEYS,
    _SHARED_SHEET,
)


# ---------------------------------------------------------------------------
# U-C-01: _4C_EXTRACTION_DIRECTION is non-empty
# ---------------------------------------------------------------------------

def test_U_C_01_4c_direction_non_empty():
    """_4C_EXTRACTION_DIRECTION must be non-empty after loading field_levels.json.

    An empty dict means Pass 4c has no extraction direction for any field,
    which would make all 4c prompts directionless.
    """
    assert len(_4C_EXTRACTION_DIRECTION) > 0, (
        "_4C_EXTRACTION_DIRECTION is empty — field_levels.json may be stale. "
        "Run generate_all.py."
    )


# ---------------------------------------------------------------------------
# U-C-02: required_weight_capacity_kg maps to MAXIMUM direction
# ---------------------------------------------------------------------------

def test_U_C_02_weight_capacity_direction_maximum():
    """required_weight_capacity_kg (KO_IF_LT) must map to MAXIMUM direction.

    KO_IF_LT: supplier must meet or exceed the tender threshold. To find the
    correct threshold in documents with multiple weight values, 4c must extract
    the MAXIMUM (the heaviest weight the AGV must carry).
    """
    direction = _4C_EXTRACTION_DIRECTION.get("required_weight_capacity_kg", "")
    assert "MAXIMUM" in direction, (
        f"required_weight_capacity_kg direction must contain 'MAXIMUM' (KO_IF_LT). "
        f"Got: {direction!r}"
    )


# ---------------------------------------------------------------------------
# U-C-03: required_min_aisle_width_m maps to MINIMUM direction
# ---------------------------------------------------------------------------

def test_U_C_03_aisle_width_direction_minimum():
    """required_min_aisle_width_m (KO_IF_GT) must map to MINIMUM direction.

    KO_IF_GT: supplier must not exceed the available aisle width. When a document
    states both rack-to-rack and pallet-to-pallet widths, 4c must extract the
    MINIMUM (the tightest constraint the AGV must fit through).
    """
    direction = _4C_EXTRACTION_DIRECTION.get("required_min_aisle_width_m", "")
    assert "MINIMUM" in direction, (
        f"required_min_aisle_width_m direction must contain 'MINIMUM' (KO_IF_GT). "
        f"Got: {direction!r}"
    )


# ---------------------------------------------------------------------------
# U-C-04: required_max_lift_height_m maps to MAXIMUM direction
# ---------------------------------------------------------------------------

def test_U_C_04_lift_height_direction_maximum():
    """required_max_lift_height_m (KO_IF_LT) must map to MAXIMUM direction.

    KO_IF_LT: supplier's lift height must meet or exceed the maximum racking height
    required. 4c must extract the MAXIMUM (highest storage level the AGV must reach).
    """
    direction = _4C_EXTRACTION_DIRECTION.get("required_max_lift_height_m", "")
    assert "MAXIMUM" in direction, (
        f"required_max_lift_height_m direction must contain 'MAXIMUM' (KO_IF_LT). "
        f"Got: {direction!r}"
    )


# ---------------------------------------------------------------------------
# U-C-05: Every key in _NUMERIC_KO_FIELD_HINTS has a direction in _4C_EXTRACTION_DIRECTION
# ---------------------------------------------------------------------------

def test_U_C_05_hints_keys_have_direction():
    """Every key in _NUMERIC_KO_FIELD_HINTS must appear in _4C_EXTRACTION_DIRECTION.

    _NUMERIC_KO_FIELD_HINTS contains the fields for which 4c sends individual LLM
    calls. Each of those fields must have a direction (MAXIMUM or MINIMUM) so the
    4c prompt can guide extraction. A missing direction means a directionless prompt.
    """
    missing = [
        k for k in _NUMERIC_KO_FIELD_HINTS
        if k not in _4C_EXTRACTION_DIRECTION
    ]
    assert not missing, (
        f"Fields in _NUMERIC_KO_FIELD_HINTS without a 4c direction: {missing}. "
        f"These fields will get directionless 4c prompts. "
        f"Check field_levels.json for their operator values."
    )


# ---------------------------------------------------------------------------
# U-C-06: _4C_EXTRACTION_DIRECTION values are non-empty strings
# ---------------------------------------------------------------------------

def test_U_C_06_direction_values_are_strings():
    """All values in _4C_EXTRACTION_DIRECTION must be non-empty strings."""
    for k, v in _4C_EXTRACTION_DIRECTION.items():
        assert isinstance(v, str) and len(v) > 0, (
            f"_4C_EXTRACTION_DIRECTION[{k!r}] is not a non-empty string: {v!r}"
        )


# ---------------------------------------------------------------------------
# U-C-07: _SHARED_SHEET is a non-empty string
# ---------------------------------------------------------------------------

def test_U_C_07_shared_sheet_non_empty():
    """_SHARED_SHEET must be a non-empty string loaded from vehicle_types.json.

    This constant controls which extraction hints apply to all vehicle types
    in Pass 4c. A missing or empty value would mean shared fields are excluded
    from per-field extraction.
    """
    assert isinstance(_SHARED_SHEET, str) and len(_SHARED_SHEET) > 0, (
        f"_SHARED_SHEET must be a non-empty string. Got: {_SHARED_SHEET!r}"
    )
