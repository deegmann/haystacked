"""Unit tests for validate_tender_values (U-V-xx) from src/matching.py.

Tests AP0 allowed-value filtering: substring containment, case-insensitive
matching, multi-value splitting, and None passthrough.

Function location: src/matching.py::validate_tender_values
Called from app.py line ~738 after Pass 4b/4c extraction.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from src.matching import validate_tender_values


# ---------------------------------------------------------------------------
# U-V-01: OPC UA (space) is rejected after Step 6 — only 'OPC-UA' is canonical
# ---------------------------------------------------------------------------

def test_U_V_01_opc_ua_space_rejected_post_step6():
    """Step 6: 'OPC UA' (with space) is no longer a valid AP0 integration value.

    The 'OPC UA' alias (added in OI-32) was removed in Step 6 allowed_values cleanup.
    Only 'OPC-UA' (hyphen) is now canonical. 'OPC UA' must be rejected with a warning.
    """
    result, warnings = validate_tender_values({"required_integration_capability": "OPC UA"})
    assert result.get("required_integration_capability") is None, (
        "'OPC UA' (space) is no longer an AP0 alias after Step 6 — must be rejected"
    )
    assert warnings, f"A warning must be emitted for rejected value 'OPC UA'"


# ---------------------------------------------------------------------------
# U-V-02: OPC-UA (hyphen) is accepted
# ---------------------------------------------------------------------------

def test_U_V_02_opc_ua_hyphen_accepted():
    """'OPC-UA' (with hyphen) is the canonical AP0 value and must pass through."""
    result, warnings = validate_tender_values({"required_integration_capability": "OPC-UA"})
    assert result.get("required_integration_capability") == "OPC-UA", (
        "'OPC-UA' (hyphen) is a valid AP0 value and must not be filtered out"
    )
    assert not warnings, f"Unexpected warnings for valid value: {warnings}"


# ---------------------------------------------------------------------------
# U-V-03: REST / OPC UA compound string — split on ' / ', OPC UA now rejected (Step 6)
# ---------------------------------------------------------------------------

def test_U_V_03_rest_opc_ua_compound_split_post_step6():
    """Step 6: 'REST / OPC UA' is split on ' / ' into ['REST', 'OPC UA'].
    'REST' passes (substring-matches 'REST API'). 'OPC UA' is now rejected
    (no longer an AP0 alias after Step 6 allowed_values cleanup).

    Result contains only 'REST'; a warning is emitted for 'OPC UA'.
    OI-61 slash-split behavior is still active and still necessary.
    """
    result, warnings = validate_tender_values({"required_integration_capability": "REST / OPC UA"})
    val = result.get("required_integration_capability", "")
    parts = [p.strip() for p in val.split(",") if p.strip()] if val else []
    assert len(parts) == 1, f"Expected 1 valid part after split (OPC UA rejected), got: {parts!r}"
    assert "rest" in parts[0].lower(), f"'REST' part missing from {parts}"
    assert warnings, "Expected a warning for rejected 'OPC UA'"


# ---------------------------------------------------------------------------
# U-V-04: VDA 5050-kompatibel (German string) is rejected
# ---------------------------------------------------------------------------

def test_U_V_04_vda5050_german_string_rejected():
    """German 'VDA 5050-kompatibel' is not a valid AP0 fleet management value.

    AP0 allows 'VDA 5050 compatible' (English). The LLM copies the German string
    from tender documents. Must be rejected with a warning.
    """
    result, warnings = validate_tender_values(
        {"required_fleet_management_system": "VDA 5050-kompatibel"}
    )
    assert result.get("required_fleet_management_system") is None, (
        "German 'VDA 5050-kompatibel' must be rejected — AP0 uses 'VDA 5050 compatible'"
    )
    assert warnings, "Expected a warning for 'VDA 5050-kompatibel'"


# ---------------------------------------------------------------------------
# U-V-05: 'Floor delivery & picking' for required_load_type is rejected
# ---------------------------------------------------------------------------

def test_U_V_05_floor_delivery_picking_rejected():
    """'Floor delivery & picking' is not a valid AP0 load_types value.

    AP0 allows: Pallet EUR, Pallet ISO, Tote, Roll Container, Custom Carrier, None.
    The LLM sometimes returns 'Floor delivery & picking' from tender documents.
    """
    result, warnings = validate_tender_values(
        {"required_load_type": "Floor delivery & picking"}
    )
    assert result.get("required_load_type") is None, (
        "'Floor delivery & picking' must be rejected by AP0 load_types filter"
    )
    assert warnings


# ---------------------------------------------------------------------------
# U-V-06: 'Pallet EUR' is accepted
# ---------------------------------------------------------------------------

def test_U_V_06_pallet_eur_accepted():
    """'Pallet EUR' is a canonical AP0 load_types value and must be accepted."""
    result, warnings = validate_tender_values({"required_load_type": "Pallet EUR"})
    assert result.get("required_load_type") == "Pallet EUR", (
        "'Pallet EUR' is a valid AP0 value and must pass through"
    )
    assert not warnings, f"Unexpected warnings: {warnings}"


# ---------------------------------------------------------------------------
# U-V-07: None passes through unchanged, no warnings
# ---------------------------------------------------------------------------

def test_U_V_07_none_passthrough():
    """None values must pass through validate_tender_values without warnings.

    A None value means the LLM did not extract the field. It must not be
    transformed or generate warnings — only non-null invalid values are reported.
    """
    result, warnings = validate_tender_values({
        "required_integration_capability": None,
        "required_fleet_management_system": None,
        "required_load_type": None,
    })
    assert result.get("required_integration_capability") is None
    assert result.get("required_fleet_management_system") is None
    assert result.get("required_load_type") is None
    assert not warnings, f"None values must not generate warnings, got: {warnings}"


# ---------------------------------------------------------------------------
# U-V-08: Substring match behaviour — 'Pallet' accepted via substring containment
# ---------------------------------------------------------------------------

def test_U_V_08_substring_match_pallet():
    """'Pallet' is accepted because 'pallet' is a substring of 'pallet eur' and 'pallet iso'.

    Documents the substring containment semantics of validate_tender_values:
    line 104 in src/matching.py uses `vl in al or al in vl`.
    This means a shorter input can match a longer allowed value.

    Note: 'Pallet' survives the AP0 filter but does NOT match supplier load_types
    exactly in the KO_SUBSET operator — it may still cause mismatches downstream.
    """
    result, warnings = validate_tender_values({"required_load_type": "Pallet"})
    assert result.get("required_load_type") == "Pallet", (
        "'Pallet' is accepted because 'pallet' is a substring of AP0 value 'pallet eur'. "
        "Substring containment is bidirectional: `vl in al or al in vl`."
    )
    assert not warnings, (
        "'Pallet' triggers no warning — it passes the AP0 filter via substring match"
    )


# ---------------------------------------------------------------------------
# U-V-09: OI-61 — slash-separated compound strings are split before validation
# ---------------------------------------------------------------------------

def test_U_V_09_slash_compound_split_into_valid_parts():
    """OI-61: ' / ' separator is normalised before AP0 validation. Step 6 update.

    Before OI-61 fix: compound strings like 'REST / OPC UA' passed the AP0 filter
    as a single opaque string, causing KO_SUBSET mismatches.

    After OI-61 fix + Step 6: the string is split on ' / '; each part is individually
    validated. 'REST' passes (matches 'REST API' via substring). 'OPC UA' is now
    rejected (removed from AP0 allowed_values in Step 6). Result is 'REST' with
    a warning for the rejected 'OPC UA' part.
    """
    result, warnings = validate_tender_values(
        {"required_integration_capability": "REST / OPC UA"}
    )
    val = result.get("required_integration_capability", "")
    parts = [p.strip() for p in val.split(",") if p.strip()] if val else []
    assert len(parts) == 1, (
        f"Expected 1 valid part after split (OPC UA rejected post-Step6), got {parts!r}. "
        "The ' / ' separator must be normalised before AP0 validation."
    )
    assert "rest" in parts[0].lower(), f"'REST' part missing from {parts}"
    assert warnings, "Expected a warning for rejected 'OPC UA' part"


# ---------------------------------------------------------------------------
# U-V-10: OI-95 — required_product_type is exempted from AP0 allowed-values
# filtering via the AP0-derived post_extraction_derived flag (_SKIP_FILTER).
# ---------------------------------------------------------------------------

def test_U_V_10_required_product_type_exempted_from_filter():
    """required_product_type is normalized by app.py (vehicle-type classification
    pipeline) after extraction — it must pass through validate_tender_values()
    unfiltered even when the raw LLM output is not a literal AP0 allowed value.
    """
    result, warnings = validate_tender_values(
        {"required_product_type": "vna forklift (not a canonical AP0 value)"}
    )
    assert result.get("required_product_type") == "vna forklift (not a canonical AP0 value)", (
        "required_product_type must be exempted from AP0 allowed-values filtering "
        "(post_extraction_derived=True in AP0 xlsx)"
    )
    assert not warnings, f"Unexpected warnings for exempted field: {warnings}"


def test_U_V_11_negative_control_other_dropdown_still_filtered():
    """Negative control: a field NOT flagged post_extraction_derived is still
    subject to normal AP0 allowed-values filtering (i.e. the skip is scoped
    to the flagged field only, not a blanket bypass)."""
    result, warnings = validate_tender_values(
        {"required_load_type": "Floor delivery & picking"}
    )
    assert result.get("required_load_type") is None, (
        "Fields without post_extraction_derived=True must still be filtered normally"
    )
    assert warnings, "Expected a warning for the disallowed value on a non-exempted field"
