"""Tests for /rematch endpoint and /api/field-meta allowed_values.

Tests:
  - test_rematch_unknown_analysis_id: POST /rematch with unknown analysis_id → 400
  - test_rematch_allowed_values_in_field_meta: GET /api/field-meta returns
      non-empty allowed_values for a known Multi-Select field;
      a Float field has allowed_values absent or null.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure the project root is on the path so 'app' can be imported
_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from app import app
import app as _app_module

client = TestClient(app)


def test_rematch_unknown_analysis_id():
    """POST /rematch with an unknown analysis_id must return HTTP 400."""
    response = client.post(
        "/rematch",
        json={"analysis_id": "00000000-0000-0000-0000-000000000000", "overrides": {}},
    )
    assert response.status_code == 400, (
        f"Expected 400 for unknown analysis_id, got {response.status_code}: {response.text}"
    )


def test_rematch_allowed_values_in_field_meta():
    """GET /api/field-meta must include non-empty allowed_values for Multi-Select/Dropdown
    fields and null (or absent) allowed_values for Float fields.

    Uses navigation_type (Multi-Select, KO_SUBSET) and max_payload (Float, KO_IF_LT)
    as concrete examples — both are stable AP0 fields that will not disappear.
    """
    response = client.get("/api/field-meta")
    assert response.status_code == 200, (
        f"GET /api/field-meta failed: {response.status_code}"
    )
    meta = response.json()

    # Multi-Select field must have non-empty allowed_values
    nav_entry = meta.get("navigation_type")
    assert nav_entry is not None, "navigation_type must be present in /api/field-meta"
    av = nav_entry.get("allowed_values")
    assert isinstance(av, list) and len(av) > 0, (
        f"navigation_type.allowed_values should be a non-empty list, got: {av!r}"
    )

    # Float KO field must have allowed_values absent or null (not a list)
    payload_entry = meta.get("max_payload")
    assert payload_entry is not None, "max_payload must be present in /api/field-meta"
    float_av = payload_entry.get("allowed_values")
    assert float_av is None, (
        f"max_payload.allowed_values should be null for a Float field, got: {float_av!r}"
    )


def test_rematch_happy_path_override_changes_match_count():
    """POST /rematch with an extreme max_payload override must KO all suppliers
    with a real payload value, leaving only null-payload suppliers qualified.

    max_payload maps to tender_key required_max_payload (KO_IF_LT).
    Setting it to 45000 kg KOs every supplier with a real payload (all <= 5000 kg).
    Value must stay within plausibility range [100–50000 kg] — values above that
    are silently dropped by validate_domain_criteria and no KOs fire.
    Suppliers with max_payload = NULL survive (null-rule LL-06) but get -15 pt penalty.
    DB-agnostic: asserts structural behavior (majority KO'd) rather than exact counts.
    """
    test_id = str(uuid.uuid4())
    _app_module._analyses[test_id] = {"analysis_id": test_id, "domain_criteria": {}}
    try:
        response = client.post(
            "/rematch",
            json={"analysis_id": test_id, "overrides": {"max_payload": 45000}},
        )
        assert response.status_code == 200
        data = response.json()
        assert set(data.keys()) >= {"top", "all", "total", "analysis_id"}
        assert data["analysis_id"] == test_id
        assert data["total"] > 0
        assert "top" in data and "all" in data
        qualified = sum(1 for r in data["all"] if not r["disqualified"])
        disqualified = sum(1 for r in data["all"] if r["disqualified"])
        assert qualified >= 0
        assert disqualified > 0          # extreme threshold must KO at least some suppliers
        assert disqualified > qualified  # extreme threshold KOs the majority
        assert len(data["top"]) <= 10
    finally:
        _app_module._analyses.pop(test_id, None)


def test_rematch_unknown_override_key_does_not_crash():
    """POST /rematch with an unrecognised override key must return HTTP 200
    and have zero effect on match results.

    Mechanism: _FIELDS_BY_FIELD_NAME.get('bogus_field_xyz', []) -> []; the key falls
    back to itself as tender_key; the rule engine finds no matching rule and
    ignores it; all suppliers remain qualified regardless of DB count.
    """
    test_id = str(uuid.uuid4())
    _app_module._analyses[test_id] = {"analysis_id": test_id, "domain_criteria": {}}
    try:
        response = client.post(
            "/rematch",
            json={"analysis_id": test_id, "overrides": {"bogus_field_xyz": 42}},
        )
        assert response.status_code == 200
        data = response.json()
        assert set(data.keys()) >= {"top", "all", "total", "analysis_id"}
        assert data["total"] > 0
        qualified = sum(1 for r in data["all"] if not r["disqualified"])
        assert qualified == data["total"]   # bogus key has zero effect — all suppliers qualify

        # bogus key lands in criteria under its own name — doesn't pollute real AP0 keys
        updated = _app_module._analyses[test_id].get("domain_criteria", {})
        assert "bogus_field_xyz" in updated
        assert "required_max_payload" not in updated
    finally:
        _app_module._analyses.pop(test_id, None)


def test_rematch_lift_height_override_applies_mm_conversion():
    """POST /rematch with lift-height override in meters must apply m→mm conversion before matching.

    required_lifting_height is KO_IF_LT — supplier lift height must be >= tender requirement.
    Override: 8 m = 8000 mm. Suppliers with lift_height < 8000 must be disqualified.
    If conversion is missing: 8 is compared against mm values (~12000) → nobody KO'd.
    If conversion is correct: 8000 compared → suppliers below threshold correctly KO'd.
    """
    test_id = str(uuid.uuid4())
    _app_module._analyses[test_id] = {"analysis_id": test_id, "domain_criteria": {}}
    try:
        response = client.post(
            "/rematch",
            json={"analysis_id": test_id, "overrides": {"required_lifting_height": 8}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] > 0

        disqualified = sum(1 for r in data["all"] if r["disqualified"])
        qualified    = sum(1 for r in data["all"] if not r["disqualified"])
        assert disqualified > 0, (
            "No suppliers disqualified — unit conversion likely missing "
            "(8 compared as 8 instead of 8000 mm)"
        )
        assert qualified > 0, "All suppliers disqualified — conversion may be inverted"
        assert data["analysis_id"] == test_id
    finally:
        _app_module._analyses.pop(test_id, None)


def test_rematch_aisle_width_override_applies_mm_conversion():
    """POST /rematch with aisle-width override in meters must apply m→mm conversion before matching.

    required_min_aisle_width is KO_IF_GT — supplier aisle width must be <= tender requirement.
    Override: 1.8 m = 1800 mm. Suppliers with min_aisle_width > 1800 must be disqualified.
    If conversion is missing: 1.8 is compared against mm values (~2700) → everyone KO'd (wrong).
    If conversion is correct: 1800 compared → appropriate mix of qualified/disqualified.
    """
    test_id = str(uuid.uuid4())
    _app_module._analyses[test_id] = {"analysis_id": test_id, "domain_criteria": {}}
    try:
        response = client.post(
            "/rematch",
            json={"analysis_id": test_id, "overrides": {"required_min_aisle_width": 1.8}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] > 0

        disqualified = sum(1 for r in data["all"] if r["disqualified"])
        qualified    = sum(1 for r in data["all"] if not r["disqualified"])
        assert disqualified > 0, (
            "No suppliers disqualified — unit conversion likely missing "
            "(1.8 compared as 1.8 instead of 1800 mm)"
        )
        assert qualified > 0, "All suppliers disqualified — conversion may be inverted"
        assert data["analysis_id"] == test_id
    finally:
        _app_module._analyses.pop(test_id, None)


def test_rematch_vt_change_clears_old_vt_fields():
    """POST /rematch with a VT change clears Tugger-specific fields but preserves shared fields.

    required_towing_capacity is Tugger AGV-specific (sheet='Tugger AGV').
    required_max_payload is shared (sheet='SHARED – All AGV Types').
    Changing from Tugger AGV to Forklift AGV must delete the Tugger-specific field
    and preserve the shared field. required_vna_capable must be set to None.
    """
    test_id = str(uuid.uuid4())
    _app_module._analyses[test_id] = {
        "analysis_id": test_id,
        "vehicle_type_canonical": "Tugger AGV",
        "domain_criteria": {
            "required_towing_capacity": 1000,
            "required_max_payload": 500,
        },
    }
    try:
        response = client.post(
            "/rematch",
            json={
                "analysis_id": test_id,
                "overrides": {},
                "vehicle_type": "Forklift AGV",
            },
        )
        assert response.status_code == 200
        updated = _app_module._analyses[test_id]["domain_criteria"]
        assert "required_towing_capacity" not in updated, (
            "Tugger-specific field must be cleared on VT change to Forklift AGV"
        )
        assert "required_max_payload" in updated, (
            "Shared field must be preserved on VT change"
        )
        assert _app_module._analyses[test_id]["vehicle_type_canonical"] == "Forklift AGV"
        assert updated.get("required_vna_capable") is None, (
            "required_vna_capable must be None after VT change"
        )
    finally:
        _app_module._analyses.pop(test_id, None)


def test_rematch_vt_change_forklift_to_tugger_clears_forklift_fields():
    """POST /rematch with a VT change from Forklift AGV to Tugger AGV clears Forklift-specific fields.

    required_lifting_height is Forklift-specific (sheet='Forklift AGV').
    required_max_payload is shared (sheet='SHARED – All AGV Types').
    Changing to Tugger AGV must delete the Forklift-specific field and preserve the shared one.
    required_vna_capable must be set to None.
    """
    test_id = str(uuid.uuid4())
    _app_module._analyses[test_id] = {
        "analysis_id": test_id,
        "vehicle_type_canonical": "Forklift AGV",
        "domain_criteria": {
            "required_lifting_height": 8.0,
            "required_max_payload": 1000,
        },
    }
    try:
        response = client.post(
            "/rematch",
            json={
                "analysis_id": test_id,
                "overrides": {},
                "vehicle_type": "Tugger AGV",
            },
        )
        assert response.status_code == 200
        updated = _app_module._analyses[test_id]["domain_criteria"]
        assert "required_lifting_height" not in updated, (
            "Forklift-specific field must be cleared on VT change to Tugger AGV"
        )
        assert "required_max_payload" in updated, (
            "Shared field must be preserved on VT change"
        )
        assert updated.get("required_vna_capable") is None, (
            "required_vna_capable must be None after VT change"
        )
    finally:
        _app_module._analyses.pop(test_id, None)


def test_rematch_same_vt_does_not_clear_criteria():
    """POST /rematch without a VT change must not clear any criteria fields.

    When vehicle_type is not supplied in the request body, no clearing occurs
    and all existing criteria fields are preserved unchanged.
    """
    test_id = str(uuid.uuid4())
    _app_module._analyses[test_id] = {
        "analysis_id": test_id,
        "vehicle_type_canonical": "Forklift AGV",
        "domain_criteria": {
            "required_lifting_height": 8.0,
            "required_max_payload": 1000,
        },
    }
    try:
        response = client.post(
            "/rematch",
            json={
                "analysis_id": test_id,
                "overrides": {},
            },
        )
        assert response.status_code == 200
        updated = _app_module._analyses[test_id]["domain_criteria"]
        assert "required_lifting_height" in updated, (
            "Forklift-specific field must NOT be cleared when VT is unchanged"
        )
        assert "required_max_payload" in updated, (
            "Shared field must NOT be cleared when VT is unchanged"
        )
    finally:
        _app_module._analyses.pop(test_id, None)


def test_field_meta_vt_sheet_assignment_separates_vehicle_types():
    """GET /api/field-meta must assign each KO field to the correct VT scope.

    Verified fields:
    - towing_capacity   → scope NOT in extractable_domains (tugger-only leaf scope)
    - lifting_height    → scope NOT in extractable_domains (forklift-only leaf scope)
    - max_payload       → scope IN extractable_domains     (shared across all VTs)
    """
    response = client.get("/api/field-meta")
    assert response.status_code == 200
    meta = response.json()

    vt_config = meta.get("__vt_config__")
    assert vt_config is not None
    extractable_domains = vt_config.get("extractable_domains", [])
    assert isinstance(extractable_domains, list) and extractable_domains, \
        f"extractable_domains must be a non-empty list, got: {extractable_domains!r}"
    legacy_map = vt_config.get("legacy_map", {})

    # Tugger-only KO field
    tugger = meta.get("towing_capacity")
    assert tugger is not None, "towing_capacity missing from /api/field-meta"
    assert tugger["scope"] not in extractable_domains
    assert tugger["scope"] != legacy_map.get("Forklift AGV", "")

    # Forklift-only KO field
    forklift = meta.get("lifting_height")
    assert forklift is not None, "lifting_height missing from /api/field-meta"
    assert forklift["scope"] not in extractable_domains
    assert forklift["scope"] != legacy_map.get("Tugger AGV", "")

    # Shared KO field
    shared = meta.get("max_payload")
    assert shared is not None, "max_payload missing from /api/field-meta"
    assert shared["scope"] in extractable_domains


def test_field_meta_sheet_and_shared_sheet_name():
    """GET /api/field-meta must return a 'sheet' property per field and 'shared_sheet_name'
    in __vt_config__ so db.html column grouping and VT filter work correctly (OI-87)."""
    response = client.get("/api/field-meta")
    assert response.status_code == 200
    meta = response.json()

    vt_config = meta["__vt_config__"]
    shared = vt_config.get("shared_sheet_name", "")
    assert shared, "__vt_config__.shared_sheet_name must be a non-empty string"

    # Shared KO field → sheet == shared_sheet_name
    payload = meta.get("max_payload")
    assert payload is not None
    assert payload.get("sheet") == shared, (
        f"max_payload should have sheet='{shared}', got {payload.get('sheet')!r}"
    )

    # Forklift-only field → sheet == canonical VT name, not shared
    lift = meta.get("lifting_height")
    assert lift is not None
    assert lift.get("sheet") not in (None, shared), (
        f"lifting_height should have a VT-specific sheet, got {lift.get('sheet')!r}"
    )

    # Tugger-only field → sheet == canonical VT name, not shared
    tow = meta.get("towing_capacity")
    assert tow is not None
    assert tow.get("sheet") not in (None, shared), (
        f"towing_capacity should have a VT-specific sheet, got {tow.get('sheet')!r}"
    )
    assert tow.get("sheet") != lift.get("sheet"), (
        "towing_capacity and lifting_height must belong to different sheets"
    )

    # Global field → sheet == None
    product_type = meta.get("product_type")
    assert product_type is not None
    assert product_type.get("sheet") is None, (
        f"product_type (Global scope) should have sheet=null, got {product_type.get('sheet')!r}"
    )


def test_replay_endpoint_golden_companyx():
    """POST /analyze with a golden JSON file must return a valid result SSE event
    without making any LLM calls (parse_method == 'replay').

    Verifies:
    - A 'result' SSE event is emitted
    - parse_method == 'replay'
    - vehicle_type_canonical matches the golden file's vehicle_type
    - matches is non-empty
    """
    golden_path = _ROOT / "tests" / "tenders" / "golden_run_tender_companyx.json"
    assert golden_path.exists(), f"Golden file not found: {golden_path}"
    golden_bytes = golden_path.read_bytes()
    golden = json.loads(golden_bytes)

    response = client.post(
        "/analyze",
        files={"file": ("golden_run_tender_companyx.json", golden_bytes, "application/json")},
    )
    assert response.status_code == 200, (
        f"Expected 200 from /analyze replay, got {response.status_code}: {response.text[:200]}"
    )

    result_event = None
    for line in response.text.splitlines():
        if line.startswith("data: ") and result_event == "result":
            try:
                result_event = json.loads(line[6:])
            except json.JSONDecodeError:
                pass
            break
        if line.startswith("event: result"):
            result_event = "result"

    assert isinstance(result_event, dict), (
        f"No 'result' SSE event found in response. Raw (first 500 chars): {response.text[:500]}"
    )
    assert result_event.get("parse_method") == "replay", (
        f"Expected parse_method='replay', got: {result_event.get('parse_method')!r}"
    )
    assert result_event.get("vehicle_type_canonical") == golden.get("vehicle_type"), (
        f"vehicle_type_canonical mismatch: got {result_event.get('vehicle_type_canonical')!r}, "
        f"expected {golden.get('vehicle_type')!r}"
    )
    assert result_event.get("matches"), (
        "matches must be non-empty for a valid AGV golden replay"
    )
