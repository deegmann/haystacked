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
# U-V-01: OPC UA (space) is rejected — not in AP0 allowed list
# ---------------------------------------------------------------------------

def test_U_V_01_opc_ua_space_rejected():
    """'OPC UA' (with space) is not a valid AP0 integration value.

    AP0 allows 'OPC-UA' (hyphen). A space variant is a known LLM fragility
    (Mama and Nordlicht tenders). Must be set to None with a warning.
    """
    result, warnings = validate_tender_values({"required_integration_capability": "OPC UA"})
    assert result.get("required_integration_capability") is None, (
        "'OPC UA' (space) must be rejected — AP0 requires 'OPC-UA' (hyphen)"
    )
    assert any("OPC UA" in w for w in warnings), (
        "Expected a warning for 'OPC UA' not in AP0 allowed values"
    )


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
# U-V-03: REST / OPC UA compound string is rejected
# ---------------------------------------------------------------------------

def test_U_V_03_rest_opc_ua_compound_rejected():
    """'REST / OPC UA' is a compound string not matching any AP0 allowed value.

    The Nordlicht tender returns this string from the LLM. Neither 'REST / OPC UA'
    nor its parts match an AP0 entry ('REST API' and 'OPC-UA' are separate allowed
    values, but the compound string fails substring containment from the wrong direction).
    """
    result, warnings = validate_tender_values({"required_integration_capability": "REST / OPC UA"})
    assert result.get("required_integration_capability") is None, (
        "'REST / OPC UA' compound must be rejected by AP0 filter"
    )
    assert any("REST / OPC UA" in w or "REST" in w for w in warnings)


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
