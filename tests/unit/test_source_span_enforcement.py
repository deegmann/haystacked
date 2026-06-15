"""Unit tests for source-span enforcement logic (U-SS-xx).

Tests the Layer 1 and Layer 2 source-span enforcement invariants from app.py
(lines 711-730). The production loop is async/generator-bound, so we replicate
the core logic here as a pure function to make it testable without an HTTP server.

The enforcement loop in app.py is:
    for _key in _NUMERIC_KO_TENDER_KEYS:
        if agv_criteria.get(_key) is None:
            continue
        _src_val = agv_criteria.get(f"{_key}_source")
        if not _src_val:
            # Layer 1: no source → null value
            agv_criteria[_key] = None
        elif _key in _4c_abstained_ref and not _source_confirms_value(agv_criteria[_key], str(_src_val)):
            # Layer 2: 4c abstained AND source doesn't confirm → null value
            agv_criteria[_key] = None

We replicate this loop inline (not importing from app.py) to avoid async dependencies.
All domain knowledge (field list, scv function) comes from the production modules.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import _NUMERIC_KO_TENDER_KEYS
from src.json_repair import source_confirms_value


def _apply_source_span_enforcement(
    criteria: dict,
    _4c_abstained: set,
    _4c_active: bool = True,
) -> dict:
    """Replicated source-span enforcement logic from app.py lines 711-730.

    Pure function — no side effects, no SSE, no logging.
    Operates on a copy of `criteria`.

    Args:
        criteria: dict with tender field values and <field>_source companions.
        _4c_abstained: set of tender_keys for which Pass 4c returned null.
        _4c_active: if False, Layer 2 is inactive (mirrors _4c_abstained_ref = set()).
    """
    result = dict(criteria)
    _4c_abstained_ref = _4c_abstained if _4c_active else set()

    for _key in _NUMERIC_KO_TENDER_KEYS:
        if result.get(_key) is None:
            continue
        _src_val = result.get(f"{_key}_source")
        if not _src_val:
            # Layer 1
            result[_key] = None
        elif _key in _4c_abstained_ref and not source_confirms_value(
            result[_key], str(_src_val)
        ):
            # Layer 2
            result[_key] = None

    return result


# ---------------------------------------------------------------------------
# U-SS-01: L1 — value set + source is None → value becomes None
# ---------------------------------------------------------------------------

def test_U_SS_01_l1_source_none_nulls_value():
    """Layer 1: if the source field is None, the value must be nulled.

    No citation = LLM inference. Layer 1 enforces that every numeric KO value
    must have an explicit source string.
    """
    key = "required_weight_capacity_kg"
    criteria = {
        key: 1000,
        f"{key}_source": None,
    }
    result = _apply_source_span_enforcement(criteria, _4c_abstained=set())
    assert result[key] is None, (
        f"L1: {key}=1000 with source=None must be nulled"
    )


# ---------------------------------------------------------------------------
# U-SS-02: L1 — value set + source is empty string → value becomes None
# ---------------------------------------------------------------------------

def test_U_SS_02_l1_source_empty_string_nulls_value():
    """Layer 1: if the source field is an empty string, the value must be nulled.

    An empty string is falsy in Python and treated the same as None.
    """
    key = "required_weight_capacity_kg"
    criteria = {
        key: 1000,
        f"{key}_source": "",
    }
    result = _apply_source_span_enforcement(criteria, _4c_abstained=set())
    assert result[key] is None, (
        f"L1: {key}=1000 with source='' must be nulled"
    )


# ---------------------------------------------------------------------------
# U-SS-03: L1 — value set + source is non-empty string → value unchanged
# ---------------------------------------------------------------------------

def test_U_SS_03_l1_source_present_value_unchanged():
    """Layer 1: if source is a non-empty string, the value must NOT be nulled by L1.

    L1 only fires on absent/null sources. A non-empty source passes L1.
    """
    key = "required_weight_capacity_kg"
    criteria = {
        key: 1000,
        f"{key}_source": "Max Loaded weight (KG) (Footprint) 1000",
    }
    result = _apply_source_span_enforcement(criteria, _4c_abstained=set())
    assert result[key] == 1000, (
        f"L1: {key}=1000 with a non-empty source must remain 1000"
    )


# ---------------------------------------------------------------------------
# U-SS-04: L2 — field in 4c_abstained AND source does NOT confirm → value becomes None
# ---------------------------------------------------------------------------

def test_U_SS_04_l2_abstained_bad_source_nulls_value():
    """Layer 2: 4c abstained + source doesn't confirm the value → null.

    This is the Dragonfly lift-height case: 4b extracted 6.0 with source
    'Outbound 1734 / Replenishment 133' (which doesn't contain 6 or 6000).
    4c also abstained. Layer 2 correctly nulls the hallucination.
    """
    key = "required_max_lift_height_m"
    bad_source = "Outbound 1734\nReplenishment (also halfs and to aisle 60 area) 133"
    criteria = {
        key: 6.0,
        f"{key}_source": bad_source,
    }
    result = _apply_source_span_enforcement(
        criteria,
        _4c_abstained={key},
    )
    assert result[key] is None, (
        f"L2: {key}=6.0 with non-confirming source must be nulled when 4c abstained"
    )


# ---------------------------------------------------------------------------
# U-SS-05: L2 — field in 4c_abstained AND source confirms → value unchanged
# ---------------------------------------------------------------------------

def test_U_SS_05_l2_abstained_good_source_value_unchanged():
    """Layer 2: 4c abstained but source DOES confirm the value → value kept.

    This is the Dragonfly weight-capacity case: 4c abstained because it
    misidentified the table row. 4b correctly extracted 1000 with source
    'Max Loaded weight (KG) (Footprint) 1000'. Layer 2 confirms 1000 is in
    the source → value kept.
    """
    key = "required_weight_capacity_kg"
    good_source = "Max Loaded weight (KG) (Footprint) 1000"
    criteria = {
        key: 1000,
        f"{key}_source": good_source,
    }
    result = _apply_source_span_enforcement(
        criteria,
        _4c_abstained={key},
    )
    assert result[key] == 1000, (
        f"L2: {key}=1000 with confirming source must be kept even when 4c abstained"
    )


# ---------------------------------------------------------------------------
# U-SS-06: L2 — field NOT in 4c_abstained → Layer 2 does not fire
# ---------------------------------------------------------------------------

def test_U_SS_06_l2_not_abstained_bad_source_value_kept():
    """Layer 2 must NOT fire for fields that are NOT in _4c_abstained.

    If 4c returned a non-null value (field not in _4c_abstained), L2 is skipped
    regardless of whether the source confirms the value. Only the 4c result is used.
    The source check is only a fallback for 4c abstentions.
    """
    key = "required_max_lift_height_m"
    bad_source = "Outbound 1734\nReplenishment 133"  # does not contain 6 or 6000
    criteria = {
        key: 6.0,
        f"{key}_source": bad_source,
    }
    # Field is NOT in _4c_abstained
    result = _apply_source_span_enforcement(
        criteria,
        _4c_abstained=set(),  # empty set — field not abstained
    )
    assert result[key] == 6.0, (
        f"L2 must not fire when field is not in _4c_abstained. "
        f"{key}=6.0 must be kept."
    )


# ---------------------------------------------------------------------------
# U-SS-07: None value skipped entirely — neither L1 nor L2 fires
# ---------------------------------------------------------------------------

def test_U_SS_07_none_value_skipped():
    """If the value is already None, the enforcement loop skips the field entirely.

    Neither L1 nor L2 should do anything when the value is already null.
    The _source field (even if absent) must not cause an error.
    """
    key = "required_max_lift_height_m"
    criteria = {
        key: None,
        # source field absent entirely
    }
    result = _apply_source_span_enforcement(
        criteria,
        _4c_abstained={key},
    )
    assert result[key] is None, (
        "Already-null value must remain null and not raise an error"
    )


# ---------------------------------------------------------------------------
# U-SS-08: L2 inactive when 4c was not run (_4c_active=False)
# ---------------------------------------------------------------------------

def test_U_SS_08_l2_inactive_when_4c_not_run():
    """When _4c_active=False (4c fields set is empty), Layer 2 must not fire.

    In app.py: _4c_abstained_ref = _4c_abstained if _4c_fields else set()
    When _4c_fields is empty (4c not run for this vehicle type), _4c_abstained_ref
    is forced to empty set → L2 cannot fire for any field.
    """
    key = "required_max_lift_height_m"
    bad_source = "Outbound 1734\nReplenishment 133"
    criteria = {
        key: 6.0,
        f"{key}_source": bad_source,
    }
    result = _apply_source_span_enforcement(
        criteria,
        _4c_abstained={key},
        _4c_active=False,  # 4c was not run
    )
    assert result[key] == 6.0, (
        "L2 must be inactive when 4c was not run (_4c_active=False). "
        "Value must be kept despite bad source."
    )
