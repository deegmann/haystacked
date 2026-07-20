# haystacked Platform — Unified Field Registry Architecture
## Spec v0.1 — DRAFT FOR APPROVAL

**Status:** Awaiting PO sign-off before any implementation begins.
**Authored:** 2026-07-08
**Scope:** Complete architectural redesign of AP0 + code generation pipeline + runtime.

---

## 1. Motivation & Problem Statement

### 1.1 The current structural rip

The AP0 xlsx today has two separate sections with two separate purposes:

```
Entity Model tab  → generate_all.py → sqlite_schema.json → DB columns (structure)
DATA_SHEETS tabs  → generate_all.py → fields.json        → matching/scoring logic
```

A field that needs to be both stored in the DB AND used for matching must be manually
maintained in BOTH sections. There is no automated cross-check. Mis-entries disappear
silently — a field defined only in Entity Model lands in the DB but is never matched;
a field defined only in DATA_SHEETS has matching logic but no DB column to read from.

### 1.2 Hardcoded sheet names

`generate_all.py` contains:

```python
DATA_SHEETS = ["SHARED – All AGV Types", "Forklift AGV", "Tugger AGV", "Mobile AMR"]
```

This constant appears in 10 places. Adding a new industry or subcategory requires a
Python code change. This is a fundamental extensibility blocker.

### 1.3 Duplicate entries

Several fields appear in both Entity Model (for DB) and DATA_SHEETS (for matching):
`agv_type`, `reference_count`, `lead_time_weeks`, `country`, and others. One source of
truth means one entry per field, full stop.

---

## 2. Vision & Design Goals

1. **One entry per field.** A field is defined exactly once. Whether it is stored in the
   DB, used for matching, displayed in the UI, or extracted by the LLM — all of this
   is a property of that one entry.

2. **No hardcoded sheet names or industry names in Python.** Adding a new industry,
   category, or subcategory = adding rows/tabs to the AP0 xlsx. Zero Python changes.

3. **Industry → Category → Subcategory hierarchy.** Today: Logistics → AGV → Forklift AGV.
   Tomorrow: Printing → Offset → Sheet-fed. The architecture supports both without change.

4. **UUID as primary key for fields.** `field_name` is human-readable but not unique
   across industries (a "temperature" field can exist in Logistics AND in Cold-Chain AND
   in Food Processing). UUID disambiguates.

5. **Complete spec before any implementation.** This document is the contract.

---

## 3. Glossary

| Term | Definition |
|------|-----------|
| **Field** | One unit of data with a name, type, and optional matching logic. Identified by UUID. |
| **Scope** | The context in which a field applies. Written as `Industry:Category:Subcategory`. `*` = global. |
| **Entity** | Which database table a field belongs to: `Company`, `Product`, or `Base Model`. |
| **Primary Key (PK)** | The unique ID column of a database table (e.g. `company_id`). Not a business field — structural only. |
| **Foreign Key (FK)** | A column that references another table's PK (e.g. `product.company_id` points to `companies.company_id`). Structural only. |
| **Structural field** | PK/FK and administrative columns (`last_updated`, `active`). Not in the Field Registry — in the Structure Registry. |
| **Field Registry** | The collection of all business fields across all scopes. Lives in the scope tabs of the AP0 xlsx. |
| **Scope Registry** | The definition of the scope hierarchy plus classification hints for the LLM. One tab in the AP0 xlsx. |
| **Structure Registry** | The definition of DB table structure (PK/FK, admin columns). One tab in the AP0 xlsx. Replaces Entity Model tab. |
| **generate_all.py** | The code generator that reads AP0 xlsx → produces all config files. |
| **fields.json** | The unified runtime field registry. Consumed by matching engine, LLM pipeline, UI. |

---

## 4. AP0 xlsx — New Tab Structure

### 4.1 Tab inventory

| Tab name | Purpose | Read by generate_all.py? |
|----------|---------|--------------------------|
| `① Read me & changes` | Human documentation, changelog | No |
| `② Structure` | DB table structure: PK, FK, admin columns | Yes — generates sqlite_schema.json structural sections |
| `③ Scope Registry` | Scope hierarchy + LLM classification hints | Yes — generates scope_registry.json |
| `Global` | Fields applying to all industries (company info, product info) | Yes — scope = `*` |
| `Logistics:AGV` | Fields applying to all AGV/AMR types | Yes — scope = `Logistics:AGV` |
| `Logistics:AGV:Forklift` | Fields specific to Forklift AGVs | Yes — scope = `Logistics:AGV:Forklift` |
| `Logistics:AGV:Tugger` | Fields specific to Tugger AGVs | Yes — scope = `Logistics:AGV:Tugger` |
| `Logistics:AGV:AMR` | Fields specific to Mobile AMRs | Yes — scope = `Logistics:AGV:AMR` |
| _(future)_ `Printing:Offset` | Fields for offset printing machines | Yes — scope = `Printing:Offset` |

**Rule:** generate_all.py reads ONLY tabs that are listed in the `③ Scope Registry`
(column `tab_name`). Metadata tabs (①②③) are never field tabs. No hardcoded tab list
in Python.

### 4.2 Tab `② Structure` — DB Table Definitions

Defines primary keys, foreign keys, and admin columns for each DB table. Does NOT
contain business fields (those are in the scope tabs).

**Columns:**

| Column | Description | Example |
|--------|-------------|---------|
| `table` | SQLite table name | `products` |
| `column` | Column name | `company_id` |
| `sqlite_type` | SQLite data type | `TEXT`, `INTEGER`, `REAL` |
| `role` | `PK`, `FK`, or `ADMIN` | `FK` |
| `references` | For FK: `table.column` it points to | `companies.company_id` |
| `mandatory` | `✓` if NOT NULL | `✓` |
| `notes` | Human note | `System-generated UUID` |

**Resulting DB tables (structural columns only):**

```
companies:   company_id (PK), last_updated, [+business fields from Global tab]
products:    product_id (PK), company_id (FK→companies), base_model_id (FK→base_models),
             active, is_oem_product (derived), last_updated, [+business fields from Global tab]
base_models: base_model_id (PK), oem_company_id (FK→companies),
             oem_link_public, last_updated
             [all other base model fields → base_model_extensions]
base_model_extensions: extension_id (PK), base_model_id (FK→base_models),
             [+all business fields entity=Base Model from all scope tabs]
```

### 4.3 Tab `③ Scope Registry` — Hierarchy + Classification

**Columns:**

| Column | Description | Example |
|--------|-------------|---------|
| `scope_id` | Unique scope identifier. Written as `Industry:Category:Subcategory`. `*` for global. | `Logistics:AGV:Forklift` |
| `parent_scope` | The scope this one inherits from. Blank for top-level. | `Logistics:AGV` |
| `display_name` | Human-readable label | `Forklift AGV` |
| `tab_name` | Name of the AP0 tab that contains this scope's fields | `Logistics:AGV:Forklift` |
| `classification_hint` | Text snippet for the LLM classification pass: what does this scope look like? | `Vehicle with mast and forks, lifts pallets into racking...` |
| `classification_keywords` | Pipe-separated keywords to assist LLM detection | `forklift\|reach truck\|stacker\|VNA` |
| `active` | `✓` if currently in use | `✓` |

**Current scope rows (Logistics domain):**

| scope_id | parent | display_name | tab_name |
|----------|--------|--------------|----------|
| `*` | — | Global | `Global` |
| `Logistics` | `*` | Logistics | _(no tab — parent only)_ |
| `Logistics:AGV` | `Logistics` | AGV / AMR | `Logistics:AGV` |
| `Logistics:AGV:Forklift` | `Logistics:AGV` | Forklift AGV | `Logistics:AGV:Forklift` |
| `Logistics:AGV:Tugger` | `Logistics:AGV` | Tugger AGV | `Logistics:AGV:Tugger` |
| `Logistics:AGV:AMR` | `Logistics:AGV` | Mobile AMR | `Logistics:AGV:AMR` |

Note: A scope can exist in the registry as a parent node without its own tab (e.g.
`Logistics` — it groups AGV/Printing/etc. but has no fields of its own).

### 4.4 Field Tab Column Format (all scope tabs share this format)

Each scope tab (`Global`, `Logistics:AGV`, etc.) has identical column headers.
The `scope` of a field is derived from the tab name — it is NOT a column the
AP0 maintainer fills in manually.

**Required columns:**

| Column | Description | Example |
|--------|-------------|---------|
| `uuid` | Auto-generated UUID. Never change after first assignment. | `18b0abbe-33f3-...` |
| `field_name` | Technical name. Lowercase, underscores. Unique within a scope but may repeat across scopes (hence UUID). | `max_payload_kg` |
| `entity` | DB ownership: `Company`, `Product`, or `Base Model` | `Base Model` |
| `data_type` | `Text`, `Integer`, `Float`, `Boolean`, `Multi-Select`, `Dropdown`, `Date`, `URL` | `Float` |
| `unit` | Physical unit if applicable | `kg` |
| `level` | Matching level: `KO`, `COND_KO`, `SCORING`, `CONTEXT` | `KO` |
| `operator` | Matching operator (blank if `CONTEXT`): `KO_IF_LT`, `KO_IF_GT`, `KO_IF_NEQ`, `KO_BOOL_REQUIRED`, `KO_BOOL_EXCLUSIVE`, `KO_SUBSET` | `KO_IF_LT` |
| `allowed_values` | Pipe-separated list for Dropdown/Multi-Select | `None\|Pallet EUR\|Tote` |
| `scoring_weight` | Weight in scoring (blank if not `SCORING`) | `0.15` |
| `score_function` | `LINEAR`, `THRESHOLD`, `STEP` (blank if not SCORING) | `LINEAR` |
| `threshold_a` | Score function parameter A | `100` |
| `threshold_b` | Score function parameter B | `500` |
| `value_if_null` | Default value applied when supplier field is NULL (LL-11) | `False` |
| `plausibility_min` | Minimum plausible value for numeric fields (LLM validation) | `0` |
| `plausibility_max` | Maximum plausible value | `50000` |
| `llm_hint` | Extraction instruction for LLM | `Maximum payload in kg...` |
| `ui_hint` | Clarification Dialog help text shown to user | `Maximum load the AGV can carry` |
| `display_mode` | UI display: `always`, `on_value`, `never` | `on_value` |

**Derived at generation time (NOT columns in xlsx):**

| Generated key | Derivation rule |
|---------------|----------------|
| `tender_key` | `required_` + `field_name` (for supplier fields) or same as `field_name` for tender-only fields |
| `scope` | Derived from the tab name by generate_all.py |

---

## 5. Generated Artifacts

### 5.1 `config/fields.json` — Unified Field Registry

**Key:** UUID (unchanged from current).

**New fields vs. current:**
- `scope` added (derived from tab, was `sheet` before)
- `sheet` removed (replaced by `scope`)
- All other keys unchanged

```json
{
  "18b0abbe-33f3-4dbc-b03e-cb9fdb216fb8": {
    "uuid":           "18b0abbe-33f3-4dbc-b03e-cb9fdb216fb8",
    "field_name":     "navigation_type",
    "tender_key":     "required_navigation_type",
    "entity":         "Base Model",
    "scope":          "Logistics:AGV",
    "level":          "CONTEXT",
    "operator":       null,
    "data_type":      "Multi-Select",
    "unit":           null,
    "allowed_values": ["Laser Reflector", "Natural Feature (SLAM)", "QR/DM Code", ...],
    "scoring_weight": null,
    "hint":           "...",
    "ui_hint":        "...",
    "display_mode":   "on_value",
    "value_if_null":  null
  }
}
```

### 5.2 `config/scope_registry.json` — NEW

Generated from `③ Scope Registry` tab. Used at startup to:
- Build scope inheritance chain for field loading
- Provide classification hints to LLM classification pass
- Drive `_VALID_SCOPES` constant (replaces `_VALID_VTS`)

```json
{
  "scopes": {
    "*": {
      "scope_id": "*",
      "parent": null,
      "display_name": "Global",
      "tab_name": "Global",
      "classification_hint": "",
      "classification_keywords": []
    },
    "Logistics:AGV:Forklift": {
      "scope_id": "Logistics:AGV:Forklift",
      "parent": "Logistics:AGV",
      "display_name": "Forklift AGV",
      "tab_name": "Logistics:AGV:Forklift",
      "classification_hint": "Vehicle with mast and forks...",
      "classification_keywords": ["forklift", "reach truck", "stacker", "VNA"]
    }
  },
  "resolution_order": {
    "Logistics:AGV:Forklift": ["*", "Logistics:AGV", "Logistics:AGV:Forklift"]
  }
}
```

`resolution_order` pre-computes the scope inheritance chain for each leaf scope.
When loading fields for `Logistics:AGV:Forklift`, generate_all.py includes fields
from `*`, `Logistics:AGV`, and `Logistics:AGV:Forklift`.

### 5.3 `config/sqlite_schema.json` — Derived from Field Registry

Generated as today, but now derived entirely from:
1. `② Structure` tab → PK/FK/admin columns per table
2. `fields.json` → business columns per entity

No longer reads from Entity Model tab (which will be removed or kept as documentation only).

### 5.4 `config/vehicle_types.json` — Replaced by `config/scope_registry.json`

`vehicle_types.json` currently holds:
- `vt_map`: LLM output → canonical vehicle type
- `text_overrides`: regex → canonical type
- `vna_context_hint`, `vna_keywords`, `vna_drive_types`

These migrate into `scope_registry.json` as scope-level metadata. The `_SHARED_SHEET`
constant and `_VALID_VTS` are replaced by `scope_registry.json` lookups.

**Note:** VNA is a sub-modifier of `Logistics:AGV:Forklift`, not a separate scope.
Its handling (KO_BOOL_EXCLUSIVE) remains in AP0 field definitions; the detection
logic migrates to scope_registry.json under `Logistics:AGV:Forklift.sub_modifiers`.

### 5.5 Artifacts that are REMOVED

| File | Replaced by |
|------|-------------|
| `config/vehicle_types.json` | `config/scope_registry.json` |
| Entity Model tab (structural part) | `② Structure` tab |
| Hardcoded `DATA_SHEETS` list | `③ Scope Registry` tab column `tab_name` |

---

## 6. Runtime Architecture

### 6.1 Startup (app.py)

```
load scope_registry.json          → _SCOPE_REGISTRY, _VALID_SCOPES
load fields.json                  → _FIELDS (all scopes, indexed by UUID)
build scope-filtered field sets   → _FIELDS_BY_SCOPE[scope_id] for each leaf scope
                                    (each set includes inherited parent fields)
load sqlite_schema.json           → schema constants (unchanged)
load unit_semantics.json          → _SIGNED_UNITS (unchanged)
```

No change to startup structure — same pattern, new config files.

### 6.2 Scope Detection (LLM Classification Pass)

**Today:** Two separate detections:
1. `is_agv_amr` (boolean) — Pass 1 basic extraction
2. `agv_type` (Forklift/Tugger/AMR) — Pass 4a

**New architecture:** One unified classification pass with three levels:

```
Pass 4a (unchanged interface, new internals):
  Input:  extracted text, scope_registry.json
  Output: scope_id (e.g. "Logistics:AGV:Forklift"), sub_modifiers (e.g. vna=true)
  
  The LLM is given the scope hierarchy from scope_registry.json
  (display_names + classification_hints + classification_keywords)
  and asked to identify the best matching leaf scope.
```

`is_agv_amr` from Pass 1 is generalized to `detected_industry` (e.g. "Logistics").
If `detected_industry` is null → analysis ends (out-of-scope tender).

**This is Step 5 in the migration plan — NOT implemented in the first steps.**
Until Step 5, Pass 4a continues to output `agv_type` (Forklift/Tugger/AMR) which
is mapped to the scope_id via scope_registry.json `vt_map` equivalent.

### 6.3 Field Loading by Scope

After scope detection, matching and extraction operate only on fields relevant to the
detected scope, resolved via `resolution_order` from scope_registry.json.

```python
# Example: tender is Logistics:AGV:Forklift
active_fields = _FIELDS_BY_SCOPE["Logistics:AGV:Forklift"]
# Contains fields from: scope=* UNION scope=Logistics:AGV UNION scope=Logistics:AGV:Forklift
```

In `matching.py`: `_FIELDS_BY_SCOPE[scope_id]` replaces the current
`fields_by_sheet()` + `_SHARED_SHEET` pattern.

### 6.4 Matching Engine (matching.py)

Changes required:
- `_SHARED_SHEET` constant → removed, replaced by scope inheritance
- `fields_by_sheet()` calls → replaced by `fields_by_scope(scope_id)`
- All other matching logic (operators, null rules, scoring) → **unchanged**

### 6.5 LLM Extraction (app.py)

`extraction_template.txt` is scoped: only fields relevant to the detected scope
are included in the extraction prompt. This is already the case today (filtered by
sheet). Change: filter by `scope_id` instead of `sheet`.

`context_builder.py`: field loading uses `fields_by_scope()` instead of
`fields_by_sheet()`.

---

## 7. Data Layer

### 7.1 SQLite Entity Structure (unchanged)

```
companies          — L1: the commercial seller
  company_id (PK)
  [structural columns from ② Structure tab]
  [business fields with entity=Company from Global tab]

products           — L2: the branded commercial offering
  product_id (PK)
  company_id (FK → companies)
  base_model_id (FK → base_models)
  active
  is_oem_product (derived)
  [structural columns from ② Structure tab]
  [business fields with entity=Product from Global tab]

base_models        — L3: the physical machine (OEM base)
  base_model_id (PK)
  oem_company_id (FK → companies)
  oem_link_public
  last_updated
  [structural columns from ② Structure tab]
  [NO business fields — all go to base_model_extensions]

base_model_extensions — L3 technical fields
  extension_id (PK)
  base_model_id (FK → base_models)
  [ALL business fields with entity=Base Model, from ALL scope tabs]
```

**Key change:** `agv_type` moves from `products` and `base_models` tables into
`base_model_extensions` as a regular field (entity=Base Model, scope=`*`,
level=KO). It is no longer a structural column.

Wait — `agv_type` in the CURRENT `products` table is used for filtering in
`data_loader.py`. This migration must keep this filtering working.
**Resolution:** `agv_type` remains in `products` table (structural for now) AND
exists as a field entry in the Field Registry. This denormalization is explicitly
accepted as a migration constraint and documented as technical debt to be resolved
in Step 3.

### 7.2 Airtable Sync (sync_airtable.py)

No functional change. `sync_airtable.py` reads column lists from `sqlite_schema.json`
(already done via `_CO_COLUMNS`, `_PROD_COLUMNS`, `_EXT_COLUMNS`). As long as
`sqlite_schema.json` continues to emit the same column lists, `sync_airtable.py`
requires no changes in Steps 1–3.

---

## 8. Migration Plan

**Invariant across ALL steps:** test suite must remain green. No behavioral changes
outside the explicitly listed scope of each step.

### Step 1 — De-hardcode DATA_SHEETS (safe entry point)

**What:** generate_all.py reads the list of field tabs from `③ Scope Registry`
(column `tab_name`) instead of the hardcoded `DATA_SHEETS` list.

**Output:** byte-identical `fields.json` and `sqlite_schema.json`. Zero runtime change.

**AP0 change required:** Add `③ Scope Registry` tab with current scopes listed.
Rename existing tabs to match `tab_name` column values, OR keep current tab names
and map them in the Scope Registry.

**Definition of Done:**
- `DATA_SHEETS` constant removed from generate_all.py
- `③ Scope Registry` tab exists in AP0 xlsx with all current scopes
- `python3 scripts/generate_all.py` produces byte-identical output
- All tests green
- Adding a new (empty) tab to `③ Scope Registry` works without Python change

**Risk:** Tab rename breaks existing AP0 content. Mitigation: Scope Registry `tab_name`
column can point to current tab names (no rename required in Step 1).

---

### Step 2 — Replace Entity Model with Structure Registry

**What:** Add `② Structure` tab. generate_all.py reads PK/FK/admin columns from
`② Structure` instead of Entity Model tab. `sqlite_schema.json` structural sections
(PK, FK, admin) come from `② Structure`.

**Output:** Identical `sqlite_schema.json`. Entity Model tab becomes documentation-only.

**Definition of Done:**
- `② Structure` tab populated with all current PK/FK/admin columns
- generate_all.py no longer reads Entity Model tab for schema generation
- `sqlite_schema.json` identical before and after
- Entity Model tab marked as "Documentation Only — not read by generate_all.py"

---

### Step 3 — Remove Denormalization

**What:** Remove `agv_type`, `reference_count`, `lead_time_weeks` from SHARED tab
(they already exist in Global tab or products/base_models via Structure).
Remove `_company_in_ext` / `shared_in_product_columns` logic from generate_all.py.

**Risk level: MEDIUM** — touches DB schema generation and matching field set.

**Pre-condition:** Step 2 complete, Entity Model replaced.

**Definition of Done:**
- No field appears in more than one tab
- `shared_in_product_columns` and `_company_in_ext` logic removed from generate_all.py
- `sqlite_schema.json` extensions_columns count reduced by duplicate count
- All tests green, golden run output unchanged

---

### Step 4 — Introduce `scope` in fields.json (replace `sheet`)

**What:** generate_all.py derives `scope` from tab name and writes it to `fields.json`
instead of (or alongside) `sheet`. Runtime consumers (`app.py`, `matching.py`,
`field_spec.py`) switch from `sheet`-based to `scope`-based field lookup.

**Output:** `fields.json` gains `scope` key, `sheet` key deprecated (kept temporarily).

**Definition of Done:**
- `fields.json` has `scope` on every field
- `_SHARED_SHEET` constant removed from `app.py` and `matching.py`
- `fields_by_sheet()` replaced by `fields_by_scope(scope_id)` everywhere
- `scope_registry.json` generated and loaded at startup
- `vehicle_types.json` merged into `scope_registry.json` (or kept as compatibility shim)
- All tests green, golden run output unchanged

---

### Step 5 — Generalize Scope Detection (Pass 4a)

**What:** Pass 4a LLM call is refactored to use `scope_registry.json`
classification hints instead of hardcoded vehicle type list.
`is_agv_amr` detection in Pass 1 generalized to `detected_industry`.

**Risk level: HIGH** — touches LLM extraction pipeline and prompt generation.
Requires E2E testing against all 5 tenders before declaring done.

**Pre-condition:** Steps 1–4 complete. New backend-llm-tester run mandatory.

**This step is NOT planned in detail here.** It requires its own spec after Steps 1–4
are complete and stable.

---

## 9. Fields That Change Scope/Level as Part of This Migration

These AP0 content changes are bundled with the structural migration (not separate tickets):

| Field | Current tab / level | New tab / level | Reason |
|-------|---------------------|-----------------|--------|
| `navigation_type` | SHARED / COND_KO | Logistics:AGV / CONTEXT | Reviewed: infrastructure_required is the real KO |
| `battery_type` | SHARED / SCORING | Logistics:AGV / CONTEXT | No meaningful scoring between LFP/NMC |
| `fleet_management_system` | SHARED / COND_KO | Logistics:AGV / CONTEXT | Overlaps with VDA5050 and integration_capability |
| `max_fleet_size` | SHARED / SCORING | Logistics:AGV / CONTEXT | No scoring relevance |
| `ingress_protection_rating` | SHARED / COND_KO | Logistics:AGV / CONTEXT | Ordinal matching not yet supported; revisit |
| `floor_flatness_req` | SHARED / COND_KO | Logistics:AGV / CONTEXT | Same — no ordinal operator |
| `infrastructure_required` | SHARED / COND_KO | Logistics:AGV / KO | Rename to `infrastructure_free`, invert boolean, supplier data must be migrated |
| `load_type` allowed values | SHARED / KO | Logistics:AGV / KO | New value set: None / Open Pallet / Closed Pallet / Tote / Custom Container / Other |
| `integration_capability` | SHARED / SCORING | Logistics:AGV / COND_KO | New value set: None / WMS / Physical IO / Industrial Bus |

---

## 10. Open Items (not in this migration)

These are known improvements that are explicitly NOT part of this spec:

| OI | Description |
|----|-------------|
| OI-new-A | CONTEXT fields display section in result card UI |
| OI-new-B | Ordinal operator (`KO_IF_ORD`) for ingress_protection / floor_flatness |
| OI-new-C | `Other` in load_type → triggers "Request" flow |
| OI-new-D | `infrastructure_free` supplier data inversion migration script |
| OI-new-E | Country restructuring (HQ_Country + HQ_City + Offices + service_reach) |
| OI-new-F | `integration_capability` option mapping hint for LLM extraction |
| OI-new-G | Step 5: generalized scope detection (own spec) |

---

## 11. Invariants (must hold after every step)

1. UUID is the primary key for every field. Never changes after first assignment.
2. `field_name` may repeat across scopes. UUID disambiguates.
3. `field_name == db_column` always. Any rename = a migration, not a config change.
4. No industry logic, field names, or scope names hardcoded in Python.
5. `generate_all.py` is the only writer of all files under `config/`. All config is generated.
6. `config/unit_semantics.json` is the sole exception — manually maintained, not generated. It contains universal physics (signed units), not industry logic.
7. The full test suite must be green after every step.
8. Golden run output must be identical after Steps 1–4 (Steps 1–4 are behavior-neutral).

---

## 12. Acceptance Criteria for Complete Migration (Steps 1–4)

- [ ] `DATA_SHEETS` constant does not exist anywhere in `generate_all.py`
- [ ] `_SHARED_SHEET` constant does not exist anywhere in Python code
- [ ] Entity Model tab in AP0 is marked documentation-only and not read by any script
- [ ] `fields.json` has `scope` on every entry; `sheet` key absent
- [ ] `scope_registry.json` exists and is loaded at startup
- [ ] `vehicle_types.json` is superseded (either merged or replaced)
- [ ] Adding a new industry scope to AP0 (new tab + new Scope Registry row) requires zero Python changes
- [ ] No field appears in more than one tab of the AP0 xlsx
- [ ] 204+ tests pass (current count)
- [ ] All 5 golden tenders produce identical output before/after migration
- [ ] `sync_airtable.py --local` completes without error

---

## 13. What This Spec Does NOT Cover

- UI changes (result card CONTEXT section, DB browser updates)
- AP0 content changes beyond those listed in Section 9
- New supplier/tender data entry
- Step 5 (generalized scope detection)
- Performance implications of scope-filtered field loading

---

*End of Spec v0.1 — Awaiting PO approval before implementation begins.*
