"""Unit tests for _find_invalid_ap0_fields from app.py (U-F-xx).

_find_invalid_ap0_fields is the pre-validation step used during the 4b retry loop.
It returns a dict of {tender_key: (bad_value, allowed_list)} for every field whose
LLM-extracted value does not match the AP0 allowed-values list.

Function signature: _find_invalid_ap0_fields(criteria: dict, skip: frozenset = frozenset()) -> dict
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from app import _find_invalid_ap0_fields


# ---------------------------------------------------------------------------
# U-F-01: 'OPC UA' (space) triggers a violation for required_integration_capability
# ---------------------------------------------------------------------------

def test_U_F_01_opc_ua_space_violation():
    """'OPC UA' with a space is not a valid AP0 integration value — must be in violations.

    AP0 allows 'OPC-UA' (hyphen). Space variant is a recurring LLM output
    (Mama, Nordlicht tenders). This check fires before the correction prompt is built.
    """
    violations = _find_invalid_ap0_fields({"required_integration_capability": "OPC UA"})
    assert "required_integration_capability" in violations, (
        "'OPC UA' must trigger a violation for required_integration_capability"
    )


# ---------------------------------------------------------------------------
# U-F-02: 'OPC-UA' (hyphen) does NOT trigger a violation
# ---------------------------------------------------------------------------

def test_U_F_02_opc_ua_hyphen_no_violation():
    """'OPC-UA' with a hyphen is valid — must NOT appear in violations."""
    violations = _find_invalid_ap0_fields({"required_integration_capability": "OPC-UA"})
    assert "required_integration_capability" not in violations, (
        "'OPC-UA' is a valid AP0 value and must not be reported as a violation"
    )


# ---------------------------------------------------------------------------
# U-F-03: None value is not flagged
# ---------------------------------------------------------------------------

def test_U_F_03_none_not_flagged():
    """None values must not appear in violations — only non-null values are checked."""
    violations = _find_invalid_ap0_fields({"required_integration_capability": None})
    assert "required_integration_capability" not in violations, (
        "None must not be flagged — absence of value is not a violation"
    )


# ---------------------------------------------------------------------------
# U-F-04: 'VDA 5050-kompatibel' triggers a violation for required_fleet_management_system
# ---------------------------------------------------------------------------

def test_U_F_04_vda5050_german_violation():
    """German 'VDA 5050-kompatibel' is not a valid AP0 fleet management value.

    AP0 allows 'VDA 5050 compatible' (English). LLM copies German string from documents.
    """
    violations = _find_invalid_ap0_fields(
        {"required_fleet_management_system": "VDA 5050-kompatibel"}
    )
    assert "required_fleet_management_system" in violations, (
        "German 'VDA 5050-kompatibel' must be flagged — AP0 requires 'VDA 5050 compatible'"
    )


# ---------------------------------------------------------------------------
# U-F-05: skip parameter excludes fields from violation check
# ---------------------------------------------------------------------------

def test_U_F_05_skip_excludes_field():
    """Fields in the `skip` frozenset must be excluded from violation checking.

    The skip parameter is used in Pass 4b to exclude fields already validated
    in Pass 4a (vehicle type, vna flag) from double-checking.
    """
    violations_without_skip = _find_invalid_ap0_fields(
        {"required_integration_capability": "OPC UA"}
    )
    assert "required_integration_capability" in violations_without_skip

    violations_with_skip = _find_invalid_ap0_fields(
        {"required_integration_capability": "OPC UA"},
        skip=frozenset({"required_integration_capability"}),
    )
    assert "required_integration_capability" not in violations_with_skip, (
        "Field in skip must not appear in violations"
    )


# ---------------------------------------------------------------------------
# U-F-06: violation dict contains (bad_value, allowed_list) tuple
# ---------------------------------------------------------------------------

def test_U_F_06_violation_value_structure():
    """Each violation entry must be a (bad_value_string, allowed_list) tuple."""
    violations = _find_invalid_ap0_fields(
        {"required_fleet_management_system": "VDA 5050-kompatibel"}
    )
    assert "required_fleet_management_system" in violations
    bad_val, allowed_list = violations["required_fleet_management_system"]
    assert isinstance(bad_val, str), f"bad_val must be a string, got {type(bad_val)}"
    assert isinstance(allowed_list, list), (
        f"allowed_list must be a list, got {type(allowed_list)}"
    )
    assert len(allowed_list) > 0, "allowed_list must be non-empty"
    # The allowed list should contain the English canonical value
    assert any("VDA 5050" in v for v in allowed_list), (
        f"allowed_list should contain 'VDA 5050 compatible'. Got: {allowed_list}"
    )
