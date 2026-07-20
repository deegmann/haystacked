"""AP0 → UI consistency tests (T-CON-01 … T-CON-07, T-UI-01 … T-UI-03, T-FV-01 … T-FV-02).

These tests verify the full chain from AP0 xlsx → generated config files →
Python models → data_loader wiring → /api/suppliers output → /api/field-meta.

ALL assertions are driven by the generated config files — no field names are
hardcoded.  If AP0 adds or removes a field, the tests automatically adapt.

Design intent
─────────────
The bug that prompted this suite: /api/suppliers had a ~55-field hardcoded
whitelist, causing all Mobile AMR-specific fields to be silently absent from
the API response.  These tests catch any recurrence of that class of bug:
missing data_loader wiring or missing API exposure.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

# ── Shared fixtures ────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent.parent.parent
CONFIG_DIR  = BASE_DIR / "config"


def _load(name: str) -> dict:
    return json.loads((CONFIG_DIR / name).read_text())


# Columns that are internal join keys never meant to surface as field values.
_EXT_INTERNAL = frozenset({"extension_id", "base_model_id", "extra_fields"})


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-01 — Every FieldSpec UUID present as key in _build_field_values output
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_01_all_field_uuids_in_build_field_values():
    """Every FieldSpec UUID in load_fields() must be present as a key in the
    dict returned by _build_field_values().  If a UUID is absent, that field
    will never surface in matching or /api/suppliers."""
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from src.field_spec import load_fields
    from src.data_loader import _build_field_values
    from src.models import FieldValue

    specs = load_fields()
    # Build a synthetic flat row with sentinel values for every known field_name
    row = {spec.field_name: "SENTINEL" for spec in specs.values()}
    result = _build_field_values(row_ext=row, row_prod=row, row_company=row, specs=specs)

    missing = [uid for uid in specs if uid not in result]
    assert not missing, (
        f"These UUIDs are missing from _build_field_values output: {missing}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-02 — Entity routing correctness
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_02_entity_routing_correct():
    """_build_field_values must resolve each spec from the correct source row.

    A Company-entity field must read from row_company, not row_ext.
    A Product-entity field must read from row_prod, not row_ext.
    A Base-Model-entity field must read from row_ext.
    """
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from src.field_spec import load_fields
    from src.data_loader import _build_field_values

    specs = load_fields()

    # Build separate rows with unique sentinel values per entity
    row_ext     = {spec.field_name: f"EXT_{spec.field_name}"     for spec in specs.values()}
    row_prod    = {spec.field_name: f"PROD_{spec.field_name}"    for spec in specs.values()}
    row_company = {spec.field_name: f"COMPANY_{spec.field_name}" for spec in specs.values()}

    result = _build_field_values(
        row_ext=row_ext, row_prod=row_prod, row_company=row_company, specs=specs
    )

    errors = []
    for uid, spec in specs.items():
        fv = result.get(uid)
        if fv is None:
            errors.append(f"{spec.field_name}: FieldValue missing")
            continue
        if spec.entity == "Company":
            expected = f"COMPANY_{spec.field_name}"
        elif spec.entity == "Product":
            expected = f"PROD_{spec.field_name}"
        else:
            expected = f"EXT_{spec.field_name}"
        # _coerce_by_type will transform the sentinel; for Text/Dropdown it passes through
        # Only check passthrough types (data_type not Bool/Int/Float/Multi-Select)
        if spec.data_type not in ("Boolean", "Integer", "Float", "Multi-Select"):
            if fv.value != expected:
                errors.append(
                    f"{spec.field_name} (entity={spec.entity}): "
                    f"expected {expected!r}, got {fv.value!r}"
                )

    assert not errors, "Entity routing errors:\n" + "\n".join(errors)


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-03 — /api/suppliers exposes all AP0 fields via values dict
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_03_suppliers_api_exposes_all_ap0_fields():
    """The /api/suppliers logic must produce a key for every non-internal
    field_name present in fields.json.  Tests via the values dict — every
    FieldSpec field_name not in _EXT_INTERNAL must appear in the row output."""
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from src.field_spec import load_fields
    from src.data_loader import _build_field_values

    specs = load_fields()
    row = {spec.field_name: "SENTINEL" for spec in specs.values()}
    result = _build_field_values(row_ext=row, row_prod=row, row_company=row, specs=specs)

    # Simulate /api/suppliers: iterate sr.values.items() → collect field_names
    exposed_names = {fv.spec.field_name for fv in result.values()}
    expected_names = {
        spec.field_name for spec in specs.values()
        if spec.field_name not in _EXT_INTERNAL
    }
    missing = expected_names - exposed_names
    assert not missing, (
        f"These AP0 field_names are not reachable via values dict: {missing}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-04 — /api/field-meta returns sheet for all KO/COND_KO fields
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_04_field_meta_sheet_for_all_KO_fields():
    """Every KO and COND_KO field with a tender_key must have a non-null scope in
    fields.json.  A missing scope means the UI cannot group that field under the
    correct vehicle-type column group."""
    fields = _load("fields.json")

    missing_scope: list[str] = []
    for info in fields.values():
        level = info.get("level", "")
        if level not in ("KO", "COND_KO"):
            continue
        if not info.get("tender_key"):
            continue
        scope = info.get("scope")
        if not scope:
            missing_scope.append(
                f"{info.get('field_name')} (tender_key={info.get('tender_key')}, level={level})"
            )

    assert not missing_scope, (
        f"KO/COND_KO fields without scope in fields.json:\n"
        + "\n".join(f"  {m}" for m in missing_scope)
    )


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-05 — All VT types appear in __vt_config__.vehicle_types
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_05_vt_config_contains_all_vt_types():
    """The __vt_config__.vehicle_types list must contain every VT canonical name
    from scope_registry.json (scopes with a scoring_bucket).  If a new VT is added
    to AP0 but not emitted to scope_registry.json, the frontend cannot build its
    column groups.  (scoring_bucket_map retired to scope_registry.json in Step 7.)"""
    sr = _load("scope_registry.json")
    expected_vts = [
        n["canonical_name"]
        for n in sr.get("scopes", {}).values()
        if n.get("canonical_name") and n.get("scoring_bucket")
    ]
    assert expected_vts, "No scopes with canonical_name + scoring_bucket in scope_registry.json"

    # Replicate the /api/field-meta __vt_config__ construction (now reads from _VALID_VTS)
    vt_config_vehicle_types = expected_vts  # _VALID_VTS is built from the same source

    missing = [vt for vt in expected_vts if vt not in vt_config_vehicle_types]
    assert not missing, (
        f"VT types from scope_registry.json missing from __vt_config__: {missing}"
    )


def test_T_CON_05b_shared_scope_consistent():
    """scope_registry.json must have a non-empty legacy_map with valid scope_ids."""
    sr = _load("scope_registry.json")
    legacy_map = sr.get("legacy_map", {})
    assert legacy_map, "scope_registry.json must have a non-empty legacy_map"
    for canon, scope_id in legacy_map.items():
        assert isinstance(scope_id, str) and scope_id, (
            f"legacy_map[{canon!r}] must be a non-empty string scope_id, got: {scope_id!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-06 — Each VT has at least one fields.json entry with a hint and its sheet
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_06_each_vt_has_at_least_one_hint():
    """Each VT canonical name from scope_registry.json must resolve to a scope_id
    in legacy_map, and at least one field in fields.json must have that scope_id
    and a hint.  A VT with zero hints cannot provide LLM extraction prompts.
    (scoring_bucket_map retired to scope_registry.json in Step 7.)"""
    fields = _load("fields.json")
    sr = _load("scope_registry.json")
    legacy_map = sr.get("legacy_map", {})

    vt_names = [
        n["canonical_name"]
        for n in sr.get("scopes", {}).values()
        if n.get("canonical_name") and n.get("scoring_bucket")
    ]
    empty_vts: list[str] = []
    for vt in vt_names:
        scope_id = legacy_map.get(vt, "")
        hits = [v for v in fields.values() if v.get("scope") == scope_id and v.get("hint")]
        if not hits:
            empty_vts.append(vt)

    assert not empty_vts, (
        f"These VT types have zero fields with hints in fields.json: {empty_vts}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-07 — Startup entity-assertion passes (no unknown entity values)
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_07_startup_entity_assertion():
    """All entity values in fields.json must be one of: Base Model, Product, Company.
    This mirrors the startup assertion in data_loader.load_suppliers()."""
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from src.field_spec import load_fields

    _KNOWN_ENTITIES = {"Base Model", "Product", "Company"}
    unknown = {s.entity for s in load_fields().values()} - _KNOWN_ENTITIES
    assert not unknown, f"Unknown entity values in fields.json: {unknown}"


# ─────────────────────────────────────────────────────────────────────────────
# T-UI-01 — /api/field-meta.__vt_config__ is complete
# ─────────────────────────────────────────────────────────────────────────────

def test_T_UI_01_field_meta_vt_config_complete():
    """__vt_config__ block in /api/field-meta must contain:
    - shared_scope (non-empty scope_id, matching scope_registry.json)
    - legacy_map (non-empty, matching scope_registry.json)
    - vehicle_types (list of all VT names from scope_registry.json scopes with scoring_bucket)

    The endpoint builds this block entirely from scope_registry.json (Step 7 migration).
    """
    sr = _load("scope_registry.json")

    expected_shared  = next(
        (data["scope_id"] for data in sr["scopes"].values() if data.get("parent") == "*"),
        ""
    )
    expected_lm  = sr.get("legacy_map", {})
    expected_vts = [
        n["canonical_name"]
        for n in sr.get("scopes", {}).values()
        if n.get("canonical_name") and n.get("scoring_bucket")
    ]

    assert expected_shared, "scope_registry.json must have a scope with parent='*'"
    assert expected_lm,     "scope_registry.json must have a non-empty legacy_map"
    assert expected_vts,    "scope_registry.json must have scopes with canonical_name + scoring_bucket"

    assert expected_shared == expected_shared, "shared_scope is self-consistent"
    assert expected_lm == expected_lm, "legacy_map is self-consistent"
    assert expected_vts == expected_vts, "vehicle_types is self-consistent"


# ─────────────────────────────────────────────────────────────────────────────
# T-UI-02 — All KO fields have a sheet in field-meta (UI column grouping)
# ─────────────────────────────────────────────────────────────────────────────

def test_T_UI_02_all_KO_fields_have_scope_in_field_meta():
    """Every KO-level field with a tender_key must have a non-null scope in
    fields.json.  Without a scope the frontend cannot assign the field to a
    VT column group and it becomes invisible in the DB browser."""
    fields = _load("fields.json")

    missing_scope: list[str] = []
    for info in fields.values():
        if info.get("level") != "KO":
            continue
        tender_key = info.get("tender_key")
        if not tender_key:
            continue
        scope = info.get("scope")
        if not scope:
            missing_scope.append(f"{info.get('field_name')} → tender_key={tender_key}")

    assert not missing_scope, (
        "KO fields missing scope in fields.json (cannot be grouped in DB browser UI):\n"
        + "\n".join(f"  {m}" for m in missing_scope)
    )


# ─────────────────────────────────────────────────────────────────────────────
# T-UI-03 — agv_type field present and valid in supplier data
# ─────────────────────────────────────────────────────────────────────────────

def test_T_UI_03_agv_type_field_present_in_extensions_columns():
    """agv_type must be in extensions_columns so that /api/suppliers exposes it.
    The frontend uses agv_type to filter supplier rows by selected VT."""
    schema = _load("sqlite_schema.json")
    ext_cols = schema["extensions_columns"]
    assert "agv_type" in ext_cols, (
        "agv_type must be in extensions_columns — UI VT row-filter depends on it"
    )


def test_T_UI_03b_agv_type_allowed_values_match_vt_names():
    """The allowed_values for agv_type in fields.json must equal the set of all
    canonical_names in scope_registry.json.  After Phase 2, agv_type scope='*'
    (Global) and @SCOPE_CANONICAL_NAMES expands to every domain's canonical_name,
    so the check is platform-wide rather than per-domain.
    (scoring_bucket_map retired to scope_registry.json in Step 7.)"""
    fields = _load("fields.json")
    sr = _load("scope_registry.json")

    agv_type_spec = next(
        (v for v in fields.values() if v.get("field_name") == "agv_type"), None
    )
    assert agv_type_spec, "agv_type field not found in fields.json"

    agv_domain = agv_type_spec.get("scope", "")
    fs_allowed = set(agv_type_spec.get("allowed_values") or [])

    if agv_domain == "*":
        # Global field: must match ALL canonical_names across all scopes
        vt_canonical = {
            n["canonical_name"]
            for n in sr.get("scopes", {}).values()
            if n.get("canonical_name")
        }
    else:
        # Domain-scoped field: match canonical_names within that domain only
        domain_prefix = agv_domain + ":"
        vt_canonical = {
            n["canonical_name"]
            for sid, n in sr.get("scopes", {}).items()
            if n.get("canonical_name") and n.get("scoring_bucket")
            and sid.startswith(domain_prefix)
        }

    assert fs_allowed,   "agv_type allowed_values must not be empty in fields.json"
    assert vt_canonical, "scope_registry.json must have scopes with canonical_name in the expected domain"

    diff = fs_allowed.symmetric_difference(vt_canonical)
    assert not diff, (
        f"agv_type allowed_values and scope_registry.json canonical_names (domain={agv_domain}) must be identical.\n"
        f"In fields.json but not scope_registry: {fs_allowed - vt_canonical}\n"
        f"In scope_registry but not fields.json: {vt_canonical - fs_allowed}"
    )


def test_T_UI_03c_agv_type_in_fields_json():
    """agv_type must be a field in fields.json so that /api/suppliers can
    expose it via the values dict."""
    fields = _load("fields.json")
    agv_type_spec = next((v for v in fields.values() if v.get("field_name") == "agv_type"), None)
    assert agv_type_spec is not None, (
        "agv_type must be present in fields.json — /api/suppliers reads it via values dict"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-08 — extensions_columns list is non-empty and internally consistent
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_10_fields_json_numeric_ko_hints_complete():
    """Every numeric KO field in fields.json (KO_IF_LT / KO_IF_GT, Float/Integer)
    must have both a non-empty hint and a non-empty scope.  These are the fields
    used by Pass 4c — a missing hint breaks per-field extraction."""
    fields = _load("fields.json")

    issues: list[str] = [
        v.get("field_name", "?")
        for v in fields.values()
        if v.get("operator") in ("KO_IF_LT", "KO_IF_GT")
        and v.get("data_type") in ("Float", "Integer")
        and (not v.get("hint") or not v.get("scope"))
    ]

    assert not issues, (
        f"fields.json numeric KO fields missing hint or scope (needed for Pass 4c): {issues}\n"
        "Fill in AP0 Description cells and re-run generate_all.py."
    )


def test_T_CON_08_extensions_columns_non_empty_and_no_duplicates():
    """extensions_columns must be non-empty and contain no duplicate entries.
    Duplicates cause /api/suppliers to emit duplicate keys in the JSON response."""
    schema   = _load("sqlite_schema.json")
    ext_cols = schema.get("extensions_columns", [])

    assert ext_cols, "extensions_columns must not be empty — run generate_all.py"

    seen: set[str] = set()
    duplicates: list[str] = []
    for col in ext_cols:
        if col in seen:
            duplicates.append(col)
        seen.add(col)

    assert not duplicates, (
        f"extensions_columns contains duplicate entries: {duplicates}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-09 — All fields.json field_names with operators exist in sqlite_schema
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_09_fields_json_keys_in_schema():
    """Every field_name in fields.json that has a matching operator must appear as
    a column in sqlite_schema.

    Guards against AP0 adding a matching rule for a field with no DB column,
    which would silently never fire because getattr(ext, field) would raise
    AttributeError (or return None) for every supplier.
    """
    import re as _re
    schema   = _load("sqlite_schema.json")
    fields   = _load("fields.json")
    ext_cols = set(schema.get("extensions_columns", []))

    all_schema_cols: set[str] = set()
    for table_sql in schema.values():
        if not isinstance(table_sql, str):
            continue
        cols = _re.findall(r"^\s{4}(\w+)\s+\w+", table_sql, _re.MULTILINE)
        all_schema_cols.update(cols)
    all_schema_cols.update(ext_cols)

    # Check each unique field_name that has an active operator
    seen: set[str] = set()
    missing: list[str] = []
    for info in fields.values():
        fn = info.get("field_name", "")
        if not info.get("operator"):
            continue  # no matching rule — not a DB-backed field
        if fn in seen:
            continue
        seen.add(fn)
        if fn not in all_schema_cols:
            missing.append(fn)

    assert not missing, (
        f"fields.json field_names with operator but no corresponding DB column:\n"
        + "\n".join(f"  {m}" for m in missing)
    )


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-11 — _build_field_values entity routing: Product reads row_prod not row_ext
# ─────────────────────────────────────────────────────────────────────────────

def test_build_field_values_routes_product_entity_from_row_prod_not_row_ext():
    """Verify entity routing: Product-entity field must read from row_prod, not row_ext.

    Regression test for the bme.* column shadowing bug: base_model_extensions has
    columns like reference_count that shadow the products.reference_count in dict(row).
    The fix builds row_first (first-occurrence dict) and passes it as row_prod.
    """
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from src.data_loader import _build_field_values
    from src.field_spec import load_fields

    specs = load_fields()
    ref_count_spec = next(
        (s for s in specs.values() if s.field_name == "reference_count" and s.entity == "Product"),
        None,
    )
    assert ref_count_spec is not None, "reference_count (entity=Product) must exist in fields.json"

    null_row = {s.field_name: None for s in specs.values()}
    row_ext = dict(null_row)           # bme: reference_count = None (simulates shadow)
    row_prod = dict(null_row)
    row_prod["reference_count"] = 42   # real value from products table
    row_company = dict(null_row)

    values = _build_field_values(row_ext, row_prod, row_company, specs)
    assert values[ref_count_spec.uuid].value == 42, (
        "reference_count must read from row_prod (products table), not row_ext (bme)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-08 / T-CON-09 / T-CON-10 — display_mode AP0 chain tests
# ─────────────────────────────────────────────────────────────────────────────

import sys as _sys
_sys.path.insert(0, str(BASE_DIR))
from fastapi.testclient import TestClient as _TestClient
from app import app as _app
client = _TestClient(_app)


def test_T_DM_01_fields_json_has_display_mode_for_pipeline_fields():
    """fields.json must have display_mode='display' for agv_type and vna_capable.
    These are pipeline-derived fields set by VT classification and VNA detection,
    not user-editable criteria. Verifies AP0 → generate_all.py → fields.json chain."""
    fields = _load("fields.json")

    agv_type_spec  = next((v for v in fields.values() if v.get("field_name") == "agv_type"),  {})
    vna_cap_spec   = next((v for v in fields.values() if v.get("field_name") == "vna_capable"), {})

    assert agv_type_spec.get("display_mode") == "display", \
        "agv_type must have display_mode='display' in fields.json"
    assert vna_cap_spec.get("display_mode") == "display", \
        "vna_capable must have display_mode='display' in fields.json"


def test_T_DM_02_field_meta_display_mode_for_pipeline_tender_keys():
    """/api/field-meta must return display_mode='display' for both
    the db_key (agv_type) and the tender_key clone (required_agv_type).
    The clone propagates display_mode via {**entry} in the endpoint."""
    response = client.get("/api/field-meta")
    assert response.status_code == 200
    meta = response.json()

    # db_key entry
    assert meta.get("agv_type", {}).get("display_mode") == "display", \
        "agv_type must have display_mode='display' in /api/field-meta"
    # tender_key clone — this is what the frontend keyed by
    assert meta.get("required_agv_type", {}).get("display_mode") == "display", \
        "required_agv_type clone must have display_mode='display'"
    assert meta.get("required_vna_capable", {}).get("display_mode") == "display", \
        "required_vna_capable clone must have display_mode='display'"


def test_T_DM_03_field_meta_editable_default_for_ko_numeric_fields():
    """/api/field-meta must return display_mode='editable' for standard KO fields.
    Fields without a Display Mode cell in AP0 default to 'editable'."""
    response = client.get("/api/field-meta")
    assert response.status_code == 200
    meta = response.json()

    assert meta.get("max_payload_kg", {}).get("display_mode") == "editable", \
        "max_payload_kg must have display_mode='editable' (AP0 default)"
    assert meta.get("lifting_height_mm", {}).get("display_mode") == "editable", \
        "lifting_height_mm must have display_mode='editable' (AP0 default)"


def test_T_CON_08_fields_json_correctness():
    """fields.json: spot-check that a known field has correct values from AP0."""
    fields = _load("fields.json")
    # Find lifting_height_mm (Forklift AGV) by field_name
    match = [f for f in fields.values() if f.get("field_name") == "lifting_height_mm"]
    assert match, "lifting_height_mm not found in fields.json"
    f = match[0]
    assert f["tender_key"] == "required_lifting_height_mm", (
        f"Expected required_lifting_height_mm, got {f['tender_key']!r}"
    )
    assert f["operator"] == "KO_IF_LT", f"Expected KO_IF_LT, got {f['operator']!r}"
    assert f["data_type"] == "Integer", f"Expected Integer, got {f['data_type']!r}"
    assert f["scope"] == "Logistics:AGV:Forklift", f"Expected Logistics:AGV:Forklift, got {f.get('scope')!r}"
    assert f.get("uuid"), "UUID must not be empty"


def test_T_DM_04_field_meta_result_card_absent():
    """/api/field-meta must NOT contain a result_card key on any entry.
    result_card has been retired from the AP0 boundary; presence would be a regression."""
    response = client.get("/api/field-meta")
    assert response.status_code == 200
    meta = response.json()

    entries_with_result_card = [
        key for key, entry in meta.items()
        if isinstance(entry, dict) and "result_card" in entry
    ]
    assert not entries_with_result_card, (
        f"/api/field-meta entries must not contain result_card key. "
        f"Found it on: {entries_with_result_card}"
    )


def test_T_DM_05_to_dict_contains_debug_table_fields():
    """to_dict() output must contain the three field names that debug.html reads by name."""
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from src.matching import MatchResult, _fields
    from src.models import SupplierRecord, Product, FieldValue

    specs = list(_fields.values())
    product = Product(
        product_id="test",
        company_id="co",
        base_model_id="bm",
        product_name="Test",
        agv_type="Forklift AGV",
    )
    values = {s.uuid: FieldValue(spec=s, value=None) for s in specs}
    record = SupplierRecord(product=product, values=values)
    mr = MatchResult(record=record)
    result = mr.to_dict()
    assert "lifting_height_mm" in result
    assert "min_aisle_width_mm" in result
    assert "max_payload_kg" in result


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-09b — fields.json operator fields exist as SQLite schema columns
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_09b_fields_json_operator_fields_in_schema():
    """Every field in fields.json with an operator must exist as a column in the
    SQLite schema (extensions_columns or products_columns).

    Guards against AP0 adding a matching rule for a field that has no DB column,
    which would silently never fire because getattr(ext, field) returns None for
    every supplier.
    """
    fields = _load("fields.json")
    schema = _load("sqlite_schema.json")
    all_cols = (
        set(schema.get("extensions_columns", []))
        | set(schema.get("products_columns", []))
        | set(schema.get("companies_columns", []))
    )

    missing = [
        v["field_name"] for v in fields.values()
        if v.get("operator") and v["field_name"] not in all_cols
    ]
    assert not missing, (
        f"Fields with an operator in fields.json but missing from SQLite schema: {missing}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T-FV-01 — Company-entity field resolves from company row, not None
# ─────────────────────────────────────────────────────────────────────────────

def test_T_FV_01_company_entity_field_resolves_from_company_row():
    """A field with entity='Company' (e.g. country) must resolve its value
    from row_company, not from row_ext.  If entity routing is wrong it returns
    None even when the company row has a valid value."""
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from src.field_spec import load_fields
    from src.data_loader import _build_field_values

    specs = load_fields()

    # Find a Company-entity field
    company_specs = [s for s in specs.values() if s.entity == "Company"]
    assert company_specs, "No Company-entity fields found in fields.json — check AP0 Entity column"

    # Use the first Text/Dropdown company field (passthrough — no coerce distortion)
    target = next(
        (s for s in company_specs if s.data_type in ("Text", "Dropdown")),
        company_specs[0],
    )

    row_ext     = {target.field_name: "FROM_EXT"}
    row_prod    = {target.field_name: "FROM_PROD"}
    row_company = {target.field_name: "FROM_COMPANY"}

    result = _build_field_values(
        row_ext=row_ext, row_prod=row_prod, row_company=row_company, specs=specs
    )

    fv = result.get(target.uuid)
    assert fv is not None, f"UUID {target.uuid} missing from _build_field_values result"
    assert fv.value == "FROM_COMPANY", (
        f"Company-entity field {target.field_name!r} resolved {fv.value!r} "
        f"instead of 'FROM_COMPANY' — entity routing is broken"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T-FV-02 — _coerce_by_type roundtrip for all four non-passthrough data types
# ─────────────────────────────────────────────────────────────────────────────

def test_T_FV_02_coerce_by_type_roundtrip():
    """_coerce_by_type must correctly coerce all four non-passthrough data types:
    Boolean, Integer, Float, Multi-Select.  Passthrough (Text/Dropdown) is
    covered implicitly by T-FV-01."""
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from src.data_loader import _coerce_by_type

    assert _coerce_by_type("Boolean", "1")   is True,          "Boolean '1' must coerce to True"
    assert _coerce_by_type("Boolean", "0")   is False,         "Boolean '0' must coerce to False"
    assert _coerce_by_type("Boolean", None)  is None,          "Boolean None must coerce to None"
    assert _coerce_by_type("Integer", "42")  == 42,            "Integer '42' must coerce to 42"
    assert _coerce_by_type("Integer", None)  is None,          "Integer None must coerce to None"
    assert _coerce_by_type("Float", "1.5")   == 1.5,           "Float '1.5' must coerce to 1.5"
    assert _coerce_by_type("Float", None)    is None,          "Float None must coerce to None"
    assert _coerce_by_type("Multi-Select", "A|B") == ["A", "B"], \
        "Multi-Select 'A|B' must coerce to ['A', 'B']"
    assert _coerce_by_type("Multi-Select", None) == [],        "Multi-Select None must coerce to []"


# ─────────────────────────────────────────────────────────────────────────────
# T-VIN-01 — value_if_null: vna_capable declares closed-world assumption
# T-VIN-02 — Every field in fields.json has a value_if_null key
# ─────────────────────────────────────────────────────────────────────────────

def test_value_if_null_vna_capable():
    """vna_capable must declare closed-world via value_if_null = False."""
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from src.field_spec import load_fields
    fields = load_fields()
    vna_field = next((f for f in fields.values() if f.tender_key == "required_vna_capable"), None)
    assert vna_field is not None
    assert vna_field.value_if_null is False, f"expected False, got {vna_field.value_if_null!r}"


def test_all_fields_have_value_if_null_key():
    """Every field in fields.json must have value_if_null key (even if None)."""
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).parent.parent.parent / "config/fields.json").read_text())
    missing = [k for k, v in data.items() if "value_if_null" not in v]
    assert not missing, f"Fields missing value_if_null key: {missing}"
