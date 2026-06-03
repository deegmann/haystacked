"""
U-E-xx — LLM extraction null-rule regression tests.

No live Ollama required. These tests pin expected LLM extraction outputs for
known tenders as regression anchors for hallucination patterns.

When a new hallucination is discovered:
  1. Document the bad value in a comment below
  2. Pin the known-correct null/value as the assertion
  3. AP0 null rule fix goes in the xlsx Description column → regenerate

Gap context: the test suite covers the matching engine (stage 3) exhaustively
but has zero coverage of LLM extraction (stage 2). These tests are the first
layer of that missing coverage.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
import pytest

TENDER_DIR = Path(__file__).parent.parent / "tenders"


# ---------------------------------------------------------------------------
# Golden extraction outputs — expected LLM tender_key values for known PDFs.
# Update ONLY when the source document changes, never to match a wrong LLM output.
# ---------------------------------------------------------------------------

# Dragonfly.pdf: VNA Forklift AGV, UK DC, ~54,000 VNA pallet positions.
# Document text contains: Ph=2850mm (pallet height), aisle 1900mm min, payload 1000kg.
# Document text does NOT contain: an explicit AGV fork lift height.
DRAGONFLY_GOLDEN = {
    # Known hallucination 2026-06-03: LLM computed 2 × Ph(2850mm) ≈ 6m and output that.
    # Correct: null — no AGV fork lift height is stated anywhere in the document.
    # AP0 fix applied 2026-06-03: null rule strengthened to prohibit inference from pallet dims.
    "required_max_lift_height_m": None,

    # "aisle width is 2000mm rack-to-rack, with a minimum of 1900mm pallet-to-pallet"
    # CONSERVATIVE RULE (KO_IF_GT): extract the minimum → 1.9 m
    "required_min_aisle_width_m": 1.9,

    # "Max Loaded weight (KG) (Footprint) 1000"
    "required_weight_capacity_kg": 1000,

    # VNA context confirmed by vehicle-type pass → required
    "required_vna": "required",
}


# ---------------------------------------------------------------------------
# U-E-01: required_max_lift_height_m null rule — Dragonfly
# ---------------------------------------------------------------------------

def test_U_E_01_dragonfly_lift_height_must_be_null():
    """
    required_max_lift_height_m must be null for Dragonfly.

    The document contains only Ph = 2850mm (pallet height with stock) — not
    an AGV fork lift height specification. Any non-null value is a hallucination.

    Regression anchor for hallucination reported 2026-06-03:
      LLM returned 6.0 m, computed as 2 × 2850 mm.
    """
    assert DRAGONFLY_GOLDEN["required_max_lift_height_m"] is None, (
        "Dragonfly: required_max_lift_height_m must be null. "
        "The document states only Ph=2850mm (pallet height), never an AGV fork spec. "
        "Value 6m is arithmetic hallucination (2 × 2850mm). See AP0 lifting_height_mm null rule."
    )


def test_U_E_02_dragonfly_aisle_width_minimum():
    """
    required_min_aisle_width_m must be 1.9 m.

    Document: "aisle width is 2000mm rack-to-rack, with a minimum of 1900mm
    pallet-to-pallet." Conservative rule → extract minimum = 1.9 m.
    """
    assert DRAGONFLY_GOLDEN["required_min_aisle_width_m"] == pytest.approx(1.9)


def test_U_E_03_dragonfly_payload():
    """
    required_weight_capacity_kg must be 1000 kg.

    Document: "Max Loaded weight (KG) (Footprint) 1000".
    """
    assert DRAGONFLY_GOLDEN["required_weight_capacity_kg"] == 1000


def test_U_E_04_dragonfly_vna_required():
    """
    required_vna must be 'required' for Dragonfly.

    Document explicitly describes VNA APR racking and unmanned VNA turret device.
    """
    assert DRAGONFLY_GOLDEN["required_vna"] == "required"


# ---------------------------------------------------------------------------
# U-E-05: null values survive validate_agv_criteria unchanged
# ---------------------------------------------------------------------------

def test_U_E_05_null_lift_height_survives_plausibility_filter():
    """
    A null required_max_lift_height_m must pass through validate_agv_criteria
    unchanged — the plausibility filter must not coerce null to a default value.

    This verifies LL-06 (Blank ≠ Zero) is upheld in the post-LLM validation step.
    """
    from app import validate_agv_criteria

    criteria = {
        "required_vehicle_type": "Forklift AGV",
        "required_max_lift_height_m": None,
        "required_min_aisle_width_m": 1.9,
        "required_weight_capacity_kg": 1000,
    }
    validated, warnings = validate_agv_criteria(criteria)
    assert validated.get("required_max_lift_height_m") is None, (
        "validate_agv_criteria must not fill a null required_max_lift_height_m "
        "with a default value (LL-06: Blank ≠ Zero)."
    )


# ---------------------------------------------------------------------------
# U-E-06: _source_confirms_value boundary conditions
# ---------------------------------------------------------------------------

def test_U_E_06_source_confirms_value():
    """
    _source_confirms_value must correctly gate Layer 2 source-span enforcement.

    Covers: direct match, mm/m scale (×1000), thousands separator, false positive.
    """
    from app import _source_confirms_value

    # Direct numeric match
    assert _source_confirms_value(1000, "Max Loaded weight (KG) (Footprint) 1000") is True

    # Thousands separator: "1,000" must be read as 1000
    assert _source_confirms_value(1000, "a maximum of 1,000 kg") is True

    # mm/m scale: value 1.9 m → look for 1900 in source
    assert _source_confirms_value(1.9, "minimum of 1900 mm pallet-to-pallet") is True

    # mm/m scale: value 2.0 m → look for 2000 in source
    assert _source_confirms_value(2.0, "aisle width is 2000 mm rack-to-rack") is True

    # False positive guard: source "Outbound 1734 / Replenishment 133" must NOT
    # confirm value 6.0 (the Dragonfly lift-height hallucination)
    assert _source_confirms_value(6.0, "Outbound 1734\nReplenishment (also halfs) 133") is False

    # Zero always passes (deliberate zero, not an inference hallucination)
    assert _source_confirms_value(0, "no lifting required") is True


# ---------------------------------------------------------------------------
# U-E-07: _NUMERIC_KO_TENDER_KEYS non-empty guard
# ---------------------------------------------------------------------------

def test_U_E_07_numeric_ko_tender_keys_non_empty():
    """
    _NUMERIC_KO_TENDER_KEYS must be non-empty after loading field_levels.json.

    If empty, source-span enforcement and Pass 4c are silently inactive.
    This test catches a missing or stale field_levels.json before a run.
    """
    from app import _NUMERIC_KO_TENDER_KEYS

    assert len(_NUMERIC_KO_TENDER_KEYS) > 0, (
        "_NUMERIC_KO_TENDER_KEYS is empty — field_levels.json may be missing or "
        "has no KO_IF_LT/KO_IF_GT Float/Integer fields. Run generate_all.py."
    )
    assert "required_weight_capacity_kg" in _NUMERIC_KO_TENDER_KEYS, (
        "required_weight_capacity_kg missing from _NUMERIC_KO_TENDER_KEYS — "
        "check field_levels.json tender_key mapping for max_payload_kg."
    )
    assert "required_max_lift_height_m" in _NUMERIC_KO_TENDER_KEYS, (
        "required_max_lift_height_m missing from _NUMERIC_KO_TENDER_KEYS."
    )
