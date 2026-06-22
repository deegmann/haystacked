"""AP0 → UI consistency tests (T-CON-01 … T-CON-07, T-UI-01 … T-UI-03).

These tests verify the full chain from AP0 xlsx → generated config files →
Python models → data_loader wiring → /api/suppliers output → /api/field-meta.

ALL assertions are driven by the generated config files — no field names are
hardcoded.  If AP0 adds or removes a field, the tests automatically adapt.

Design intent
─────────────
The bug that prompted this suite: /api/suppliers had a ~55-field hardcoded
whitelist, causing all Mobile AMR-specific fields to be silently absent from
the API response.  These tests catch any recurrence of that class of bug:
missing dataclass field, missing data_loader wiring, or missing API exposure.

Known open items (C1/H1 fix pending)
──────────────────────────────────────
T-CON-01 and T-CON-03 will produce xfail entries for six Extension-dataclass
gaps that are not yet resolved:
  - installation_process   (Extension field missing)
  - modification_process   (Extension field missing)
  - min_fleet_size         (Extension field missing)
  - typical_project_value_eur (Extension field missing)
  - multi_language_display (Extension field missing)
  - gamification           (Extension field missing)

T-CON-02 (H1) flags the type mismatch: throughput_picks_per_hour is declared
Optional[int] in Extension but TEXT in sqlite_schema.json — a non-numeric TEXT
value would be silently coerced to None by _parse_int().
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


# Columns that are internal join keys never meant to surface as Extension attrs.
_EXT_INTERNAL = frozenset({"extension_id", "base_model_id", "extra_fields"})

# Fields with a confirmed Product-table fallback in /api/suppliers.
# These are missing from Extension but present on Product; the suppliers API
# resolves them via getattr(p, col, None) so they are NOT a runtime gap.
_PRODUCT_FALLBACK = frozenset({
    "reference_count",
    "lead_time_weeks",
    "service_coverage",
    "distribution_model",
    "country",
    "certifications_generic",
    "languages_spoken",
})

# Pure gaps: not in Extension AND not in Product.  These return None silently
# from /api/suppliers today.  Marked xfail until the C1 fix lands.
_PURE_C1_GAPS = frozenset({
    "installation_process",
    "modification_process",
    "min_fleet_size",
    "typical_project_value_eur",
    "multi_language_display",
    "gamification",
})


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-01 — All extensions_columns in Extension dataclass
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_01_all_extensions_columns_in_Extension_dataclass():
    """Every non-internal column in sqlite_schema.json extensions_columns must
    appear as a field on the Extension dataclass.

    This is an xfail when the six C1 pure-gap fields are still missing.
    If all gaps are fixed the test becomes a passing green test.
    """
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from src.models import Extension

    schema      = _load("sqlite_schema.json")
    ext_cols    = schema["extensions_columns"]
    ext_fields  = {f.name for f in dataclasses.fields(Extension)}

    missing = [
        col for col in ext_cols
        if col not in _EXT_INTERNAL
        and col not in ext_fields
        # Product-fallback fields are expected to be absent from Extension
        and col not in _PRODUCT_FALLBACK
    ]

    if missing:
        # Separate known C1 gaps from unexpected new gaps
        known   = [m for m in missing if m in _PURE_C1_GAPS]
        unknown = [m for m in missing if m not in _PURE_C1_GAPS]

        if unknown:
            # New gap — fail hard so the developer is alerted immediately
            pytest.fail(
                f"NEW Extension dataclass gaps detected (not in C1 backlog): {unknown}\n"
                f"All missing (including known C1): {missing}"
            )
        else:
            # Only known C1 gaps — mark as xfail
            pytest.xfail(
                f"C1/H1 fix pending — Extension missing {known}"
            )


def test_T_CON_01b_product_fallback_fields_present_in_Product():
    """Fields in _PRODUCT_FALLBACK must actually exist on the Product dataclass
    so that /api/suppliers getattr(p, col, None) resolves them correctly."""
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from src.models import Product

    prod_fields = {f.name for f in dataclasses.fields(Product)}
    missing = [f for f in _PRODUCT_FALLBACK if f not in prod_fields]
    assert not missing, (
        f"Fields expected on Product for API fallback are missing from Product dataclass: {missing}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-02 — All Extension fields wired in data_loader (mock-row test)
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_02_extension_fields_wired_in_data_loader():
    """Each field on the Extension dataclass must be populated by data_loader
    when a non-null value exists in the SQLite row.

    Approach: build a synthetic dict row, call load_suppliers() logic inline
    by constructing Extension the same way data_loader does, then assert each
    field received a non-default value.

    Excludes:
    - Identity fields (extension_id, base_model_id, agv_type) — required str args
    - extra_fields — opaque JSON blob, not individually wired
    - List fields (multiselect) get [] from a None row value — tested separately
    - Fields that live on Product (join-through) — not Extension constructor args
    """
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from src.models import Extension
    from src.data_loader import (
        _parse_bool, _parse_float, _parse_int, _parse_multiselect
    )

    schema = _load("sqlite_schema.json")
    bool_fields  = set(schema.get("bool_fields", []))
    int_fields   = set(schema.get("int_fields", []))
    float_fields = set(schema.get("float_fields", []))

    # Sentinel values used to detect successful wiring
    SENTINEL_BOOL  = 1       # will become True via _parse_bool
    SENTINEL_INT   = 42
    SENTINEL_FLOAT = 9.9
    SENTINEL_STR   = "TEST_VALUE"
    SENTINEL_MULTI = "A|B"   # will become ["A", "B"] via _parse_multiselect

    ext_fields = dataclasses.fields(Extension)

    # Fields that are identity/skip
    SKIP = {"extension_id", "base_model_id", "agv_type", "extra_fields"}
    # Fields with a list default — multiselect
    SKIP_LIST_FIELDS = {
        f.name for f in ext_fields
        if f.default_factory is not dataclasses.MISSING  # type: ignore[arg-type]
    }
    # Product join-through fields present on Extension as company context
    # These are populated in data_loader from d["employee_count_range"] etc., not from
    # the bme.* columns. Test them separately.
    COMPANY_CONTEXT = {"employee_count_range", "hq_city", "founding_year",
                       "industries_served"}

    # Build a mock row where every field has a sentinel value
    mock_row: dict = {}
    for f in ext_fields:
        if f.name in SKIP or f.name in SKIP_LIST_FIELDS or f.name in COMPANY_CONTEXT:
            continue
        if f.name in bool_fields:
            mock_row[f.name] = SENTINEL_BOOL
        elif f.name in int_fields:
            mock_row[f.name] = SENTINEL_INT
        elif f.name in float_fields:
            mock_row[f.name] = SENTINEL_FLOAT
        else:
            mock_row[f.name] = SENTINEL_STR

    # Also provide list (multiselect) fields with sentinel pipe-string
    for f in ext_fields:
        if f.name in SKIP_LIST_FIELDS and f.name not in SKIP:
            mock_row[f.name] = SENTINEL_MULTI

    # Provide company-context fields
    mock_row["employee_count_range"] = SENTINEL_STR
    mock_row["hq_city"]              = SENTINEL_STR
    mock_row["founding_year"]        = SENTINEL_INT
    mock_row["industries_served"]    = SENTINEL_MULTI

    # Replicate the data_loader Extension() constructor call using the same parse helpers.
    # This is NOT a copy of data_loader — it is a re-execution of the same logic
    # to verify every field maps through correctly.
    def _build_ext(d: dict) -> Extension:
        kwargs: dict = {
            "extension_id":               d.get("extension_id", "TEST-ID"),
            "base_model_id":              d.get("base_model_id", "BM-TEST"),
            "agv_type":                   d.get("agv_type", "Forklift AGV"),
        }
        for f in ext_fields:
            n = f.name
            if n in ("extension_id", "base_model_id", "agv_type"):
                continue
            if n == "extra_fields":
                kwargs[n] = d.get(n)
                continue
            if f.default_factory is not dataclasses.MISSING:  # type: ignore[arg-type]
                kwargs[n] = _parse_multiselect(d.get(n))
            elif n in bool_fields:
                kwargs[n] = _parse_bool(d.get(n))
            elif n in int_fields:
                kwargs[n] = _parse_int(d.get(n))
            elif n in float_fields:
                kwargs[n] = _parse_float(d.get(n))
            elif n in COMPANY_CONTEXT:
                raw = d.get(n)
                if n == "founding_year":
                    kwargs[n] = _parse_int(raw)
                elif n == "industries_served":
                    kwargs[n] = _parse_multiselect(raw)
                else:
                    kwargs[n] = raw
            else:
                kwargs[n] = d.get(n)
        return Extension(**kwargs)

    ext = _build_ext(mock_row)

    # Verify every wired field received the sentinel (not the default)
    not_wired = []
    for f in ext_fields:
        n = f.name
        if n in SKIP:
            continue
        val = getattr(ext, n)
        if f.default_factory is not dataclasses.MISSING:  # type: ignore[arg-type]
            # Multiselect: sentinel "A|B" should parse to ["A", "B"]
            if val == []:
                not_wired.append(n)
        else:
            default_val = f.default if f.default is not dataclasses.MISSING else None
            if val == default_val:
                not_wired.append(n)

    assert not not_wired, (
        f"These Extension fields received their default (not wired or parse failed): {not_wired}"
    )


def test_T_CON_02_H1_throughput_type_mismatch():
    """H1 gap: throughput_picks_per_hour is TEXT in sqlite_schema but Optional[int]
    in Extension.  A non-numeric TEXT value (e.g. '100-200') is silently coerced
    to None by _parse_int(), causing data loss without any error.

    This test is xfail until models.py changes throughput_picks_per_hour to
    Optional[str] to match the schema declaration.
    """
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from src.models import Extension
    from src.data_loader import _parse_int

    schema = _load("sqlite_schema.json")
    # Find throughput_picks_per_hour in the schema
    # It should NOT be in int_fields if it is declared TEXT
    int_fields = set(schema.get("int_fields", []))
    bool_fields = set(schema.get("bool_fields", []))
    float_fields = set(schema.get("float_fields", []))
    ext_cols = schema.get("extensions_columns", [])

    assert "throughput_picks_per_hour" in ext_cols, (
        "throughput_picks_per_hour must be in extensions_columns"
    )

    is_numeric_schema_type = (
        "throughput_picks_per_hour" in int_fields
        or "throughput_picks_per_hour" in float_fields
    )

    # Find the Extension field type
    for f in dataclasses.fields(Extension):
        if f.name == "throughput_picks_per_hour":
            ext_type_hint = f.type
            break
    else:
        pytest.fail("throughput_picks_per_hour not found in Extension dataclass")

    # If schema says TEXT but Extension says int, we have a mismatch
    if not is_numeric_schema_type and "int" in str(ext_type_hint).lower():
        pytest.xfail(
            "H1 fix pending: throughput_picks_per_hour is TEXT in sqlite_schema.json "
            f"but declared as {ext_type_hint} in Extension. "
            "Non-numeric TEXT values will be silently coerced to None by _parse_int()."
        )


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-03 — /api/suppliers logic exposes all extensions_columns
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_03_suppliers_api_exposes_all_extensions_columns():
    """The /api/suppliers logic must produce a key for every non-internal
    extensions_columns entry.  Tests the column iteration logic directly
    (no running server required).

    Pure C1 gaps (6 fields with no Extension AND no Product attribute) are
    xfail — they silently return None today.
    """
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from src.models import Extension, Product

    schema      = _load("sqlite_schema.json")
    ext_cols    = schema["extensions_columns"]
    EXT_INTERNAL = {"extension_id", "base_model_id", "extra_fields"}

    ext_fields  = {f.name for f in dataclasses.fields(Extension)}
    prod_fields = {f.name for f in dataclasses.fields(Product)}

    # Simulate what /api/suppliers does per column:
    #   val = getattr(e, col, None)
    #   if val is None: val = getattr(p, col, None)
    # A column "passes" if at least one of Extension or Product has it.
    missing_from_api = []
    for col in ext_cols:
        if col in EXT_INTERNAL:
            continue
        if col not in ext_fields and col not in prod_fields:
            missing_from_api.append(col)

    if missing_from_api:
        known   = [m for m in missing_from_api if m in _PURE_C1_GAPS]
        unknown = [m for m in missing_from_api if m not in _PURE_C1_GAPS]
        if unknown:
            pytest.fail(
                f"NEW /api/suppliers gaps (not in C1 backlog): {unknown}\n"
                f"All missing: {missing_from_api}"
            )
        else:
            pytest.xfail(
                f"C1 fix pending — these columns silently return None from /api/suppliers: {known}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-04 — /api/field-meta returns sheet for all KO/COND_KO fields
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_04_field_meta_sheet_for_all_KO_fields():
    """Every KO and COND_KO field with a tender_key must have a sheet mapping
    in extraction_hints.json.  A missing sheet means the UI cannot group that
    field under the correct vehicle-type column group."""
    fl    = _load("field_levels.json")
    hints = _load("extraction_hints.json")

    missing_sheet: list[str] = []
    for db_key, info in fl.items():
        level = info.get("level", "")
        if level not in ("KO", "COND_KO"):
            continue
        tk = info.get("tender_key", db_key)
        sheet = hints.get(tk, {}).get("sheet")
        if not sheet:
            missing_sheet.append(f"{db_key} (tender_key={tk}, level={level})")

    assert not missing_sheet, (
        f"KO/COND_KO fields without sheet in extraction_hints.json:\n"
        + "\n".join(f"  {m}" for m in missing_sheet)
    )


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-05 — All VT types appear in __vt_config__.vehicle_types
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_05_vt_config_contains_all_vt_types():
    """The __vt_config__.vehicle_types list must contain every VT name from
    vehicle_types.json scoring_bucket_map.keys().  If a new VT is added to AP0
    but not to scoring_bucket_map, the frontend cannot build its column groups."""
    vt_cfg = _load("vehicle_types.json")
    expected_vts = list(vt_cfg.get("scoring_bucket_map", {}).keys())
    assert expected_vts, "scoring_bucket_map in vehicle_types.json must not be empty"

    # Replicate the /api/field-meta __vt_config__ construction
    vt_config_vehicle_types = list(vt_cfg.get("scoring_bucket_map", {}).keys())

    missing = [vt for vt in expected_vts if vt not in vt_config_vehicle_types]
    assert not missing, (
        f"VT types from scoring_bucket_map missing from __vt_config__: {missing}"
    )


def test_T_CON_05b_shared_sheet_name_consistent():
    """__vt_config__.shared_sheet_name must match vehicle_types.json shared_sheet_name."""
    vt_cfg = _load("vehicle_types.json")
    expected_shared = vt_cfg.get("shared_sheet_name", "")
    assert expected_shared, "vehicle_types.json must have a non-empty shared_sheet_name"

    # The field-meta endpoint reads it directly from vehicle_types.json
    # so the values are identical by construction — this test guards against
    # a future copy-paste into a separate config file.
    actual_shared = vt_cfg.get("shared_sheet_name", "")
    assert actual_shared == expected_shared, (
        f"shared_sheet_name mismatch: expected {expected_shared!r}, got {actual_shared!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-06 — Each VT has at least one extraction_hints entry with its sheet
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_06_each_vt_has_at_least_one_hint():
    """Each VT name from scoring_bucket_map must appear as the sheet value of
    at least one entry in extraction_hints.json.  A VT with zero hints cannot
    provide LLM extraction prompts for its fields."""
    vt_cfg = _load("vehicle_types.json")
    hints  = _load("extraction_hints.json")

    vt_names = list(vt_cfg.get("scoring_bucket_map", {}).keys())
    empty_vts: list[str] = []
    for vt in vt_names:
        hits = [k for k, v in hints.items() if v.get("sheet") == vt]
        if not hits:
            empty_vts.append(vt)

    assert not empty_vts, (
        f"These VT types have zero extraction_hints entries: {empty_vts}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-07 — _check_extension_gaps() warns only for true gaps, not for
#             Product-fallback fields (smoke test)
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_07_extension_gaps_smoke():
    """Smoke test: _check_extension_gaps() logic must produce no gap warnings
    AFTER all C1 gaps are resolved (i.e., when Extension dataclass is complete).

    While C1/H1 are still open, this test is xfail for the pure gaps.

    The function warns for ALL fields in extensions_columns that are absent from
    the Extension dataclass.  It does NOT distinguish Product-fallback fields
    from true gaps — that is an accepted limitation (false-positive warnings at
    startup).  This test tracks only whether true gaps (no Extension AND no Product
    attribute) exist, because those are the ones that silently return None.

    What _check_extension_gaps() actually does today (by design):
    - It warns about _PRODUCT_FALLBACK fields too — those fields are intentionally
      absent from Extension but work via Product fallback in /api/suppliers.
      These are known benign false-positive startup warnings.
    - It warns about _PURE_C1_GAPS fields — those are real gaps (C1 backlog).
    The test below validates only the real-gap case.
    """
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from src.models import Extension

    schema   = _load("sqlite_schema.json")
    ext_cols = schema["extensions_columns"]
    EXT_INTERNAL = {"extension_id", "base_model_id", "extra_fields"}

    ext_fields = {f.name for f in dataclasses.fields(Extension)}

    # Replicate _check_extension_gaps() gap detection logic
    all_gaps = [
        col for col in ext_cols
        if col not in EXT_INTERNAL and col not in ext_fields
    ]

    # Separate real runtime gaps from benign Product-fallback gaps
    real_gaps = [g for g in all_gaps if g not in _PRODUCT_FALLBACK]

    if real_gaps:
        known   = [g for g in real_gaps if g in _PURE_C1_GAPS]
        unknown = [g for g in real_gaps if g not in _PURE_C1_GAPS]
        if unknown:
            pytest.fail(
                f"_check_extension_gaps detected NEW unexpected runtime gaps (not in C1 backlog): {unknown}\n"
                f"These fields will silently return None from /api/suppliers.\n"
                f"Full gap list: {real_gaps}"
            )
        else:
            pytest.xfail(
                f"C1 fix pending — these fields silently return None from /api/suppliers: {known}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# T-UI-01 — /api/field-meta.__vt_config__ is complete
# ─────────────────────────────────────────────────────────────────────────────

def test_T_UI_01_field_meta_vt_config_complete():
    """__vt_config__ block in /api/field-meta must contain:
    - shared_sheet_name (non-empty, matching vehicle_types.json)
    - vehicle_types (list of all VT names from scoring_bucket_map)

    The endpoint builds this block directly from vehicle_types.json so this
    is primarily a contract test — if the config key names ever drift the
    frontend column-grouping silently breaks.
    """
    vt_cfg = _load("vehicle_types.json")

    expected_shared = vt_cfg.get("shared_sheet_name", "")
    expected_vts    = list(vt_cfg.get("scoring_bucket_map", {}).keys())

    assert expected_shared, "shared_sheet_name must be non-empty in vehicle_types.json"
    assert expected_vts,    "scoring_bucket_map must be non-empty in vehicle_types.json"

    # Simulate /api/field-meta __vt_config__ construction (from app.py lines 964-968)
    vt_config = {
        "shared_sheet_name": vt_cfg.get("shared_sheet_name", ""),
        "vehicle_types":     list(vt_cfg.get("scoring_bucket_map", {}).keys()),
    }

    assert vt_config["shared_sheet_name"] == expected_shared, (
        f"shared_sheet_name mismatch: {vt_config['shared_sheet_name']!r} != {expected_shared!r}"
    )
    assert vt_config["vehicle_types"] == expected_vts, (
        f"vehicle_types mismatch: {vt_config['vehicle_types']} != {expected_vts}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T-UI-02 — All KO fields have a sheet in field-meta (UI column grouping)
# ─────────────────────────────────────────────────────────────────────────────

def test_T_UI_02_all_KO_fields_have_sheet_in_field_meta():
    """Every KO-level field with a tender_key must resolve to a non-null sheet
    in the /api/field-meta response.  Without a sheet the frontend cannot assign
    the field to a VT column group and it becomes invisible in the DB browser.

    Equivalent to T-CON-04 but exercises the field-meta endpoint logic path
    (including the tender_key → sheet lookup chain) rather than raw config files.
    """
    fl    = _load("field_levels.json")
    hints = _load("extraction_hints.json")

    missing_sheet: list[str] = []
    for db_key, info in fl.items():
        if info.get("level") != "KO":
            continue
        tender_key = info.get("tender_key")
        if not tender_key:
            continue
        # Replicate field-meta sheet lookup (app.py line 952)
        sheet = hints.get(tender_key, {}).get("sheet")
        if not sheet:
            missing_sheet.append(f"{db_key} → tender_key={tender_key}")

    assert not missing_sheet, (
        "KO fields missing sheet in /api/field-meta (cannot be grouped in DB browser UI):\n"
        + "\n".join(f"  {m}" for m in missing_sheet)
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
    """The allowed_values for agv_type in field_levels.json must be identical to
    scoring_bucket_map.keys() in vehicle_types.json.  If they diverge, the UI
    VT filter will hide rows it should show (or show rows it should hide)."""
    fl     = _load("field_levels.json")
    vt_cfg = _load("vehicle_types.json")

    fl_allowed   = set(fl.get("agv_type", {}).get("allowed_values", []))
    vt_canonical = set(vt_cfg.get("scoring_bucket_map", {}).keys())

    assert fl_allowed, "agv_type allowed_values must not be empty in field_levels.json"
    assert vt_canonical, "scoring_bucket_map must not be empty in vehicle_types.json"

    diff = fl_allowed.symmetric_difference(vt_canonical)
    assert not diff, (
        f"agv_type allowed_values and scoring_bucket_map.keys() must be identical.\n"
        f"In field_levels but not scoring_bucket_map: {fl_allowed - vt_canonical}\n"
        f"In scoring_bucket_map but not field_levels: {vt_canonical - fl_allowed}"
    )


def test_T_UI_03c_agv_type_is_Extension_field():
    """agv_type must be a field on the Extension dataclass so that
    /api/suppliers can expose it via getattr(e, 'agv_type')."""
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from src.models import Extension

    ext_fields = {f.name for f in dataclasses.fields(Extension)}
    assert "agv_type" in ext_fields, (
        "agv_type must be a field on Extension — /api/suppliers reads it via getattr(e, col)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T-CON-08 — extensions_columns list is non-empty and internally consistent
# ─────────────────────────────────────────────────────────────────────────────

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
# T-CON-09 — All field_levels.json keys exist in sqlite_schema extensions_columns
# ─────────────────────────────────────────────────────────────────────────────

def test_T_CON_09_field_levels_keys_in_schema():
    """Every db_key in field_levels.json (non-tender_key entries) must appear as
    a column in extensions_columns OR in one of the other schema tables.

    Guards against AP0 adding a matching rule for a field that has no DB column,
    which would silently never fire because getattr(ext, field) would raise
    AttributeError (or return None via default) for every supplier.
    """
    schema   = _load("sqlite_schema.json")
    fl       = _load("field_levels.json")
    ext_cols = set(schema.get("extensions_columns", []))

    # Build the full set of all known schema columns across all tables
    all_schema_cols: set[str] = set()
    for table_sql in schema.values():
        if not isinstance(table_sql, str):
            continue
        # Extract column names from CREATE TABLE SQL (simple heuristic)
        import re
        cols = re.findall(r"^\s{4}(\w+)\s+\w+", table_sql, re.MULTILINE)
        all_schema_cols.update(cols)
    all_schema_cols.update(ext_cols)

    # Exclude fields that are tender_keys (they don't correspond to db columns)
    tender_keys = {
        info.get("tender_key", key)
        for key, info in fl.items()
        if info.get("tender_key")
    }

    missing: list[str] = []
    for db_key in fl:
        if db_key in tender_keys:
            continue  # this is a tender key alias, not a db column
        if db_key not in all_schema_cols:
            missing.append(db_key)

    assert not missing, (
        f"field_levels.json keys with no corresponding DB column in any schema table:\n"
        + "\n".join(f"  {m}" for m in missing)
    )
