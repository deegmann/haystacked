---
title: Haystacked Platform — Technical Reference
version: IK Sprint (multi-domain rollout) + OI-114 guard fixes, AP0 v0.10
date: 2026-07-31
author: app-documentation-writer agent
---

# Haystacked Platform — Technical Reference

> Reflects the multi-domain rollout (Logistics:AGV + FoodBev:Refrigeration live in production)
> and the OI-114 hallucination-guard fixes (commits `685b492`, `2724749`). 322 tests.
> This document assumes Python familiarity and cites exact function/file locations. For a
> plain-language walkthrough aimed at a reader new to this codebase — the pipeline stages,
> the guard architecture explained conceptually, and an expanded Known Risks section — see
> `docs/architecture.md`. That document and this one should agree; where they don't, trust
> whichever was more recently touched (check the date headers) and flag the drift.

---

## 1. AP0 xlsx Tab Structure

`Spec/haystacked_AP0_field_spec_v0_10.xlsx` is the single source of truth.

### 1.1 Data Tabs (machine-readable by generate_all.py)

Each data tab has a standard column header row starting with `Field Name`. Required columns:

| Column | Purpose |
|--------|---------|
| `Field Name` | Primary key — field_name in fields.json; also used as column name in SQLite |
| `UUID` | Globally unique identifier for this field; hard error if absent |
| `Entity` | `Company`, `Product`, or `Base Model` — determines which SQLite table and source dict |
| `Level` | `K.O.` / `Cond. K.O.` / `Scoring` / `Context` (maps to KO/COND_KO/SCORING/CONTEXT) |
| `Matching Operator` | One of: KO_IF_LT, KO_IF_GT, KO_IF_NEQ, KO_BOOL_REQUIRED, KO_BOOL_EXCLUSIVE, KO_SUBSET |
| `Data Type` | Boolean, Integer, Float, Dropdown, Multi-Select, Text, Long Text |
| `Unit` | Physical unit string (mm, kg, °C, etc.) |
| `Allowed Values` | Pipe-separated enum values for Dropdown/Multi-Select fields |
| `Scoring Weight` | Integer; points awarded if scoring rule matches |
| `Score Function` | bool, bool_cond, proportional, nonempty, threshold_lower, threshold_upper, tiered_lower, tiered_upper |
| `Score Threshold A` | Primary threshold for scoring functions |
| `Score Threshold B` | Secondary threshold (tiered functions) |
| `LLM Hint` | Extraction hint for LLM; controls whether a field appears in extraction template |
| `UI Hint` | User-facing description (`user_description` in fields.json) |
| `Display Mode` | Optional display hint for frontend |
| `Value if Null` | Closed-world assumption: value to use when supplier field is None |
| `Plausibility Min` | Minimum plausible value for LLM validation |
| `Plausibility Max` | Maximum plausible value for LLM validation |

### 1.2 Tab List and Scopes

**Multi-domain is live in production** (IK Sprint, completed 2026-07-2x). `scope_registry.json`'s
`scopes` dict currently has two domain-level nodes (`parent == "*"`): `Logistics:AGV` (3 leaf
product types) and `FoodBev:Refrigeration` (0 leaves — a single-leaf domain, see note below).
The earlier assumption of "exactly one child of `*`" (a hard startup assertion in `app.py`) has
been relaxed to "at least one" (`assert len(_shared_candidates) >= 1`); `_EXTRACTABLE_DOMAINS`
is the resulting `frozenset` of all domain-level scope_ids, and `app.py` builds one system prompt
per domain (`_DOMAIN_SYSTEM: dict[str, str]`), not one global AGV-only prompt.

| AP0 Tab | Scope ID assigned | Fields in scope |
|---------|------------------|-----------------|
| `Global` | `*` | Fields applicable to all industries |
| `AGV_Shared` | `Logistics:AGV` | Fields shared across all AGV vehicle types |
| `AGV_Forklift` | `Logistics:AGV:Forklift` | Forklift-specific fields |
| `AGV_Tugger` | `Logistics:AGV:Tugger` | Tugger-specific fields |
| `AGV_AMR` | `Logistics:AGV:AMR` | Mobile AMR-specific fields |
| `FoodBev_Refrigeration` | `FoodBev:Refrigeration` | Industrial refrigeration fields (single-leaf domain — no sub-types; canonical_name `"Industrial Refrigeration"` lives directly on the domain node) |

**Single-leaf domains skip Pass 4a (leaf-type classification) entirely (OI-107):** if a domain
node has no children in `scope_registry.json`, `_SINGLE_LEAF_DOMAINS` includes it, and `app.py`'s
`/analyze` handler (`_is_single_leaf` branch) sets `canonical_product_type` directly from
`scope_reg["scopes"][_domain]["canonical_name"]` without an LLM call — there is only one possible
answer, so classifying is a wasted call. `Logistics:AGV` is NOT single-leaf (3 children), so
AGV tenders still run Pass 4a.

**A new pipeline stage precedes Pass 4a for every tender, not just AGV ones: domain detection.**
`app.py`'s `/analyze` handler runs an LLM call against `domain_detection_template.txt`
(placeholders `{tender_category}`, `{summary}`) immediately after NACE classification, populating
`result["detected_domain"]` (e.g. `"Logistics:AGV"` or `"FoodBev:Refrigeration"`). A keyword
fallback (`_DOMAIN_KWS`, from `scope_registry.json["domain_keywords"]`, scanned against the first
5,000 chars) fires if the LLM call fails or returns nothing. `is_extractable =
detected_domain in _EXTRACTABLE_DOMAINS` gates whether any domain-specific extraction runs at
all. This pass supersedes the older `is_agv_amr` boolean flag described in `CLAUDE.md`'s Data
Flow section, which predates the multi-domain rollout and has not yet been updated to match.

### 1.3 Structural Tabs

| Tab | Purpose |
|-----|---------|
| `③ Scope Registry` | Defines scope hierarchy: columns scope_id, parent_scope, tab_name, active |
| `② Structure` | SQLite structural columns per table: table, column, sqlite_type, role, references, nullable, notes |
| `Vehicle Types` | LLM output -> canonical mapping, VNA detection, fallback keywords, text override regexes |
| `Field Fallbacks` | Regex -> field value override rules |
| `Entity Model` | Documentation only — NOT read by generate_all.py |

### 1.4 AP0 Hygiene Asserts (run at generation time)

**SA-22 (hard error):** CONTEXT-level fields must not have a Matching Operator. `generate_all.py` aborts with `[FEHLER]` if any CONTEXT field has an operator.

**SA-25 (warning only):** SCORING-level fields with no Scoring Weight and no Score Function are inert — they contribute nothing to matching. generate_all.py prints a warning. Fix by assigning weights in AP0 or demoting to CONTEXT.

**Numeric KO plausibility assertion:** All Float/Integer fields with KO_IF_LT or KO_IF_GT must have Plausibility Min and Plausibility Max defined. Hard error if missing.

---

## 2. config/fields.json

Generated by `scripts/generate_all.py`. Keyed by UUID. Never edit manually.

### 2.1 Field Schema

Every entry in fields.json:

```json
{
  "<uuid>": {
    "uuid":             "7ca18941-1522-4b3d-a34e-38fb11dad36b",
    "field_name":       "service_coverage",
    "tender_key":       "required_service_coverage",
    "entity":           "Product",
    "scope":            "Logistics:AGV",
    "level":            "COND_KO",
    "operator":         "KO_SUBSET",
    "data_type":        "Multi-Select",
    "unit":             null,
    "allowed_values":   ["None", "DACH", "EU", "Global"],
    "score_function":   null,
    "threshold_a":      null,
    "threshold_b":      null,
    "scoring_weight":   null,
    "hint":             "Geographic service & support reach. Source: 'locations / service network'. ...",
    "user_description": "In which countries or regions is service and support required?",
    "display_mode":     null,
    "value_if_null":    null
  }
}
```

### 2.2 Field Key Semantics

| Key | Type | Source | Notes |
|-----|------|--------|-------|
| `uuid` | str | AP0 UUID column | Primary key; globally unique; hard error if absent |
| `field_name` | str | AP0 Field Name column | SQLite column name and Python attribute name |
| `tender_key` | str | Derived: `"required_" + field_name` | Key used in extracted tender criteria dict |
| `entity` | str | AP0 Entity column | "Company", "Product", or "Base Model" |
| `scope` | str | AP0 tab name -> scope_id via ③ Scope Registry | e.g. "Logistics:AGV:Forklift" |
| `level` | str\|null | AP0 Level column | KO / COND_KO / SCORING / CONTEXT / null |
| `operator` | str\|null | AP0 Matching Operator column | One of 6 operators; null for SCORING and CONTEXT |
| `data_type` | str | AP0 Data Type column | Boolean, Integer, Float, Dropdown, Multi-Select, Text |
| `unit` | str\|null | AP0 Unit column | Physical unit for display and KO_IF_LT zero-check |
| `allowed_values` | list\|null | AP0 Allowed Values column (Dropdown/Multi-Select only) | Enum validation list |
| `score_function` | str\|null | AP0 Score Function column | Scoring rule name |
| `threshold_a` | float\|null | AP0 Score Threshold A | Primary threshold |
| `threshold_b` | float\|null | AP0 Score Threshold B | Secondary threshold (tiered functions) |
| `scoring_weight` | int\|null | AP0 Scoring Weight column | Points for this field |
| `hint` | str\|null | AP0 LLM Hint column | LLM extraction instruction; absent = field not extracted |
| `user_description` | str\|null | AP0 UI Hint column | Shown in frontend clarification dialog |
| `display_mode` | str\|null | AP0 Display Mode column | Frontend display hint |
| `value_if_null` | any\|null | AP0 Value if Null column | Closed-world assumption value; typed and validated at generation |

### 2.3 Multi-VT Fields

Some fields appear in multiple AP0 tabs with the same field_name but different UUIDs and scopes. Example: `min_aisle_width` appears in both AGV_Shared and AGV_Forklift if the allowed values or plausibility ranges differ per VT.

`fields_by_tender_key()` returns `dict[tender_key -> list[FieldSpec]]` — a list because one tender_key can map to multiple scoped specs. A startup assertion verifies all specs for the same tender_key agree on `allowed_values`.

---

## 3. config/scope_registry.json

Generated by `scripts/generate_all.py`. Read by `app.py` and `src/matching.py` at startup.

```json
{
  "scopes": {
    "*":                      {"scope_id": "*",                    "parent": null, "tab_name": "Global"},
    "Logistics:AGV":          {"scope_id": "Logistics:AGV",        "parent": "*",  "tab_name": "AGV_Shared"},
    "Logistics:AGV:Forklift": {"scope_id": "Logistics:AGV:Forklift","parent": "Logistics:AGV","tab_name": "AGV_Forklift", "canonical_name": "Forklift AGV"},
    "Logistics:AGV:Tugger":   {"scope_id": "Logistics:AGV:Tugger", "parent": "Logistics:AGV","tab_name": "AGV_Tugger", "canonical_name": "Tugger AGV"},
    "Logistics:AGV:AMR":      {"scope_id": "Logistics:AGV:AMR",    "parent": "Logistics:AGV","tab_name": "AGV_AMR", "canonical_name": "Mobile AMR"},
    "FoodBev:Refrigeration":  {"scope_id": "FoodBev:Refrigeration","parent": "*",  "tab_name": "FoodBev_Refrigeration", "canonical_name": "Industrial Refrigeration"}
  },
  "resolution_order": {
    "Logistics:AGV:Forklift": ["*", "Logistics:AGV", "Logistics:AGV:Forklift"],
    "Logistics:AGV:Tugger":   ["*", "Logistics:AGV", "Logistics:AGV:Tugger"],
    "Logistics:AGV:AMR":      ["*", "Logistics:AGV", "Logistics:AGV:AMR"],
    "FoodBev:Refrigeration":  ["*", "FoodBev:Refrigeration"]
  },
  "legacy_map": {
    "Forklift AGV": "Logistics:AGV:Forklift",
    "Tugger AGV":   "Logistics:AGV:Tugger",
    "Mobile AMR":   "Logistics:AGV:AMR",
    "Industrial Refrigeration": "FoodBev:Refrigeration"
  }
}
```

Note: `FoodBev:Refrigeration` has no children in `scopes` (no node has `parent ==
"FoodBev:Refrigeration"`), which is what makes it a single-leaf domain (§1.2) — its
`resolution_order` chain has only 2 entries instead of 3.

**resolution_order** is the key mechanism for scope-aware field selection. For a given leaf scope, the list contains all ancestor scope_ids (root first, leaf last). A field is relevant to a supplier if `field.scope in resolution_order[supplier_leaf_scope]`.

**legacy_map** bridges canonical VT names (LLM output domain) to scope IDs (AP0 domain). Always use `legacy_map` to translate; never hardcode scope IDs in Python.

---

## 4. config/unit_semantics.json

**Manually maintained — NOT generated by generate_all.py.** Edit this file directly when new signed-domain units are needed.

```json
{
  "signed_units": ["°C", "°F"],
  "_comment": "Units with signed domain (zero is a real value). All other numeric units are non-negative — zero means no effective requirement for KO_IF_LT."
}
```

**Purpose:** The `_is_active_requirement()` function in `src/matching.py` treats a tender value of 0 as "no effective requirement" for `KO_IF_LT` fields — unless the field's unit is in `_SIGNED_UNITS`. This allows a minimum temperature of 0°C to be treated as a real constraint (not "no minimum"), while a 0 kg payload requirement means "any payload is acceptable."

**Consumed by:** `src/matching.py` (loaded at startup into `_SIGNED_UNITS`), `app.py` (also loaded at startup).

---

## 5. src/field_spec.py (Generated)

Generated by `scripts/generate_all.py`. Never edit manually.

### 5.1 FieldSpec Dataclass

```python
@dataclass
class FieldSpec:
    uuid: str
    field_name: str
    tender_key: Optional[str]      # "required_" + field_name
    entity: str                    # "Company", "Product", "Base Model"
    scope: str                     # scope_id string
    level: Optional[str]           # KO, COND_KO, SCORING, CONTEXT
    operator: Optional[str]        # KO_IF_LT, KO_IF_GT, KO_IF_NEQ, KO_BOOL_REQUIRED, KO_BOOL_EXCLUSIVE, KO_SUBSET
    data_type: str                 # Boolean, Integer, Float, Dropdown, Multi-Select, Text
    unit: Optional[str]
    allowed_values: Optional[list]
    score_function: Optional[str]
    threshold_a: Optional[float]
    threshold_b: Optional[float]
    scoring_weight: Optional[int]
    hint: Optional[str]
    user_description: Optional[str]
    display_mode: Optional[str]
    value_if_null: object = None
```

### 5.2 Public API

| Function | Returns | Notes |
|----------|---------|-------|
| `load_fields()` | `dict[str, FieldSpec]` | All fields keyed by UUID; asserts UUID uniqueness |
| `fields_by_tender_key()` | `dict[str, list[FieldSpec]]` | Groups by tender_key; excludes fields with tender_key=None |
| `fields_by_field_name()` | `dict[str, list[FieldSpec]]` | Groups by field_name; one name can appear in multiple scopes |

Note: `fields_by_scope()` and `fields_by_sheet()` are NOT present in the generated file. Scope-based filtering is done by callers using `scope in resolution_order[leaf_scope]`.

---

## 6. app.py Module-Level Constants

All constants are loaded from config files at import time. No domain knowledge is hardcoded.

| Constant | Type | Source | Purpose |
|----------|------|--------|---------|
| `_SIGNED_UNITS` | `frozenset` | `config/unit_semantics.json` | Units where 0 is a real constraint for KO_IF_LT |
| `_EXT_COLUMNS` | `list[str]` | `config/sqlite_schema.json["extensions_columns"]` | Extension column list for sync_airtable |
| `_FIELDS_BY_TENDER_KEY` | `dict` | `fields_by_tender_key()` | tender_key -> list[FieldSpec] |
| `_FIELDS_BY_FIELD_NAME` | `dict` | `fields_by_field_name()` | field_name -> list[FieldSpec] |
| `_TK_TO_UUIDS` | `defaultdict(list)` | Built from `load_fields()` | tender_key -> list of UUIDs; used by `_criteria_to_uuid_keyed()` |
| `_AP0_CONSTRAINED_FIELDS` | `dict` | Built from `_FIELDS_BY_TENDER_KEY` | tender_key -> {allowed: set, allowed_list: list} for Dropdown/Multi-Select |
| `_NUMERIC_KO_TENDER_KEYS` | `frozenset` | Built from `_FIELDS_BY_TENDER_KEY` | tender_keys for Float/Integer KO_IF_LT or KO_IF_GT fields |
| `_NUMERIC_KO_FIELD_HINTS` | `dict` | Built from `_FIELDS_BY_TENDER_KEY` | tender_key -> {hint, scope} for Pass 4c prompt construction |
| `_4C_EXTRACTION_DIRECTION` | `dict` | Built from `_FIELDS_BY_TENDER_KEY` | tender_key -> direction string (MAXIMUM/MINIMUM) |
| `_VT_MAP_CFG` | `dict` | `scope_registry.json["variant_map"]` (Step 7 rename of the old `vehicle_types.json["vt_map"]`) | variant_lower -> canonical product-type name |
| `_VNA_CFG` | `set` | `vehicle_types.json["vna_subtypes"]` | LLM output strings that indicate VNA |
| `_VT_OVERRIDES` | `list` | `vehicle_types.json["text_overrides"]` | [{regex, canonical, vna}] for text-based VT override |
| `_VNA_APPLICABLE` | `set` | `vehicle_types.json["vna_applicable_types"]` | Canonical types for which VNA gate applies |
| `_AGV_DETECT_KWS` | `list` | `scope_registry.json["agv_detection_keywords"]` (Step 7; moved from vehicle_types.json) | Domain-detection keyword fallback |
| `_DOMAIN_KWS` | `dict` | `scope_registry.json["domain_keywords"]` | domain_id -> keyword list, for the domain-detection LLM-fallback (§1.2) |
| `_FIELD_TEXT_FALLBACKS` | `list` | `vehicle_types.json["field_text_fallbacks"]` | Regex-based field value overrides |
| `_LEGACY_MAP` | `dict` | `scope_registry.json["legacy_map"]` | Canonical product-type name -> leaf scope_id |
| `_RESOLUTION_ORDER` | `dict` | `scope_registry.json["resolution_order"]` | leaf_scope_id -> ordered list of ancestor scope_ids |
| `_EXTRACTABLE_DOMAINS` | `frozenset` | Derived from `scope_registry.json["scopes"]` | All scope_ids with `parent == "*"` (e.g. `{"Logistics:AGV", "FoodBev:Refrigeration"}`) — replaces the single-domain-era `_SHARED_SCOPE` |
| `_SINGLE_LEAF_DOMAINS` | `frozenset` | Derived from `scope_registry.json["scopes"]` | Domain scope_ids with zero children — Pass 4a is skipped for these (OI-107) |
| `_DOMAIN_CLASSIF_VALUES` | `dict` | Derived from `scope_registry.json["scopes"]` | domain scope_id -> frozenset of valid Pass 4a `canonical_name` outputs (multi-leaf domains only) |
| `_VALID_VTS` | `set` | Derived from `scope_registry.json["scopes"]` | `canonical_name` of every scope node with a `scoring_bucket` key — valid product types for `/rematch` VT change |
| `CATEGORY_LIST` | `str` | `nace_codes.json["codes"]` | NACE code list for Pass 3 prompt |
| `_DOMAIN_SYSTEM` | `dict[str, str]` | `build_system_context(domain_prefix=sid)` per `sid` in `_EXTRACTABLE_DOMAINS` | One LLM system prompt per domain (replaces the single-domain-era `AGV_SYSTEM` constant) |
| `_DOMAIN_CLASSIF_TEMPLATES` | `dict` | `config/prompts/classification_template_{domain_slug}.txt` per domain | Pass 4a prompt template per domain (multi-leaf domains only) |
| `_PRODUCT_TYPE_TEMPLATES` | `dict` | `config/prompts/extraction_template_{tab_name}.txt` per scope node, keyed by `canonical_name` | Pass 4b prompt template per leaf product type |
| `_4A_SKIP` | `frozenset` | `vehicle_types.json["4a_fields"]` | Fields from Pass 4a to skip in 4b AP0 validation |

### 6.1 Startup Assertions (fail-fast)

**Updated for the multi-domain rollout** — the constants and assertions below reflect the
current `app.py` (verified 2026-07-31), not the single-domain-era version this table
previously described:

```python
_shared_candidates = [d["scope_id"] for d in _scope_reg["scopes"].values() if d.get("parent") == "*"]
assert len(_shared_candidates) >= 1, "scope_registry.json: expected at least 1 child of '*'"
_EXTRACTABLE_DOMAINS = frozenset(_shared_candidates)   # e.g. {"Logistics:AGV", "FoodBev:Refrigeration"}
assert _LEGACY_MAP, "scope_registry.json missing legacy_map"
assert set(_LEGACY_MAP.values()) <= set(_RESOLUTION_ORDER)

# Domain-scoped valid Pass 4a output values — only multi-leaf domains need this;
# single-leaf domains (no children) skip Pass 4a entirely (OI-107).
for _dom in _EXTRACTABLE_DOMAINS:
    _children = [n["canonical_name"] for n in _scope_reg["scopes"].values()
                 if n.get("parent") == _dom and n.get("canonical_name")]
    if _children:
        _DOMAIN_CLASSIF_VALUES[_dom] = frozenset(_children)
    else:
        _single_leaf_domains.add(_dom)
_SINGLE_LEAF_DOMAINS = frozenset(_single_leaf_domains)
assert _SINGLE_LEAF_DOMAINS | set(_DOMAIN_CLASSIF_VALUES) == _EXTRACTABLE_DOMAINS

# variant_map (Step 7 rename of vt_map) canonical values must resolve via legacy_map
assert set(_VT_MAP_CFG.values()) <= set(_LEGACY_MAP)

# Allowed_values consistency across multi-VT specs for the same tender_key
for _tk, _specs in _FIELDS_BY_TENDER_KEY.items():
    assert len(set(tuple(_s.allowed_values or []) for _s in _specs)) <= 1

# Numeric KO infrastructure must be non-empty
assert _NUMERIC_KO_TENDER_KEYS
assert _NUMERIC_KO_FIELD_HINTS
assert _4C_EXTRACTION_DIRECTION
```

---

## 7. src/matching.py Module-Level Constants

| Constant | Type | Source | Purpose |
|----------|------|--------|---------|
| `NULL_KO_PENALTY` | `int` = 15 | Hardcoded | Points deducted per null numeric KO field |
| `_SIGNED_UNITS` | `frozenset` | `config/unit_semantics.json` | Same as app.py; loaded independently |
| `_fields` | `dict[str, FieldSpec]` | `load_fields()` | All AP0 fields by UUID |
| `_scope_registry` | `dict` | `config/scope_registry.json` | Full scope registry |
| `_LEGACY_MAP` | `dict` | `_scope_registry["legacy_map"]` | Canonical product-type name -> scope_id |
| `OPERATORS` | `dict` | Module-level | operator name -> operator function |

Note: `matching.py` has **no** `_SHARED_SCOPE` / `_EXTRACTABLE_DOMAINS`-equivalent constant —
unlike `app.py`, it never needs to enumerate domains, only to resolve one supplier's product
type to its scope chain (`Matcher._score_one()`, `matching.py:443-449`: `vt_scope =
_LEGACY_MAP.get(prod.product_type)` then `_scope_registry["resolution_order"].get(vt_scope, [])`).

### 7.1 Guardian S2 Assertion

At startup, `matching.py` asserts that every `canonical_name` present anywhere in
`scope_registry.json["scopes"]` is also a key in `legacy_map` (`matching.py:53-64`):

```python
_scope_registry = json.loads(...)
_LEGACY_MAP = _scope_registry.get("legacy_map", {})
assert _LEGACY_MAP, "scope_registry.json missing legacy_map — run generate_all.py"
_canon_names = {node["canonical_name"] for node in _scope_registry["scopes"].values()
                if node.get("canonical_name")}
assert _canon_names <= set(_LEGACY_MAP), (
    f"canonical_names without legacy_map entry: {_canon_names - set(_LEGACY_MAP)}"
)
```

---

## 8. Matching Operators

### KO_IF_LT

K.O. if `float(supplier_value) < float(tender_value)`.

Use case: payload capacity, lifting height, fleet size, operating hours — supplier must meet or exceed the requirement.

Null behavior: `None` on either side -> no K.O. Tender value of 0 -> no effective requirement (unless field unit is in `_SIGNED_UNITS`).

### KO_IF_GT

K.O. if `float(supplier_value) > float(tender_value)`.

Use case: minimum aisle width, turning radius — supplier must fit within the constraint.

Null behavior: `None` on either side -> no K.O. Tender value of 0 with unsigned unit -> the most restrictive possible constraint (supplier aisle width must be <= 0, which is impossible for any real supplier) — this is a data quality issue, not intended behavior. Signed units (°C, °F) are excluded from the zero-treatment.

### KO_IF_NEQ

K.O. if `str(supplier_value).lower() != str(tender_value).lower()`.

Use case: exact categorical match (e.g. agv_type must match exactly).

Null behavior: `None` on either side -> no K.O. Lists on either side -> skip (use KO_SUBSET for list fields).

### KO_BOOL_REQUIRED

K.O. if tender is "required" (or True or 1) AND supplier is explicitly False (0).

Use case: capabilities that are optionally required (outdoor_capable, cleanroom_capable).

Null behavior: `None` supplier -> no K.O. (LL-06: absence of data != absence of capability).

### KO_BOOL_EXCLUSIVE

Bidirectional boolean gate.

- Tender = "required" AND supplier = False -> K.O.
- Tender = "not_required" AND supplier = True -> K.O.
- Tender = None or "preferred" -> no K.O.
- Supplier = None -> no K.O. (LL-06)

Use case: VNA capability — VNA-required tenders exclude non-VNA suppliers; non-VNA tenders exclude VNA suppliers.

### KO_SUBSET

K.O. if no overlap between tender list and supplier list (substring matching in both directions).

Use case: navigation_type, service_coverage, load_type — at least one common value required.

Null behavior: empty tender or supplier list -> no K.O.

Substring matching: "SLAM" matches "Natural Feature (SLAM)" and vice versa.

---

## 9. Null Rule (LL-06) and Null Penalty

**LL-06:** `None` on either side never triggers a hard K.O. for numeric or categorical operators. Absence of data is not evidence of absent capability.

**Null KO penalty:** When a tender specifies a numeric KO requirement (KO_IF_LT or KO_IF_GT) and the supplier has `None` for that field:
- Supplier is NOT disqualified
- A penalty of `-15 pts` (`NULL_KO_PENALTY`) is applied
- Field is added to `null_gap_fields` for UI display

This ranks suppliers with confirmed data above suppliers with unknown data, without excluding either.

**_is_active_requirement() check:** The null penalty and null_gap tracking both use `_is_active_requirement()` to determine whether the tender actually has an active requirement. For boolean operators, `False`/`"not_required"` tender values are not active requirements and do not generate null_gap entries.

---

## 10. Source-Span Guard (src/json_repair.py)

All functions in this module are field-agnostic. Never add field names, AP0 allowed-values lists, or domain knowledge to this module.

### 10.1 enforce_source_spans()

```python
def enforce_source_spans(
    domain_criteria: dict,
    document_text: str,
    numeric_ko_keys,       # frozenset of tender_keys subject to the guard
    four_c_abstained: set, # tender_keys where Pass 4c returned null
    units: dict = None,    # tender_key -> unit string, for the Layer 2 rescue check (D0). Defaults to {}.
) -> tuple[dict, list[str], list[SpanEvent]]:
```

For each key in `numeric_ko_keys` with a non-null value in `domain_criteria`, applies three layers in order. Returns `(domain_criteria, messages, events)` — `events` is a `list[SpanEvent(field, layer, value, source)]`, one per field actually nulled OR rescued, consumed by app.py for D1 provenance attribution and (since D0) filtered for `layer == "L2_RESCUED"` before feeding `_nulled_by`.

**Layer 1:** `domain_criteria.get(f"{key}_source")` is falsy -> null value, add message.

**Layer 0:** `source_is_grounded(value, source, document_text)` returns False -> null value, add message.

**Layer 2 (scoped to abstentions):** `key in four_c_abstained` AND `source_confirms_value(value, source)` returns False -> null value, add message, **unless a rescue fires first (D0, 2026-07-28):** if `document_supports_value_with_unit(value, units.get(key, ""), document_text)` returns True, the value is kept instead — recorded as `SpanEvent(layer="L2_RESCUED", ...)`, not a null. This addresses Pass 4b echoing the AP0 field hint as `_source` (breaking the citation channel) for a value that is otherwise genuinely present in the document.

### 10.2 source_is_grounded(value, source, document, unit="")

Checks whether the LLM's self-reported source quote is actually present in the real document.

Two binary conditions (no fractions, no calibrated cutoffs):

1. **Anchor check:** value's digit-string (with locale ambiguity via `_interpret_number_token()`) must occur in the real document. The exact-scale target (`value` itself) anchors unconditionally, as always — **this remains an open gap, see docs/architecture.md §5.1**. A ×1000/÷1000 scale-converted target is now **unit-gated** (fixed 2026-07-31, commit `2724749`, OI-114 Defect B): it only anchors if `unit` is a key in the generic `_METRIC_PREFIX_SCALE` table (`mm`/`cm`/`m`/`km`/`g`/`kg`/`t`) AND a metric-prefix unit token sits within 3 chars of the matched document number (`_adjacent_metric_prefix_unit()`) AND that unit, applied to the document's number, dimensionally resolves to the same real-world quantity as `value` under `unit` (`_converted_anchor_dimensionally_valid()`). If `unit` is empty or not a `_METRIC_PREFIX_SCALE` key (non-metric units: `%`, `°C`, `h`, `kW`, ...), converted-scale targets anchor unconditionally — a deliberate carve-out, not a bug, for units this table has no opinion about.
2. **Co-location check:** at least one distinctive content word (> 3 chars, not a function word) from the source quote must appear within `_GROUNDING_WINDOW_CHARS = 80` chars of an anchor occurrence. Narrowed via `_phrase_words_around_value()` to the ±3-word phrase around the value's number in the source when available, falling back to whole-source content words otherwise.

Returns True if both conditions hold. Zero values always return True.

`enforce_source_spans()` passes `unit=units.get(key, "")` — the field's real AP0 `Unit` column
value, via the `units` dict callers must now supply (`app.py` builds it as
`_NUMERIC_KO_FIELD_UNITS`, one unit string per numeric-KO tender_key, asserted non-empty at
startup for every key in `_NUMERIC_KO_TENDER_KEYS`).

**Root cause this fix closed:** `source_is_grounded()`'s anchor target set used to be
`{av, av*1000, av/1000}` unconditionally, so a fabricated value like `10000` (mm) always
included a bare `10` in its anchor set — and a bare `10` is a near-certain coincidental
substring in any real multi-page document (dates, list indices, unrelated quantities),
effectively defeating the anchor check for any round-thousands fabrication. This is exactly
what let the `required_lifting_height=10000` fabrication described in the OI-114 incident
(`docs/architecture.md` §4.1) slip past Layer 0 on one specific run, after `user_description`
had already been stripped from the prompt (that fix closed the *prompt-poisoning* side of the
incident; this fix closes the independent *guard* side). See `tests/unit/test_source_is_grounded.py::test_U_SG_15`
through `test_U_SG_21` for the regression coverage, and `test_U_SS_11`
(`tests/unit/test_source_span_enforcement.py`, written 2026-06-16) for the residual open case
this fix does *not* cover (exact-scale, non-converted collisions).

### 10.3 source_confirms_value(value, source_text)

Checks whether the source text contains a number matching the value within unit-scale tolerance.

- Handles DE locale (comma decimal) and EN locale (period decimal)
- Tolerance: exact match OR ×1000 OR ÷1000 (unit scale)
- Zero values always return True

### 10.4 _interpret_number_token(raw)

Returns the set of all plausible float interpretations of a raw number string, handling both locale conventions without choosing one. Used by source_confirms_value(), source_is_grounded(), and document_supports_value_with_unit().

### 10.4a document_supports_value_with_unit(value, unit, document, window=_UNIT_GROUNDING_WINDOW_CHARS)

D0 fix (2026-07-28): the Layer 2 rescue check. Returns True if the value's digit-string occurs in `document` with `unit` as a token within `window` chars, bidirectionally (unit may precede or follow the number in real document layouts).

- Requires an EXACT digit-string match (locale-normalized via `_interpret_number_token()` only) — deliberately does NOT apply the ×1000/÷1000 scale tolerance used by `source_confirms_value()`/`source_is_grounded()`, to avoid rescuing a fabricated value that happens to be a scaled match of an unrelated real number elsewhere in the document.
- Returns False unconditionally if `unit` is empty/falsy or a single alphabetic character (e.g. `m`, `K`, `h`) — these collide with unrelated document text too often (e.g. unit `m` matching `"58,000 m²"`) to be a reliable signal.
- Zero values always return True (same convention as `source_confirms_value()`/`source_is_grounded()`).
- Field-agnostic, pure function — no field names, no AP0 value lists, no domain knowledge.
- Uses `_UNIT_GROUNDING_WINDOW_CHARS = 80`, a constant independent from `_GROUNDING_WINDOW_CHARS` (different question: tight unit-token adjacency vs. fuzzy word co-location) — do not merge these constants.

### 10.5 repair_and_parse(raw)

5-stage LLM JSON repair parser. Never call `json.loads()` directly on LLM output.

| Stage | Action |
|-------|--------|
| 0 | Brace-balanced extraction (finds shortest complete JSON object) |
| 1 | Direct `json.loads()` |
| 2 | Remove JS-style comments (`// ...`) |
| 3 | Fix unescaped newlines inside strings |
| 4 | Truncation fix (append closing suffix candidates) |
| 5 | Generic regex field extraction (field-agnostic; sets `_parse_method = "regex_fallback"`) |

Raises `ValueError` if no JSON-like structure can be extracted at all.

---

## 11. config/vehicle_types.json

Generated by `generate_all.py`. **Corrected for the multi-domain rollout (Step 7):** several
keys previously documented here migrated to `config/scope_registry.json` and no longer exist in
this file — verified directly against the current file (2026-07-31):
`python3 -c "import json; print(list(json.load(open('config/vehicle_types.json')).keys()))"`
→ `['vt_map', 'vna_subtypes', 'text_overrides', 'keyword_map', 'llm_guide', 'field_text_fallbacks', '4a_fields']`.

| Key | Type | Purpose |
|-----|------|---------|
| `vt_map` | dict | llm_output_lower -> canonical VT name (superseded at runtime by `scope_registry.json["variant_map"]`, which `app.py` actually loads as `_VT_MAP_CFG` — this key appears to be a vestigial duplicate; verify before relying on it) |
| `vna_subtypes` | list | LLM output strings indicating VNA (without separate canonical mapping) |
| `text_overrides` | list | [{regex, canonical, vna}] — regex-based VT override against full PDF text |
| `keyword_map` | dict | canonical_vt -> list of fallback keywords, used by `context_builder.py::product_type_keyword_fallback()` |
| `llm_guide` | list | [{name, description, key_indicators}] — legacy Pass 4a prompt content; current Pass 4a templates are the per-domain `classification_template_*.txt` files (§14) |
| `field_text_fallbacks` | list | [{tender_key, regex, value, only_if_null}] |
| `4a_fields` | list | Field tender_keys determined in Pass 4a; excluded from 4b AP0 correction |

**Migrated to `config/scope_registry.json`** (verify against §3 above before trusting any doc that
still attributes these to `vehicle_types.json`):
- `vt_prompt_map` → replaced by deriving `_PRODUCT_TYPE_TEMPLATES` directly from each scope
  node's `tab_name` (`app.py`: `extraction_template_{tab_name.lower()}.txt`)
- `scoring_bucket_map` / `vna_applicable_types` → now per-node fields on `scope_registry.json["scopes"][leaf_id]`: `scoring_bucket`, `vna_applicable` (booleans/strings attached directly to each leaf, e.g. `Logistics:AGV:Forklift` has `"vna_applicable": true, "scoring_bucket": "forklift_specific", "vna_hint": "VNA (very narrow aisle) operation is required."`)
- `agv_detection_keywords` → now `scope_registry.json["agv_detection_keywords"]`, alongside a new `domain_keywords` dict (`{domain_scope_id: [keywords...]}`) that the domain-detection pass (§1.2, §14) actually uses at runtime — `_DOMAIN_KWS` in `app.py`
- `vna_context_hint` → now the per-node `vna_hint` field shown above, keyed per leaf scope rather than one global string

---

## 12. config/plausibility.json

Generated from AP0 Plausibility Min/Max/Unit columns + platform_config Unit Conversions. Maps tender_key -> range definition.

```json
{
  "required_max_payload": {
    "min": 0.5,
    "max": 50000.0,
    "unit": "kg",
    "label": "max_payload",
    "conversion": null
  },
  "required_lifting_height": {
    "min": 500.0,
    "max": 20000.0,
    "unit": "mm",
    "label": "lifting_height",
    "conversion": {
      "llm_alias": "m",
      "factor": 0.001,
      "threshold": 30.0
    }
  }
}
```

If `conversion` is non-null: when the extracted value exceeds `threshold`, multiply by `factor` (mm -> m: 12000 * 0.001 = 12). If the converted value is within [min, max], accept it; otherwise set to None.

---

## 13. config/sqlite_schema.json

Generated from `② Structure` tab (structural columns) + scope tabs (business field columns).

Top-level keys:

| Key | Type | Purpose |
|-----|------|---------|
| `companies` | str | CREATE TABLE SQL for companies |
| `products` | str | CREATE TABLE SQL for products |
| `base_models` | str | CREATE TABLE SQL for base_models |
| `base_model_extensions` | str | CREATE TABLE SQL for base_model_extensions |
| `bool_fields` | list[str] | All Boolean field_names (for coercion in sync_airtable) |
| `int_fields` | list[str] | All Integer field_names |
| `float_fields` | list[str] | All Float field_names |
| `multiselect_fields` | list[str] | All Multi-Select field_names (pipe-separated in SQLite) |
| `companies_columns` | list[str] | Ordered column list for companies INSERT |
| `products_columns` | list[str] | Ordered column list for products INSERT |
| `extensions_columns` | list[str] | Ordered column list for base_model_extensions INSERT |

---

## 14. Prompt Files (config/prompts/)

All files under `config/prompts/` are generated by `generate_all.py` except where noted.
**Updated for the multi-domain rollout** — several files below did not exist at the last
full pass of this doc (2026-07-10); the list is now verified against the actual directory
contents (2026-07-31).

| File | Generated | Purpose |
|------|-----------|---------|
| `basic_system.txt` | Yes | System prompt for Pass 1 (basic extraction) |
| `basic_template.txt` | Yes | User prompt template for Pass 1; placeholder: `{text}` |
| `domain_detection_template.txt` | Yes | User prompt for the domain-detection pass (new, between NACE and Pass 4a); placeholders: `{tender_category}`, `{summary}` |
| `contact_system.txt` | Yes | System prompt for Pass 2 (contact fallback) |
| `contact_template.txt` | Yes | User prompt template for Pass 2; placeholder: `{text}` |
| `nace_system.txt` | Yes | System prompt for Pass 3 (NACE classification) |
| `nace_template.txt` | Yes | User prompt template for Pass 3; placeholders: `{tender_category}`, `{buyer_industry}`, `{category_list}` |
| `scope_classification_template.txt` | Yes | Generic Pass 4a template (Step 7); falls back to `vehicle_type_template.txt` if absent |
| `classification_template_logistics_agv.txt` | Yes | Per-domain Pass 4a template for `Logistics:AGV` (multi-leaf domain) |
| `classification_template_foodbev_refrigeration.txt` | Yes | Per-domain Pass 4a template for `FoodBev:Refrigeration` — present for completeness but never invoked at runtime, since this domain is single-leaf and skips Pass 4a entirely (OI-107) |
| `extraction_template.txt` | Yes | Combined fallback extraction template (all scopes); placeholder: `{text}` |
| `extraction_template_agv_forklift.txt` | Yes | Pass 4b template for Forklift AGV; placeholders: `{text}`, `{vehicle_type}`, `{vna_context}` |
| `extraction_template_agv_tugger.txt` | Yes | Pass 4b template for Tugger AGV |
| `extraction_template_agv_amr.txt` | Yes | Pass 4b template for Mobile AMR |
| `extraction_template_foodbev_refrigeration.txt` | Yes | Pass 4b template for Industrial Refrigeration |
| `extraction_system.txt` | Yes | Appended to every domain's system prompt (`build_system_context()`); shared extraction rules, not domain knowledge |
| `extraction_retry_system.txt` | Yes | System prompt for JSON retry/correction passes |
| `extraction_retry_template.txt` | Yes | User prompt for JSON retry (all fields, null schema) |

**Note:** generate_all.py prunes stale `extraction_template_*.txt` files that are no longer referenced by the scope registry's per-leaf template map.

**Not a prompt file, but templated the same way and worth listing here:** `config/industry_readme_{domain_slug}.md` (e.g. `industry_readme_logistics_agv.md`, `industry_readme_foodbev_refrigeration.md`) — one per domain, synced from `Spec/haystacked_industry_readme_{slug}.md`, and concatenated into that domain's system prompt by `src/context_builder.py::build_system_context(domain_prefix=...)`. See §15.

### 14.1 _fill() Function

`_fill(template, **kwargs)` in `app.py` replaces `{key}` placeholders without touching JSON braces in the template:

```python
def _fill(template: str, **kwargs) -> str:
    for key, value in kwargs.items():
        template = template.replace("{" + key + "}", str(value) if value is not None else "")
    return template
```

This avoids the `str.format()` pitfall of eating `{"field": null}` JSON syntax in templates.

### 14.2 Numeric KO Field Source Instrumentation

For each numeric KO field (Float/Integer with KO_IF_LT or KO_IF_GT) in the extraction template, `build_extraction_template()` automatically adds:
1. A `_CONSERVATIVE EXTRACTION` directive in the hint (extract MAXIMUM for KO_IF_LT, MINIMUM for KO_IF_GT)
2. A companion `<field>_source` entry in the JSON schema requiring the verbatim quote

This is what feeds the source-span guard. Fields without a `hint` in AP0 do not appear in the extraction template and do not get source instrumentation.

---

## 15. src/context_builder.py

`build_system_context()` assembles the AGV system prompt (used for Passes 4a, 4b, 4c):

1. Loads `config/industry_readme_{slug}.md` for the given domain slug (domain knowledge); raises FileNotFoundError if slug file is absent — run generate_all.py
2. Iterates all FieldSpec entries; deduplicates by field_name; separates KO and COND_KO fields
3. Builds `## Field-level descriptions` section listing each KO/COND_KO field name + level only (`spec.user_description` deliberately excluded since 2026-07-30 — it's UI-only text for the Clarification Dialog, not LLM instruction text; leaking it into this prompt caused a confirmed hallucination)
4. Appends 9 critical matching rules (conservative extraction, anti-hallucination, etc.)

`agv_type_keyword_fallback(text)` — independent of LLM — scores the first 5,000 chars against keyword lists from `vehicle_types.json["keyword_map"]` and returns the highest-scoring canonical VT name, or None if no keywords match. Used as fallback when Pass 4a fails.

---

## 16. TenderRequirements

`TenderRequirements` (in `src/matching.py`) wraps a `TenderRun` for use by the matching engine.

`.get(field_name)` resolves by field_name -> UUID(s) via `fields_by_field_name()`, returns first non-None value. Falls back to direct key lookup for from_dict callers.

`TenderRequirements.from_dict(raw_dict)` — accepts a UUID-keyed criteria dict from `/match` and `/rematch` endpoints, wraps it in an ephemeral `TenderRun`.

`_criteria_to_uuid_keyed(criteria)` in `app.py` translates tender_key -> UUID(s) before passing to the matching engine. Multi-sheet fields (same tender_key in multiple scopes) are broadcast to all matching UUIDs.

---

## 17. generate_all.py Pipeline

`scripts/generate_all.py` executes in order:

1. Read `③ Scope Registry` tab -> `data_sheets`, `shared_tab`, `leaf_tabs`, `tab_scope_map`, `scopes_raw`
2. Read field data from all `data_sheets` -> `field_levels`, `scoring_weights`, `extraction_schema`
3. Read `Vehicle Types` tab -> `vehicle_types`
4. Read `Field Fallbacks` tab -> `field_text_fallbacks` (merged into vehicle_types)
5. Read `② Structure` tab -> `sqlite_schema` (structural columns)
6. Read scope tabs (business columns) -> extend `sqlite_schema`
7. Read `platform_config.xlsx` -> NACE codes, platform scope, basic schema, unit conversions
8. Build `plausibility` = `read_plausibility()` + `unit_conversions` (assert numeric KO fields have plausibility ranges)
9. `emit_fields_json()` -> write `config/fields.json` and `src/field_spec.py`; apply SA-22/SA-25 hygiene asserts
10. `_write_scope_registry()` -> write `config/scope_registry.json`; build `legacy_map` and `resolution_chains`
11. Build VT-specific prompt templates for each leaf tab
12. Add runtime-derived fields to vehicle_types (scoring_bucket_map, vna_applicable_types, agv_detection_keywords, vt_prompt_map, 4a_fields, vna_context_hint)
13. Write all config files and prompt files
14. Prune stale `extraction_template_*.txt` files
15. Run `validate_vs_sqlite()` and `validate_no_unit_in_field_name()` -> print warnings / hard-assert

**`_scope_resolution_chain(scope_id, parent_of)`** — single implementation used by both `_write_scope_registry` (to store resolution_order in JSON) and `generate()` (to select fields per VT for prompt templates). Walks the scope tree from leaf to root and returns the chain root-first.

**Dry-run mode** (`--dry-run`): reads everything and validates, but writes nothing. Prints a preview of what would be written.

---

## 18. VNA Logic End-to-End

### Detection

1. Pass 4a: LLM returns `required_vna_capable=true` OR `required_agv_type` normalizes to a value in `_VNA_CFG`
2. After 4a: text override regex applied; if `override["vna"]` is True, `is_vna_subtype = True`

### Matching Assignment

```python
new_req["required_vna_capable"] = (
    "required"     if is_vna_subtype                                      # VNA tender
    else "not_required" if canonical_agv_type in _VNA_APPLICABLE         # non-VNA forklift tender
    else None                                                              # Tugger/AMR — no gate
)
```

`_VNA_APPLICABLE = ["Forklift AGV"]` — loaded from `vehicle_types.json["vna_applicable_types"]`.

### Operator Behavior

`KO_BOOL_EXCLUSIVE` on the `vna_capable` field:

| Tender required_vna_capable | Supplier vna_capable | Result |
|-----------------------------|---------------------|--------|
| "required" | True | Pass |
| "required" | False | K.O. |
| "required" | None | Pass (LL-06) |
| "not_required" | True | K.O. (VNA equipment in standard aisle) |
| "not_required" | False | Pass |
| "not_required" | None | Pass (LL-06) |
| None (Tugger/AMR) | any | Pass (no gate) |

---

## 19. /rematch Endpoint Logic

Accepts `{analysis_id, overrides, vehicle_type?}` and re-runs matching against the cached extraction.

1. Load cached `domain_criteria` from `_analyses[analysis_id]`
2. Apply `overrides` (by field_name -> tender_key via `_FIELDS_BY_FIELD_NAME`; empty string -> None)
3. If `vehicle_type` changed: clear all fields scoped to the old VT's leaf scope from criteria; reset `required_vna_capable = None` (cannot determine VNA without re-running Pass 4a)
4. Apply `validate_domain_criteria()` (same unit conversion and plausibility as main flow)
5. Apply `_criteria_to_uuid_keyed()`
6. Run `match_suppliers_new()` and return results
7. Update `_analyses[analysis_id]` so `/api/last-result` stays in sync

---

## 20. Step 6 Behavior Changes (UFR Sprint)

The following fields changed level or operator in AP0 during Step 6 of the UFR Sprint:

| Field | Old level/operator | New level | Reason |
|-------|--------------------|-----------|--------|
| `navigation_type` | COND_KO / KO_SUBSET | CONTEXT | No matching, informational only |
| `battery_type` | COND_KO | CONTEXT | No matching, informational only |
| `fleet_management_system` | COND_KO | CONTEXT | No matching, informational only |
| `max_fleet_size` | SCORING | CONTEXT | No matching, informational only |
| `ingress_protection_rating` | COND_KO | CONTEXT | No matching, informational only |
| `floor_flatness_req` | COND_KO | CONTEXT | No matching, informational only |
| `integration_capability` | SCORING | COND_KO / KO_SUBSET | Now a real matching criterion |
| `infrastructure_required` | COND_KO / KO_BOOL_REQUIRED | Renamed + inverted | See infrastructure_free below |
| `infrastructure_free` | (new field) | COND_KO / KO_BOOL_REQUIRED | TRUE = no infrastructure needed |

**infrastructure_free boolean semantics:**
- True: vehicle operates without fixed infrastructure (SLAM, contour navigation, free-path planning)
- False: vehicle requires fixed infrastructure (magnetic tape, QR codes, reflectors, wire guidance)

The field replaces `infrastructure_required` with inverted boolean: if a tender is `infrastructure_free=True` (no infrastructure available), then a supplier with `infrastructure_free=False` (requires infrastructure) receives a K.O.

---

## 21. Known Gaps and Technical Debt

| ID | Area | Description | Severity |
|----|------|-------------|----------|
| OI-55 | Unit naming | **Fully resolved (OI-115b commit `26d4195`, then OI-115c commits `3b9f65d`/`e3ce309`).** The 3 fields where field_name suffix (_mm) disagreed with AP0 Unit (m) were realigned to `mm` (OI-115b); all 38 fields with a redundant unit suffix then had it stripped from field_name entirely (OI-115c). `validate_unit_suffix_drift()` was repurposed into `validate_no_unit_in_field_name()` — a hard assert (not a warning) enforcing no field_name may encode its own unit, going forward. | Resolved |
| OI-56 | Data loader | Startup assertion detects column-name collisions between Base Model and Product/Company. | Mitigation active |
| M1 | Hardcoding | **Resolved (OI-115b).** The old m->mm conversion factor (0.001) + `_to_match_units()` + its startup assertion are all deleted. A reversed mm->m auto-heal conversion (factor 1000) now lives in `validate_domain_criteria()`'s plausibility gate, with the gate direction derived generically from whether `factor < 1` or `> 1` — no field-name strings involved. | Resolved |
| H2 | Sync | sync_airtable.py positional INSERTs not yet fully schema-driven from column lists. | Medium |
| OI-73 | Architecture | Multi-domain scoping (Step 7): **resolved.** `_shared_candidates` assertion relaxed from "exactly 1" to "at least 1" child of `*`; `FoodBev:Refrigeration` is live as a second domain alongside `Logistics:AGV`. See §1.2. | Resolved |
| — | Docs | `CLAUDE.md`'s "Data Flow" section still describes the pre-multi-domain, `is_agv_amr`-flag-based pipeline. Not updated as part of this pass — flagged for a separate, deliberate update rather than silently drifting from the repo's canonical doc. | Medium |

---

## 22. Known Risks (Hallucination Guard, 2026-07-31)

This section is a code-level companion to `docs/architecture.md` §5, which has the same list
in plain language with fuller narrative context (concrete supplier/tender examples, before/after
numbers). Cross-references to source memory notes are omitted here — see architecture.md for
those. All items current as of 2026-07-31 unless marked resolved.

### 22.1 Open — exact-scale anchor collisions (`source_is_grounded()`)

The `2724749` fix (§10.2) only unit-gates the **converted-scale** target family
(`av*1000`, `av/1000`). The **exact-scale** target (`av` itself) still anchors unconditionally —
by design, per the function's docstring ("The exact-scale target ... anchors unconditionally,
as always"). A fabricated value that happens to numerically match a real, unrelated number **at
the same scale** elsewhere in the document still passes Layer 0. Flagged and tracked since
2026-06-16 by `test_U_SS_11` (`tests/unit/test_source_span_enforcement.py`) — still red-lit as
an accepted, unresolved gap, not a regression.

### 22.2 Open — no generation-time check for numeric literals outside `LLM Hint`

`generate_all.py` has no assertion that catches a numeric-literal example creeping into any
AP0 text column that reaches an LLM prompt. The 2026-07-30 fix removed one whole column
(`user_description`) from the LLM-facing surface, which structurally shrinks this risk, but the
remaining `LLM Hint` column (and any future prompt-construction code path that reads a new AP0
column) has no automated guard — only manual review.

### 22.3 Open — Pass 4c abstention rate on `max_payload` provides near-zero signal

Observed near-100% null rate from Pass 4c for this specific field across multiple live-corpus
runs, even when Pass 4b extracts it correctly from plain-stated prose. Not yet investigated for
other numeric-KO fields — unknown whether this is field-specific or systemic.

### 22.4 Open — no automated fallback when Pass 4c overrides Pass 4b and then gets rejected

Current behavior (`app.py`, Pass 4c block): a non-null Pass 4c result unconditionally overwrites
`domain_criteria[key]` and `domain_criteria[key + "_source"]`. If the source-span guard then
nulls that overridden value, Pass 4b's original (possibly correct, possibly still
genuinely-grounded) value and source are already gone — there is no snapshot-restore path.
`_pre_4c_snapshot` (D1, `app.py`) captures the pre-4c state for **provenance/forensics only**; it
is never read back into `domain_criteria` at runtime. Tracked as an open design question (see
`.claude/agent-memory/senior-architect/` project notes referencing "4c arbitration design"), not
yet resolved.

### 22.5 Open — bistable extraction on at least two fields, one test tender

`required_max_payload` and `required_min_aisle_width` on the CompanyX test tender have
flipped between a correct non-null value and null/wrong across repeated identical pipeline runs
against the identical source PDF, with `temperature: 0.0` in the Ollama request. Not a guard
defect — LLM sampling variance at the generation stage that empirically survives temp=0.0 on
this model/hardware combination. Not systematically characterized beyond this one tender.

### 22.6 Open — sign-flip on `required_temperature_min`

Confirmed on two industrial-refrigeration test tenders: a positive-only source document (e.g.
"+2°C to +6°C") produces an extracted value of `-2`. The digit and surrounding words genuinely
exist in the document, so Layers 0/1/2 all correctly treat the citation as grounded — none of
the three layers check numeric sign, only presence and co-location. Root cause not yet isolated
to a specific pass (4b vs 4c) or mechanism.

### 22.7 Open — `cooling_medium` field: `LLM Hint` wording doesn't match its own `allowed_values`

`LLM Hint` says `"glycol circuit, water, or direct expansion"`; `allowed_values` is
`['glycol', 'water', 'direct']`. `validate_tender_values()`'s allowed-values filter does
case-insensitive substring matching in both directions, but `"glycol circuit"` and `"glycol"` are
substrings of each other in a way that currently passes the filter without normalizing to the
canonical value — the mismatched string then flows into `KO_IF_NEQ`-style exact comparison
against supplier data (which correctly stores `"glycol"`), producing a false K.O. One-cell AP0
fix, not yet applied.

### 22.8 Resolved (OI-115a/OI-115b) — Unit column now read by the extraction prompt

Previously, `build_extraction_template()` / the per-field prompt construction in `app.py` did
not read the AP0 `Unit` column to tell the LLM what unit to output — unit guidance was manually
embedded in free-text `LLM Hint` strings only, and had been observed to drift out of sync with
the structured `Unit` column (concrete case: `lifting_height`'s hint said "in METERS", its
former `user_description` said "(mm; e.g. ...)", `AP0 Unit` = `m`, field_name suffix = `_mm`).

OI-115a (`f76a767`) made `build_extraction_template()` auto-render `(unit: X)` into every
field's prompt line from the AP0 `Unit` column. OI-115b (`26d4195`) closed the storage/tender
split for `lifting_height`/`min_aisle_width`/`tugger_min_aisle_width` specifically —
realigned `Unit` to `mm` (matching storage) and deleted `_to_match_units()` entirely rather
than leave it compensating for a mismatch that no longer exists. `Unit` is now the single
source of truth for both the LLM prompt and buyer-facing labels for these fields; no residual
prompt-side inconsistency. The formerly-tracked field_name suffix cleanup (OI-115c Phases 3C/3D/3F, commits `3b9f65d`/`e3ce309`)
has shipped — field_name no longer carries a unit suffix for any of the 38 affected fields.
Live Airtable rename (Phase 3E) remains a separate, deferred step.

### 22.9 Resolved, for reference

`user_description` LLM-prompt leak (commit `685b492`, 2026-07-30) and the converted-scale anchor
gap (commit `2724749`, 2026-07-31) — both described in §10.2 above. Included here only so a
reader scanning this section for "is X still a risk" gets a direct answer.
