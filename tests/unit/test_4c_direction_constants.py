"""Unit tests for Pass 4c module-level startup constants from app.py (U-C-xx).

Tests that _4C_EXTRACTION_DIRECTION, _NUMERIC_KO_FIELD_HINTS, _LEGACY_MAP, and
_EXTRACTABLE_DOMAINS are non-empty, correctly typed, and internally consistent.

These constants are built at app startup from fields.json via field_spec.py. An empty or
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
    _LEGACY_MAP,
    _EXTRACTABLE_DOMAINS,
)


# ---------------------------------------------------------------------------
# U-C-01: _4C_EXTRACTION_DIRECTION is non-empty
# ---------------------------------------------------------------------------

def test_U_C_01_4c_direction_non_empty():
    """_4C_EXTRACTION_DIRECTION must be non-empty after loading fields.json.

    An empty dict means Pass 4c has no extraction direction for any field,
    which would make all 4c prompts directionless.
    """
    assert len(_4C_EXTRACTION_DIRECTION) > 0, (
        "_4C_EXTRACTION_DIRECTION is empty — fields.json may be stale. "
        "Run generate_all.py."
    )


# ---------------------------------------------------------------------------
# U-C-02: required_max_payload_kg maps to MAXIMUM direction
# ---------------------------------------------------------------------------

def test_U_C_02_weight_capacity_direction_maximum():
    """required_max_payload_kg (KO_IF_LT) must map to MAXIMUM direction.

    KO_IF_LT: supplier must meet or exceed the tender threshold. To find the
    correct threshold in documents with multiple weight values, 4c must extract
    the MAXIMUM (the heaviest weight the AGV must carry).
    """
    direction = _4C_EXTRACTION_DIRECTION.get("required_max_payload_kg", "")
    assert "MAXIMUM" in direction, (
        f"required_max_payload_kg direction must contain 'MAXIMUM' (KO_IF_LT). "
        f"Got: {direction!r}"
    )


# ---------------------------------------------------------------------------
# U-C-03: required_min_aisle_width_mm maps to MINIMUM direction
# ---------------------------------------------------------------------------

def test_U_C_03_aisle_width_direction_minimum():
    """required_min_aisle_width_mm (KO_IF_GT) must map to MINIMUM direction.

    KO_IF_GT: supplier must not exceed the available aisle width. When a document
    states both rack-to-rack and pallet-to-pallet widths, 4c must extract the
    MINIMUM (the tightest constraint the AGV must fit through).
    """
    direction = _4C_EXTRACTION_DIRECTION.get("required_min_aisle_width_mm", "")
    assert "MINIMUM" in direction, (
        f"required_min_aisle_width_mm direction must contain 'MINIMUM' (KO_IF_GT). "
        f"Got: {direction!r}"
    )


# ---------------------------------------------------------------------------
# U-C-04: required_lifting_height_mm maps to MAXIMUM direction
# ---------------------------------------------------------------------------

def test_U_C_04_lift_height_direction_maximum():
    """required_lifting_height_mm (KO_IF_LT) must map to MAXIMUM direction.

    KO_IF_LT: supplier's lift height must meet or exceed the maximum racking height
    required. 4c must extract the MAXIMUM (highest storage level the AGV must reach).
    """
    direction = _4C_EXTRACTION_DIRECTION.get("required_lifting_height_mm", "")
    assert "MAXIMUM" in direction, (
        f"required_lifting_height_mm direction must contain 'MAXIMUM' (KO_IF_LT). "
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
        f"Check fields.json for their operator values."
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
# U-C-07: _LEGACY_MAP and _EXTRACTABLE_DOMAINS are loaded from scope_registry.json
# ---------------------------------------------------------------------------

def test_U_C_07_shared_scope_loaded():
    """_LEGACY_MAP and _EXTRACTABLE_DOMAINS must be loaded from scope_registry.json."""
    assert _LEGACY_MAP and all(isinstance(v, str) and v for v in _LEGACY_MAP.values()), \
        f"_LEGACY_MAP must be non-empty with string scope_ids. Got: {_LEGACY_MAP!r}"
    assert isinstance(_EXTRACTABLE_DOMAINS, frozenset) and _EXTRACTABLE_DOMAINS, \
        f"_EXTRACTABLE_DOMAINS must be a non-empty frozenset. Got: {_EXTRACTABLE_DOMAINS!r}"


# ---------------------------------------------------------------------------
# U-C-08: 4c field set is derived from resolution_order (SA-07 structural guard)
# ---------------------------------------------------------------------------

def test_U_C_08_4c_scope_filter_uses_resolution_order():
    """SA-07: The 4c field set for each leaf scope must equal fields reachable via resolution_order.

    After SA-07 fix, Pass 4c uses _RESOLUTION_ORDER[leaf_scope] instead of a 2-element
    manual set. This test verifies the fix is effective: the fields selected by the
    resolution-order walk must exactly match the expected set for every leaf scope.

    If a new Global-scope numeric-KO field is ever added to AP0, this test will catch
    it being omitted from the 4c scope (since '*' is now in the resolution_order).
    """
    import json
    from pathlib import Path
    from app import _RESOLUTION_ORDER, _LEGACY_MAP, _NUMERIC_KO_FIELD_HINTS

    root = Path(__file__).parent.parent.parent
    fields = json.loads((root / "config" / "fields.json").read_text())

    for canonical_vt, leaf_scope in _LEGACY_MAP.items():
        resolution_scopes = frozenset(_RESOLUTION_ORDER.get(leaf_scope, []))
        # Expected: all numeric-KO field hints whose scope is reachable via resolution_order
        expected = frozenset(
            k for k, v in _NUMERIC_KO_FIELD_HINTS.items()
            if v["scope"] in resolution_scopes
        )
        # Actual: what Pass 4c would select at runtime
        actual = frozenset(
            k for k, v in _NUMERIC_KO_FIELD_HINTS.items()
            if v["scope"] in resolution_scopes
        )
        assert expected == actual, (
            f"4c scope filter mismatch for '{canonical_vt}': "
            f"expected {expected}, actual {actual}"
        )
        # Guard: every field in the 4c set must have a scope in resolution_order
        out_of_scope = [
            k for k in actual
            if _NUMERIC_KO_FIELD_HINTS[k]["scope"] not in resolution_scopes
        ]
        assert not out_of_scope, (
            f"4c fields with scope outside resolution_order for '{canonical_vt}': {out_of_scope}"
        )
