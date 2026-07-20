# haystacked Platform — Unified Field Registry Architecture
## Spec v0.3 — DRAFT FOR SENIOR REVIEW

**Status:** Internal review (Senior Architect). Not yet approved for implementation.
**Authored:** 2026-07-09
**Changes vs v0.2:** All 3 v0.2 Blockers resolved. Top 5 Majors addressed.
  Additional minors fixed (tab_name error policy, `*` sentinel overload, key set spec,
  "identical output" definition, legacy_map miss guard, Step 1/4 DoD contradiction).

---

## 1. Motivation & Problem Statement

### 1.1 The structural rip

The AP0 xlsx today has two separate sections:

```
Entity Model tab  → generate_all.py → sqlite_schema.json → DB columns
DATA_SHEETS tabs  → generate_all.py → fields.json        → matching/scoring
```

A field needing both DB storage AND matching must be maintained in both sections
manually, with no cross-check. Fields disappear silently. Additionally, 10 business
fields are duplicated across tables in the DB (verified in `generate_all.py:498-520`).

### 1.2 Hardcoded scope names

```python
DATA_SHEETS = ["SHARED – All AGV Types", "Forklift AGV", "Tugger AGV", "Mobile AMR"]
```

This constant appears across `generate_all.py` at lines 66, 243, 739, 891, 1283 and
in `app.py`, `matching.py`, `context_builder.py`. Adding a new industry or subcategory
requires Python changes.

### 1.3 Design goals

1. One entry per field. Defined exactly once; all properties on that one entry.
2. No hardcoded sheet/scope/industry names in Python after migration is complete.
3. Industry → Category → Subcategory hierarchy. Adding a new industry = AP0 changes
   only. Zero Python changes (achieved after Step 7).
4. UUID as primary key for fields. `field_name` is human-readable, not unique across
   industries.
5. Complete spec before any implementation.

---

## 2. Glossary

| Term | Definition |
|------|-----------|
| **Field** | One unit of data: name, type, optional matching logic. Identified by UUID. |
| **Scope** | Context a field applies in. Written as `Industry:Category:Subcategory`. Colons are notation only — NOT used in Excel tab names. |
| **Entity** | Which DB table a field belongs to: `Company`, `Product`, or `Base Model`. |
| **Structural field** | PK, FK, and admin columns. Lives in ② Structure tab. Not in Field Registry. |
| **PLAIN field** | Stored in DB, no matching semantics. Neither structural nor business. E.g., `product_description`, `is_oem_product`. Lives in ② Structure with `role=PLAIN`. |
| **Field Registry** | All business fields (levels KO/COND_KO/SCORING/CONTEXT) across all scopes. Lives in scope tabs. |
| **Scope Registry** | Hierarchy definition + classification guides. Tab ③. |
| **Structure Registry** | DB table structure (PK/FK/PLAIN/ADMIN). Tab ②. Replaces Entity Model. |
| **Classification Guide** | Per-scope text teaching the LLM what a tender must look like to belong to that scope. Used exclusively for scope detection (Pass 4a today; generalized in Step 7). No influence on extraction or matching. |
| **Resolution order** | Ordered list of scopes whose fields apply to a given leaf scope. E.g., for `Logistics:AGV:Forklift`: `[*, Logistics:AGV, Logistics:AGV:Forklift]`. |
| **Legacy values** | Old string values (e.g. `"Forklift AGV"`) mapping to a new scope_id. Defined in ③. |

---

## 3. AP0 xlsx — New Tab Structure

### 3.1 Tab inventory

**Fixed metadata tabs** (never scope tabs, never field tabs):

| Tab name | Purpose | Read by generate_all.py? | How |
|----------|---------|--------------------------|-----|
| `① Read me & changes` | Human documentation | No | — |
| `② Structure` | DB table PKs, FKs, PLAIN/ADMIN columns, entity-table mapping | Yes | Dedicated parser |
| `③ Scope Registry` | Scope hierarchy + classification guides | Yes | Dedicated parser → scope_registry.json |
| `Field Fallbacks` | Regex-based field overrides | Yes | Existing parser (unchanged) |
| `Vehicle Types` | Superseded in Step 7. Kept until then. | Yes until Step 7 | Existing parser |
| `Representatives` | Data entry only | No | — |

**Scope tabs** (contain business fields; enumerated in ③ Scope Registry `tab_name` column):

| Tab name | Scope ID | Parent scope |
|----------|----------|--------------|
| `Global` | `*` | — |
| `AGV_Shared` | `Logistics:AGV` | `*` |
| `AGV_Forklift` | `Logistics:AGV:Forklift` | `Logistics:AGV` |
| `AGV_Tugger` | `Logistics:AGV:Tugger` | `Logistics:AGV` |
| `AGV_AMR` | `Logistics:AGV:AMR` | `Logistics:AGV` |

**B1 fix (retained from v0.2):** Tab names are FREE — any valid Excel name. The
authoritative link between tab name and scope_id is the `tab_name` column in ③.
`generate_all.py` reads ③ first, then reads exactly the tabs listed there.
It does NOT derive scope_id from tab names.

**Error policy:** A row in ③ with a blank `tab_name` is a valid intermediate node
(no own fields). A row with a non-blank `tab_name` that is absent from the workbook
is a **hard generation error** — no warning, generation fails with an explicit message
naming the missing tab. Silent orphans are the class of bug this migration eliminates.

### 3.2 Tab `② Structure` — DB Table Definitions

Defines structural and PLAIN columns per DB table. Does NOT contain business fields.

**Role enum:**

| Role | Meaning |
|------|---------|
| `PK` | Primary key |
| `FK` | Foreign key (references another table) |
| `ADMIN` | System column: `active`, `last_updated`, `is_oem_product`, etc. |
| `PLAIN` | Stored in DB, no matching semantics, not a registry field. E.g. `product_description`, `is_oem_product`, `website`, `export_capable`, `min_project_value_eur`, `max_project_value_eur`. |
| `DERIVED` | Computed at query time, not stored. |

**Columns in ② Structure:**

| Column | Description | Example |
|--------|-------------|---------|
| `table` | SQLite table name | `products` |
| `column` | Column name | `company_id` |
| `sqlite_type` | `TEXT`, `INTEGER`, `REAL`, `BOOLEAN` | `TEXT` |
| `role` | PK / FK / ADMIN / PLAIN / DERIVED | `FK` |
| `references` | For FK only: `table.column` | `companies.company_id` |
| `nullable` | `✓` if NULL allowed (blank = NOT NULL) | |
| `notes` | Human note | |

**Entity → physical table mapping** (machine-readable rows in ② Structure,
`role=PK` rows define entities):

| entity_id | physical_table | pk_column | fk_column | fk_references |
|-----------|----------------|-----------|-----------|---------------|
| `Company` | `companies` | `company_id` | — | — |
| `Product` | `products` | `product_id` | `company_id` | `companies.company_id` |
| `Base Model` | `base_model_extensions` | `extension_id` | `base_model_id` | `base_models.base_model_id` |

Note: `base_models` is a structural table (OEM link only, no business fields).
Its FK to `companies` (`oem_company_id → companies.company_id`) is also in ② Structure.
The join from `products` to `base_model_extensions` uses the shared `base_model_id`
column present on both tables — this is also represented in ② as an FK row on
`products`.

**Step 2 reconciliation requirement:** Before building ② Structure, every column in
the current Entity Model tab must be classified as one of:
- Structural → ② with role PK/FK/ADMIN/PLAIN/DERIVED
- Business field → must exist in a scope tab's Field Registry

Columns without a registry entry that carry real stored data use `role=PLAIN`.
The full list of current PLAIN columns: `product_description`, `is_oem_product`,
`website`, `export_capable`, `min_project_value_eur`, `max_project_value_eur`.
Any column not accounted for in either category = **Step 2 failure** (explicit error).

**Column ordering:** ② Structure defines column order per table. `generate_all.py`
emits columns in that order into `sqlite_schema.json`. This is required for the
"sqlite_schema.json identical" DoD to be deterministic.

### 3.3 Tab `③ Scope Registry`

**Columns:**

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `scope_id` | Text | Unique. `Industry:Category:Subcategory` notation. `*` = global. | `Logistics:AGV:Forklift` |
| `parent_scope` | Text | Parent scope_id. Blank for root scopes. | `Logistics:AGV` |
| `display_name` | Text | Human-readable label for UI | `Forklift AGV` |
| `tab_name` | Text | Excel tab name holding this scope's fields. Blank = valid intermediate node with no own fields. | `AGV_Forklift` |
| `legacy_values` | Text | Pipe-separated old values that map to this scope_id. | `Forklift AGV\|VNA Forklift` |
| `active` | Boolean | `✓` if currently in use | `✓` |
| `classification_guide` | Long Text | See §3.4 | _(multi-line)_ |
| `classification_keywords` | Text | Pipe-separated trigger words | `forklift\|reach truck` |

**Step 1 DoD note:** ③ exists from Step 1 with all current scopes. The `*` (Global)
row exists from Step 1 with a **blank `tab_name`** — blank is valid (intermediate node).
Step 4 fills in `tab_name = "Global"` when the Global tab is created. This resolves
the v0.2 minor contradiction between Step 1 and Step 4 DoDs.

### 3.4 Classification Guide

`classification_guide` is the per-scope text teaching the LLM how to identify this
scope from a tender document. It is used **exclusively** for scope detection — the
classification pass (Pass 4a today; generalized classification pass in Step 7).
It has no influence on field extraction, matching rules, or scoring.

**Required content per entry:**
1. What this scope IS (positive definition)
2. What this scope is NOT (exclusion criteria and boundary with adjacent scopes)
3. Typical tender phrases
4. Boundary examples (edge cases with correct classification)

**Classification pass (Step 7 behavior):**
- LLM input: scope hierarchy from scope_registry.json, classification_guide +
  classification_keywords per active leaf scope, extracted tender text
- LLM output: single scope_id (must be a leaf scope), OR the sentinel `"OUT_OF_SCOPE"`
  if no scope matches
- `*` is reserved exclusively as the Global scope_id. It is **never** returned as a
  classification result. Out-of-scope tenders get `"OUT_OF_SCOPE"`, not `*`.
- Non-leaf result (partial classification): apply ancestor fields only, no
  subcategory-specific KO rules. The result UI must surface this state explicitly
  (banner + "not checked" field state). This requirement flows into the Step 7 sub-spec.

**Until Step 7:** Existing Pass 1 (`is_agv_amr`) and Pass 4a (`agv_type`) unchanged.
Classification guides are authored in ③ but not yet consumed by the LLM pipeline.

### 3.5 Field Tab Column Format (all scope tabs identical)

**Columns in every scope tab:**

| Column | Required | Notes |
|--------|----------|-------|
| `uuid` | Yes | Auto-assigned on first entry. Never changes. |
| `field_name` | Yes | Lowercase, underscores. Must equal db_column name (§5, invariant 3). May repeat across industries — UUID disambiguates. |
| `entity` | Yes | `Company`, `Product`, or `Base Model` |
| `data_type` | Yes | Text / Integer / Float / Boolean / Multi-Select / Dropdown / Date / URL |
| `unit` | No | Physical unit |
| `level` | Yes | KO / COND_KO / SCORING / CONTEXT |
| `operator` | Cond. | Required if level ≠ CONTEXT |
| `allowed_values` | Cond. | Pipe-separated. Required for Dropdown/Multi-Select. |
| `scoring_weight` | Cond. | Required if level = SCORING |
| `score_function` | Cond. | LINEAR / THRESHOLD / STEP. Required if SCORING. |
| `threshold_a` | No | Score function parameter A |
| `threshold_b` | No | Score function parameter B |
| `value_if_null` | No | LL-11 default for NULL supplier values |
| `plausibility_min` | No | Minimum plausible value (LLM validation) |
| `plausibility_max` | No | Maximum plausible value |
| `llm_hint` | No | LLM extraction instruction (no numeric literals — see AP0 invariant) |
| `user_description` | No | Clarification Dialog help text (see §4.1 — JSON key is `user_description`) |
| `display_mode` | No | `always` / `on_value` / `never` |

**Derived at generation time — NOT columns in xlsx:**

| Key in fields.json | Derivation rule |
|--------------------|----------------|
| `scope` | From Scope Registry: the scope_id whose `tab_name` matches this field's tab |
| `tender_key` | Auto-derived for all supplier fields: `"required_" + field_name`. Never manually entered. (No tender-only fields exist in the current schema; if added in future, `entity=Tender` must be defined in ② and the tender_key rule stated explicitly at that time.) |

**`generate_all.py` asserts at generation time:**
- Every field with `level ≠ CONTEXT` has a non-blank `operator`
- Every field with `data_type ∈ {Dropdown, Multi-Select}` has non-blank `allowed_values`
- Every field with `level = SCORING` has non-blank `scoring_weight`
- No duplicate `field_name` along any resolution chain (§5.1)
- No two fields in the same scope share a `tender_key`
- `extensions_columns ∩ products_columns ∩ companies_columns` = join keys only (no cross-table duplication)

---

## 4. Generated Artifacts

### 4.1 `config/fields.json` — Unified Field Registry

**Key:** UUID. **Normative key set:** current fields.json keys, minus `sheet`, plus `scope`.
All other keys (`uuid`, `field_name`, `tender_key`, `entity`, `level`, `operator`,
`data_type`, `unit`, `allowed_values`, `scoring_weight`, `score_function`, `threshold_a`,
`threshold_b`, `value_if_null`, `plausibility_min`, `plausibility_max`, `hint`,
`user_description`, `display_mode`) are unchanged. The sample below is illustrative;
the normative reference is the current fields.json key set.

```json
{
  "18b0abbe-33f3-4dbc-b03e-cb9fdb216fb8": {
    "uuid":             "18b0abbe-33f3-4dbc-b03e-cb9fdb216fb8",
    "field_name":       "navigation_type",
    "tender_key":       "required_navigation_type",
    "entity":           "Base Model",
    "scope":            "Logistics:AGV",
    "level":            "CONTEXT",
    "operator":         null,
    "data_type":        "Multi-Select",
    "unit":             null,
    "allowed_values":   ["Laser Reflector", "Natural Feature (SLAM)", "QR/DM Code"],
    "scoring_weight":   null,
    "score_function":   null,
    "threshold_a":      null,
    "threshold_b":      null,
    "value_if_null":    null,
    "plausibility_min": null,
    "plausibility_max": null,
    "hint":             "...",
    "user_description": "...",
    "display_mode":     "on_value"
  }
}
```

### 4.2 `config/scope_registry.json` — NEW (generated from ③)

```json
{
  "scopes": {
    "*": {
      "scope_id": "*",
      "parent": null,
      "display_name": "Global",
      "tab_name": "Global",
      "legacy_values": [],
      "classification_guide": "",
      "classification_keywords": [],
      "active": true
    },
    "Logistics:AGV:Forklift": {
      "scope_id": "Logistics:AGV:Forklift",
      "parent": "Logistics:AGV",
      "display_name": "Forklift AGV",
      "tab_name": "AGV_Forklift",
      "legacy_values": ["Forklift AGV", "VNA Forklift"],
      "classification_guide": "WHAT IT IS: ...",
      "classification_keywords": ["forklift", "reach truck", "stacker"],
      "active": true
    }
  },
  "resolution_order": {
    "Logistics:AGV:Forklift": ["*", "Logistics:AGV", "Logistics:AGV:Forklift"],
    "Logistics:AGV:Tugger":   ["*", "Logistics:AGV", "Logistics:AGV:Tugger"],
    "Logistics:AGV:AMR":      ["*", "Logistics:AGV", "Logistics:AGV:AMR"]
  },
  "legacy_map": {
    "Forklift AGV":  "Logistics:AGV:Forklift",
    "VNA Forklift":  "Logistics:AGV:Forklift",
    "Tugger AGV":    "Logistics:AGV:Tugger",
    "Mobile AMR":    "Logistics:AGV:AMR"
  }
}
```

`legacy_map` is a flat reverse index of all `legacy_values`. Used by `matching.py`
to resolve `prod.agv_type` → `scope_id`. (B6 fix from v0.2.)

**Miss guard (M-new-11):** If `prod.agv_type` is not in `legacy_map`, the supplier
is skipped with an explicit logged error. It never silently passes. Additionally,
`sync_airtable.py` runs a post-load check: all distinct DB `agv_type` values must
resolve via `legacy_map`. Unknown values abort sync with an explicit error.

### 4.3 `config/sqlite_schema.json`

Generated as today. Source changes:
- Structural and PLAIN sections → from `② Structure` tab (PK/FK/ADMIN/PLAIN/DERIVED roles)
- Business column sections → from `fields.json` grouped by entity

Consumer interface unchanged: `companies_columns`, `products_columns`,
`extensions_columns` lists remain. `sync_airtable.py` unchanged through Step 5.

### 4.4 `config/vehicle_types.json`

Kept until Step 7. After Step 7, superseded by `scope_registry.json`.

### 4.5 Literal inventory — all strings to de-hardcode

| Location | Literal | Resolved in Step |
|----------|---------|-----------------|
| `generate_all.py:66` | `DATA_SHEETS = [...]` | Step 1 |
| `generate_all.py:243` | `sheet_map` dict (scoring weights per sheet) | Step 1 |
| `generate_all.py:739` | `build_extraction_template` sheet loop | Step 1 |
| `generate_all.py:891` | `basic_template` AGV literals | Step 7 |
| `generate_all.py:1283` | sheet name reference | Step 1 |
| `matching.py` | `_SHARED_SHEET` constant | Step 3 |
| `matching.py:441` | `prod.agv_type` string filter | Step 3 (via legacy_map) |
| `app.py:169` | `_NUMERIC_KO_FIELD_HINTS` uses `spec.sheet` | Step 3 |
| `app.py` | `_VALID_VTS`, vehicle type constants | Step 3 |
| `app.py:657-671` | Pass 4a allowed-values validation uses sheet | Step 3 |
| `app.py:1054` | `/rematch` writes `required_agv_type` by name | Step 3 |
| `app.py:1131-1142` | `/api/field-meta` exports `sheet` key + `shared_sheet_name` | Step 3 |
| `app.py` | `is_agv_amr` pass | Step 7 |
| `context_builder.py` | Any `fields_by_sheet()` calls (verify by grep at implementation) | Step 3 |
| Test files | `_SHARED_SHEET` imports | Step 3 |
| Frontend JS | `.sheet` and `shared_sheet_name` usages | Step 3 |

---

## 5. Invariants

1. **UUID is the primary key** for every field. Never changes after first assignment.
2. **`field_name` may repeat across industries.** UUID disambiguates. Within a single
   resolution chain, no `field_name` may appear more than once (§5.1).
3. **`field_name == db_column` always.** No mapping, no alias. A rename requires a
   DB migration.
4. **No industry/scope/sheet names hardcoded in Python** after Step 7.
5. **`generate_all.py` is the sole writer** of all files under `config/`.
   Exception: `config/unit_semantics.json` is manually maintained (loaded by
   `matching.py:39` and `app.py:82`).
6. **Test suite green after every step.**
7. **Steps 1–5 are behavior-neutral:** golden run match results identical before
   and after (see §5.3 for definition of "identical").
8. **Step 6 (Content Changes) has its own Golden Refresh.**

### 5.1 field_name uniqueness along a resolution chain

`generate_all.py` asserts:
- No two fields in the same resolution chain share a `field_name`.
- Sibling scopes (e.g. `Logistics:AGV:Forklift` and `Logistics:AGV:Tugger`) may
  share a `field_name` only if `entity`, `data_type`, and `unit` are all identical.
- Violation → generation fails with explicit error naming the conflicting fields.

### 5.2 NULL semantics in base_model_extensions

`base_model_extensions` is a single wide table covering all industries. NULL =
"unknown or not applicable." Consistent with Blank ≠ Zero (LL-06): NULL means the
value was not provided. Scope-irrelevant columns (e.g., a Printing-scope column for
an AGV product) will always be NULL and are never evaluated by the matching engine
(scope-filtered field loading prevents it). This is explicitly accepted.

### 5.3 Definition of "identical output" (Steps 1–5 DoD)

"Identical" = per-supplier match results: `{disqualified, disqualified_by, score,
score_details}` for all 5 golden tenders. Excludes: field-meta API response envelope
(which changes in Step 3 when `sheet` → `scope`), and generation timing/ordering.
The golden test fixtures carry no `sheet` key and therefore compare cleanly.

---

## 6. Runtime Architecture

### 6.1 Startup

```
load scope_registry.json   → _SCOPE_REGISTRY, _VALID_SCOPES, _LEGACY_MAP
load fields.json           → _FIELDS (all scopes, indexed by UUID)
build per-scope field sets → for each leaf scope: apply resolution_order
load sqlite_schema.json    → existing schema constants (unchanged)
load unit_semantics.json   → _SIGNED_UNITS (unchanged)
```

### 6.2 Scope Detection (until Step 7 — unchanged behavior)

Pass 1 (`is_agv_amr`) and Pass 4a (`agv_type`) unchanged. Scope_id resolved at
runtime: `_LEGACY_MAP[prod.agv_type]` → scope_id. Unknown value → logged error,
supplier skipped.

### 6.3 Scope Detection (Step 7 — new behavior)

Unified classification pass using scope_registry.json classification guides.
Replaces Pass 1 + Pass 4a. Returns a leaf scope_id or `"OUT_OF_SCOPE"` — never `*`.
Requires its own sub-spec before implementation (OI-G).

### 6.4 Field Loading by Scope

```python
resolution = _SCOPE_REGISTRY["resolution_order"]["Logistics:AGV:Forklift"]
# → ["*", "Logistics:AGV", "Logistics:AGV:Forklift"]
active_fields = {
    uuid: spec
    for uuid, spec in _FIELDS.items()
    if spec["scope"] in resolution
}
```

Replaces `fields_by_sheet()` + `_SHARED_SHEET` pattern throughout the codebase.

### 6.5 Matching and Extraction

Matching engine: field collection becomes scope-based (§6.4). All operator logic,
null rules, and scoring unchanged. `agv_type` continues to participate in matching
via KO_IF_NEQ as a normal registry field — its matching semantics are NOT retired
until Step 7.

Extraction: `extraction_template.txt` generation uses scope-filtered fields.
Context builder uses `fields_by_scope(scope_id)`. Prompt structure, LLM call
structure, and output parsing unchanged.

---

## 7. Data Layer

### 7.1 SQLite tables (unchanged structure through Step 5)

```
companies              PK: company_id
  [structural: PKs, FKs, ADMIN/PLAIN from ② Structure]
  [business: entity=Company fields from Global tab]

products               PK: product_id  FK→companies via company_id
  [structural: ② Structure]
  [business: entity=Product fields from Global tab]
  agv_type             ← entity=Product registry field (level=KO, KO_IF_NEQ).
                          Generated into products table via entity routing.
                          Not a duplicate. Matching semantics retired in Step 7.

base_models            PK: base_model_id  FK→companies via oem_company_id
  [structural only: oem_link_public, last_updated — no business fields]

base_model_extensions  PK: extension_id  FK→base_models via base_model_id
  [ALL entity=Base Model business fields from ALL scope tabs]
```

### 7.2 The 10 real denormalization duplicates (Step 5 targets)

Verified in `generate_all.py:498-520`:

**`_company_in_ext`** (3 Company fields duplicated into `base_model_extensions`):
- `employee_count_range`
- `hq_city`
- `founding_year`

**`shared_in_product_columns`** (7 fields duplicated into `products`):
- `certifications_generic`
- `country`
- `distribution_model`
- `languages_spoken`
- `lead_time_weeks`
- `reference_count`
- `service_coverage`

Canonical home rule: field's `entity` column determines the single target table.
Copies in other tables are removed. `data_loader.py` already SELECTs the canonical
side (e.g., `c.employee_count_range`); verify the `_supplier_val` fallback chain
covers the product-side fields before removing the product-side copies.

Step 5 expected delta: `extensions_columns` shrinks by 3, `products_columns` shrinks
by 7. Document exact pre/post counts in Step 5 DoD.

### 7.3 Airtable Sync

`sync_airtable.py` reads column lists from `sqlite_schema.json`. Unchanged through
Step 5, as long as `sqlite_schema.json` emits the same column lists.

**Exception — Step 5:** Removing 10 duplicate columns reduces both `products_columns`
and `extensions_columns`. Mandatory post-Step-5 operations (see §8.5).

---

## 8. Migration Steps

**Global invariant:** Test suite green after every step. Steps 1–5: match results
identical (§5.3). Step 6: intentional behavior change with own golden refresh.

---

### Step 1 — De-hardcode DATA_SHEETS

**What:** `generate_all.py` reads field-tab list from ③ Scope Registry (`tab_name`
column) instead of the hardcoded `DATA_SHEETS` list. All sheet-name string literals
in `generate_all.py` at lines 66, 243, 739, 1283 replaced with dynamic lookups.

**AP0 change required:**
- Add `③ Scope Registry` tab with all 4 current scopes + Global row.
- `tab_name` values use current tab names verbatim (e.g., `"SHARED – All AGV Types"`).
  No renames needed yet.
- Global row has scope_id=`*`, parent_scope blank, tab_name blank (valid intermediate
  node — Step 4 will fill this in).

**Error policy:** Non-blank `tab_name` absent from workbook → hard generation error.

**DoD:**
- `DATA_SHEETS` constant removed from `generate_all.py`
- ③ Scope Registry tab exists with 5 rows (4 current scopes + Global)
- `generate_all.py` output byte-identical vs. before
- New ③ row with non-existent tab_name → generation fails with named error
- All tests green

---

### Step 2 — Structure Registry (replaces Entity Model)

**What:** Add `② Structure` tab with PK/FK/ADMIN/PLAIN/DERIVED columns + entity→table
mapping. `generate_all.py` reads structural and PLAIN sections from `② Structure`
instead of Entity Model. Entity Model tab becomes documentation-only.

**Reconciliation requirement (mandatory before implementing ②):** Every column in the
current Entity Model tab must be classified:
- Structural → ② with appropriate role
- Business field → confirm it exists in a scope tab's Field Registry
- No column left unaccounted. Any unclassified column = blocking error.

**PLAIN columns** (current list): `product_description`, `is_oem_product`, `website`,
`export_capable`, `min_project_value_eur`, `max_project_value_eur`.

**FK inventory for Base Model entity:**
- `base_model_extensions.base_model_id → base_models.base_model_id` (FK)
- `products.base_model_id → base_models.base_model_id` (FK — join anchor)
- `base_models.oem_company_id → companies.company_id` (FK)

**Column ordering:** ② defines column order per table. Generation emits in ② order.
Required for deterministic DoD comparison.

**DoD:**
- ② Structure tab fully populated and reconciliation table reviewed
- `generate_all.py` no longer reads Entity Model tab
- `sqlite_schema.json` identical before and after (including column order)
- Entity Model tab annotated: "DOCUMENTATION ONLY — not read by any script"
- All tests green

---

### Step 3 — `scope` in fields.json (replace `sheet`)

**What:** `generate_all.py` derives `scope` for each field from ③ Scope Registry
and writes it to `fields.json`. The `sheet` key is removed.

`scope_registry.json` is generated and loaded at startup (`_SCOPE_REGISTRY`,
`_LEGACY_MAP`). `vehicle_types.json` still generated (unchanged — full supersession
in Step 7).

**All consumers updated** (see §4.5 literal inventory for locations):
- `matching.py`: `_SHARED_SHEET` constant removed; field collection uses §6.4 pattern
- `matching.py`: `prod.agv_type` → `_LEGACY_MAP[prod.agv_type]` with miss guard
- `app.py:169`: `_NUMERIC_KO_FIELD_HINTS` switches from `spec.sheet` to `spec.scope`
- `app.py:657-671`: Pass 4a validation uses scope-filtered `agv_type` field
- `app.py:1054`: `/rematch` writes `required_agv_type` (field_name unchanged, no impact)
- `app.py:1131-1142`: `/api/field-meta` response: `sheet` key → `scope` key;
  `shared_sheet_name` export removed
- `context_builder.py`: verify by grep; replace any `fields_by_sheet()` calls
- Test files: `_SHARED_SHEET` imports removed
- Frontend JS: `.sheet` → `.scope`; `shared_sheet_name` usage removed

**DoD:**
- `sheet` key absent from `fields.json`
- `_SHARED_SHEET` constant absent from all Python files
- `scope_registry.json` generated and loaded at startup
- `/api/field-meta` response has `scope` key, no `sheet` key, no `shared_sheet_name`
- Frontend JS uses `.scope`
- `legacy_map` miss guard active (logged error + supplier skipped)
- All tests green
- 5 golden tenders: match results identical (per §5.3)

---

### Step 4 — Tab Restructuring (Global tab + field movement)

**What:** Create `Global` tab in AP0 xlsx. Move all `entity=Company` and
`entity=Product` fields from `SHARED – All AGV Types` (renaming it `AGV_Shared`
simultaneously or separately) to `Global`. Update ③ Scope Registry:
- `*` row: fill `tab_name = "Global"`
- `Logistics:AGV` row: update `tab_name` to match the renamed SHARED tab

**This step is purely AP0 content rearrangement.** No Python changes needed
(generate_all.py already reads tabs dynamically after Step 1).

**Move list** (derived mechanically from fields.json: all entries with `entity ∈
{Company, Product}`):

Company fields → `Global` tab:
- `country`, `employee_count_range`, `founding_year`, `hq_city`,
  `certifications_generic`, `languages_spoken`

Product fields → `Global` tab:
- `reference_count`, `lead_time_weeks`, `distribution_model`, `service_coverage`,
  `agv_type`

Note: `product_name`, `product_description`, `active`, `website`, `export_capable`
are NOT registry fields — they are structural/PLAIN columns (→ ② Structure, not scope
tabs). Do not create registry entries for them.

**DoD:**
- `Global` tab exists with all entity=Company + entity=Product fields
- `AGV_Shared` tab (formerly SHARED) contains only entity=Base Model fields
- ③ Scope Registry `*` row has `tab_name = "Global"`
- `generate_all.py` output: moved fields have `scope = "*"` (Company/Product fields)
  or `scope = "Logistics:AGV"` (Base Model fields) as appropriate
- All tests green
- 5 golden tenders: match results identical

---

### Step 5 — Remove Denormalization

**What:** Remove the 10 duplicate columns (§7.2) from the extra tables.
Remove `_company_in_ext` and `shared_in_product_columns` logic from `generate_all.py`.

**Pre-implementation check:** Verify `data_loader.py` `_supplier_val` fallback chain.
The loader SELECTs canonical columns; after removing product-side and extensions-side
copies, confirm no `_supplier_val` call silently falls through to a now-absent column.

**Generation-time assert added:** `extensions_columns ∩ products_columns ∩
companies_columns` = join keys only. Violation → generation fails.

**Post-Step-5 mandatory operations (not optional):**
1. Re-export all tables from Airtable as CSV
2. DB rebuild: `python3 sync_airtable.py --local`

**DoD:**
- No field_name appears in more than one scope tab
- `_company_in_ext` and `shared_in_product_columns` absent from `generate_all.py`
- `extensions_columns` delta: −3 (employee_count_range, hq_city, founding_year)
- `products_columns` delta: −7 (certifications_generic, country, distribution_model,
  languages_spoken, lead_time_weeks, reference_count, service_coverage)
- CSV re-export + DB rebuild completed
- Cross-table disjointness assert active at generation time
- All tests green
- 5 golden tenders: match results identical

---

### Step 6 — Content Changes (AP0 field level/operator changes)

**ONLY step that intentionally changes matching behavior.** Own golden refresh.
Completely separate from Steps 1–5.

**Content changes:**

| Field | Change | Data migration? |
|-------|--------|----------------|
| `navigation_type` | COND_KO → CONTEXT | No |
| `battery_type` | SCORING → CONTEXT | No |
| `fleet_management_system` | COND_KO → CONTEXT | No |
| `max_fleet_size` | SCORING → CONTEXT | No |
| `ingress_protection_rating` | COND_KO → CONTEXT | No |
| `floor_flatness_req` | COND_KO → CONTEXT | No |
| `infrastructure_required` | Rename → `infrastructure_free`; Boolean inverted; operator stays KO_BOOL_REQUIRED | **YES — 3-front migration** |
| `load_type` | `allowed_values` updated | **YES — value mapping** |
| `integration_capability` | SCORING → COND_KO; operator KO_SUBSET; new `allowed_values` | **YES — value mapping** |

**For `infrastructure_free` (3-front migration order — mandatory sequence):**
1. Apply rename and Boolean inversion **in Airtable** (rename field, invert all values)
2. Full CSV re-export from Airtable
3. `python3 sync_airtable.py --local` — DB rebuild
4. Apply rename + operator change in AP0 xlsx
5. `python3 scripts/generate_all.py`

DoD checks: old column name `infrastructure_required` absent from rebuilt DB;
spot-check ≥5 suppliers that `infrastructure_free` values are correctly inverted;
NULL count for `infrastructure_free` ≤ pre-migration NULL count for
`infrastructure_required`.

**For `load_type` and `integration_capability`:**
Same 3-front sequence: Airtable value update → CSV re-export → DB rebuild → AP0
change → generate_all. Migration scripts must be idempotent (safe to re-run).
Verify on dev DB before production.

**DoD:**
- All content changes applied in AP0 xlsx
- `generate_all.py` run; `config/` regenerated
- All 3 data migrations completed (Airtable → CSV → DB → AP0 → config)
- Golden run on all 5 tenders with updated expectations documented
- All tests updated for new behavior
- New golden baseline committed

---

### Step 7 — Generalize Scope Detection

Replaces hardcoded `is_agv_amr` + Pass 4a with unified classification pass using
`scope_registry.json` classification guides. First run that uses the `classification_guide`
content from ③.

**Pre-conditions:** Steps 1–6 complete and stable.
**This step requires its own sub-spec before implementation begins** (OI-G).
Sub-spec must include: classification pass prompt design, hierarchy traversal logic,
`"OUT_OF_SCOPE"` handling, partial-classification UI surfacing, `vehicle_types.json`
retirement plan.

---

## 9. Open Items (out of scope for this migration)

| ID | Description |
|----|-------------|
| OI-A | CONTEXT fields display section in result card UI |
| OI-B | Ordinal operator (`KO_IF_ORD`) for ordered categorical fields |
| OI-C | `Other` in load_type → triggers Request flow |
| OI-D | Country restructuring: HQ_Country + HQ_City + Offices + service_reach |
| OI-E | `max/min_project_value_eur` — confirm as PLAIN (no matching) or promote to CONTEXT field |
| OI-F | `integration_capability` LLM extraction hint (mapping "SAP WM" → WMS) |
| OI-G | Step 7 sub-spec: classification pass design, partial-classification UI, vehicle_types.json retirement |
| OI-H | Admin UI consideration: build own interface when second industry is added |

---

## 10. Acceptance Criteria (Steps 1–6 complete)

- [ ] `DATA_SHEETS` constant absent from all Python files
- [ ] `_SHARED_SHEET` constant absent from all Python files
- [ ] Entity Model tab marked documentation-only
- [ ] `fields.json`: every entry has `scope`, no `sheet` key
- [ ] `scope_registry.json` generated, loaded at startup
- [ ] Non-blank `tab_name` absent from workbook → hard generation error
- [ ] `extensions_columns ∩ products_columns ∩ companies_columns` = join keys (generation assert)
- [ ] No field appears in more than one AP0 scope tab
- [ ] `legacy_map` miss guard active; `sync_airtable.py` validates all `agv_type` values
- [ ] Adding a new scope (new ③ row + new tab): zero Python changes needed
- [ ] `/api/field-meta` response has `scope` key, no `sheet` key
- [ ] `infrastructure_free` inversion complete (3-front migration verified)
- [ ] `load_type` + `integration_capability` value migrations complete
- [ ] Test suite ≥ 204 passing
- [ ] Steps 1–5: 5 golden tenders match results identical to pre-migration baseline
- [ ] Step 6: new golden baseline committed with documented expected changes
- [ ] `sync_airtable.py --local` completes without error after each step

---

*End of Spec v0.3*
