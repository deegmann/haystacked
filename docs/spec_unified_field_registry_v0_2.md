# haystacked Platform — Unified Field Registry Architecture
## Spec v0.2 — DRAFT FOR SENIOR REVIEW

**Status:** Internal review (Senior Architect). Not yet approved for implementation.
**Authored:** 2026-07-09
**Changes vs v0.1:** All 6 Blockers resolved. Classification Guide concept added.
  Top Majors addressed (M1, M3, M4, M6, M7, M8, M9, M10, M11).
  Step order corrected. §9 Content Changes separated from structural migration.

---

## 1. Motivation & Problem Statement

### 1.1 The structural rip (unchanged from v0.1)

The AP0 xlsx today has two separate sections:

```
Entity Model tab  → generate_all.py → sqlite_schema.json → DB columns
DATA_SHEETS tabs  → generate_all.py → fields.json        → matching/scoring
```

A field needing both DB storage AND matching must be maintained in both sections
manually, with no cross-check. Fields disappear silently. This is the root cause of
the inconsistencies found in the July 2026 AP0 review.

### 1.2 Hardcoded scope names

```python
DATA_SHEETS = ["SHARED – All AGV Types", "Forklift AGV", "Tugger AGV", "Mobile AMR"]
```

This constant — and equivalent sheet-name strings — appears across `generate_all.py`
at lines 66, 243, 739, 891, 1283 and in `app.py`, `matching.py`, `context_builder.py`.
Adding a new industry or subcategory requires Python changes. That is the primary
extensibility blocker this migration resolves.

### 1.3 Design goals (unchanged)

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
| **Scope** | The context a field applies in. Written as `Industry:Category:Subcategory`. `*` = global. Colons are notation only — not used in Excel tab names (see §4.1). |
| **Entity** | Which DB table a field belongs to: `Company`, `Product`, or `Base Model`. |
| **Primary Key (PK)** | The unique ID column of a DB table (`company_id`, `product_id`, etc.). Structural — not a business field. |
| **Foreign Key (FK)** | A column referencing another table's PK. Structural only. E.g. `product.company_id → companies.company_id`. |
| **Structural field** | PK, FK, and admin columns (`last_updated`, `active`). Lives in ② Structure tab. Not in Field Registry. |
| **Field Registry** | All business fields across all scopes. Lives in scope tabs. |
| **Scope Registry** | Hierarchy definition + LLM classification guide. One tab (③) in the AP0. |
| **Structure Registry** | DB table structure (PK/FK/admin). One tab (②) in the AP0. Replaces Entity Model. |
| **Classification Guide** | Per-scope text that teaches the LLM what belongs in that scope, what doesn't, and typical tender phrases. Part of ③ Scope Registry. |
| **Resolution order** | The ordered list of scopes whose fields apply to a given leaf scope. E.g., for `Logistics:AGV:Forklift`: `[*, Logistics:AGV, Logistics:AGV:Forklift]`. |
| **Legacy values** | Old string values (`"Forklift AGV"`) that map to a new scope_id. Defined in ③ Scope Registry for backward compatibility during migration. |

---

## 3. AP0 xlsx — New Tab Structure

### 3.1 Tab inventory

**Fixed metadata tabs** (never field tabs, never read as scope tabs):

| Tab name | Purpose | Read by generate_all.py? | How |
|----------|---------|--------------------------|-----|
| `① Read me & changes` | Human documentation | No | — |
| `② Structure` | DB table PKs, FKs, admin columns | Yes | Dedicated parser |
| `③ Scope Registry` | Scope hierarchy + classification guide | Yes | Dedicated parser → scope_registry.json |
| `Field Fallbacks` | Regex-based field overrides | Yes | Existing parser (unchanged) |
| `Vehicle Types` | Superseded in Step 7. Kept until then. | Yes until Step 7 | Existing parser |
| `Representatives` | Data entry only | No | — |

**Scope tabs** (contain business fields; listed in ③ Scope Registry `tab_name` column):

| Tab name | Scope ID | Parent scope |
|----------|----------|--------------|
| `Global` | `*` | — |
| `AGV_Shared` | `Logistics:AGV` | `*` |
| `AGV_Forklift` | `Logistics:AGV:Forklift` | `Logistics:AGV` |
| `AGV_Tugger` | `Logistics:AGV:Tugger` | `Logistics:AGV` |
| `AGV_AMR` | `Logistics:AGV:AMR` | `Logistics:AGV` |

Tab names are FREE — any valid Excel name works (no special characters required).
The authoritative link between tab name and scope_id is the `tab_name` column in
③ Scope Registry. `generate_all.py` reads ③ first, then reads exactly the tabs
listed there. It does NOT derive scope_id from tab names.

Future industry example:
| `Printing_Shared` | `Printing` | `*` |
| `Printing_Offset` | `Printing:Offset` | `Printing` |

Zero Python changes needed to add these.

### 3.2 Tab `② Structure` — DB Table Definitions

Defines PKs, FKs, and admin columns per DB table. Does NOT contain business fields.

**Columns:**

| Column | Description | Example |
|--------|-------------|---------|
| `table` | SQLite table name | `products` |
| `column` | Column name | `company_id` |
| `sqlite_type` | `TEXT`, `INTEGER`, `REAL`, `BOOLEAN` | `TEXT` |
| `role` | `PK`, `FK`, `ADMIN`, `DERIVED` | `FK` |
| `references` | For FK only: `table.column` | `companies.company_id` |
| `nullable` | `✓` if NULL allowed (blank = NOT NULL) | `✓` |
| `notes` | Human note | `System-generated UUID` |

**Entity → physical table mapping** (machine-readable, part of ② Structure):

| entity_id | physical_table | pk_column | fk_to_parent | fk_column |
|-----------|----------------|-----------|--------------|-----------|
| `Company` | `companies` | `company_id` | — | — |
| `Product` | `products` | `product_id` | `Company` | `company_id` |
| `Base Model` | `base_model_extensions` | `extension_id` | `Product` | `base_model_id` |

Note: `base_models` is a structural table (OEM link, oem_link_public, last_updated)
with no business fields. It sits between `products` and `base_model_extensions` for
the OEM-rebadge pattern. All `entity=Base Model` business fields go to
`base_model_extensions`. This table entry is also in ② Structure.

### 3.3 Tab `③ Scope Registry`

**Columns:**

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `scope_id` | Text | Unique scope ID. `Industry:Category:Subcategory` notation. `*` = global. | `Logistics:AGV:Forklift` |
| `parent_scope` | Text | Parent scope_id. Blank for top-level. | `Logistics:AGV` |
| `display_name` | Text | Human-readable label for UI | `Forklift AGV` |
| `tab_name` | Text | Name of the Excel tab that holds this scope's fields. Blank if scope has no own tab (intermediate node only). | `AGV_Forklift` |
| `legacy_values` | Text | Pipe-separated old field values that map to this scope. Used during migration and for backward compat in matching.py. | `Forklift AGV\|VNA Forklift` |
| `active` | Boolean | `✓` if currently in use | `✓` |
| `classification_guide` | Long Text | See §3.4 | _(multi-line)_ |
| `classification_keywords` | Text | Pipe-separated trigger words for LLM | `forklift\|reach truck\|stacker` |

### 3.4 Classification Guide — How the LLM identifies a scope

The `classification_guide` column in ③ Scope Registry teaches the LLM what belongs
in each scope. It is the authoritative source replacing the current hardcoded
`is_agv_amr` pass and `vehicle_types.json` classification logic.

**Required content per scope entry:**

1. **What this scope IS** — positive definition. What physical object or process does
   a tender describe when it falls into this scope?
2. **What this scope is NOT** — exclusion criteria. Where is the boundary with adjacent
   or similar scopes? (E.g. `Logistics:AGV:Forklift` is NOT rack-bound shuttles, NOT
   conveyor systems, NOT manually operated forklifts.)
3. **Typical tender phrases** — verbatim or paraphrased language that appears in
   real tenders for this scope. This is the highest-signal input for classification.
4. **Boundary examples** — one or two edge cases with the correct classification.

**Example entry for `Logistics:AGV:Forklift`:**

```
WHAT IT IS:
An autonomous ground vehicle with a lifting mast and forks, designed to pick up,
transport, and place pallets or similar unit loads. May operate in standard aisles
(≥2.5 m) or narrow aisles (VNA, ≤1.8 m). Includes reach trucks, counterbalanced
forklifts, and VNA turret trucks — as long as they are automated/autonomous.

WHAT IT IS NOT:
- Manually operated forklifts (human driver, no autonomous mode)
- Rack-bound shuttles or AS/RS (move on rails inside racking)
- Underride AMRs that carry pallets at floor level without lifting (→ Logistics:AGV:AMR)
- Conveyor systems (fixed infrastructure, no ground vehicle)
- Tugger AGVs pulling trains of carts (→ Logistics:AGV:Tugger)

TYPICAL TENDER PHRASES:
"automatischer Gabelstapler", "autonomous forklift", "AGV mit Hubmast",
"Fahrerloser Hubwagen", "automated reach truck", "FTS Schmalgangstapler",
"VNA-Stapler", "Automated Storage and Retrieval" (only if AGV-based, not rack-bound)

BOUNDARY EXAMPLES:
- "Autonomous pallet mover without lifting" → Logistics:AGV:AMR (no mast)
- "Self-driving reach truck for high-bay warehouse" → Logistics:AGV:Forklift ✓
```

**Classification pass** (Pass 4a in current system; generalized in Step 7):

The LLM receives:
- The full resolution order of active leaf scopes from scope_registry.json
- The `classification_guide` and `classification_keywords` for each
- The extracted tender text

It returns: a single `scope_id` (must be a leaf scope or `*` if out-of-scope).
If classification confidence is low, it returns the deepest matching ancestor scope
(non-leaf). Runtime behavior for non-leaf result: apply ancestor fields only, log
"partial classification", do not apply subcategory-specific KO rules.

**Level 1 detection** (replaces `is_agv_amr`):
An "in-scope" check runs first against top-level industry scopes. If no industry
matches → analysis ends, result = "out of scope". This is the generalization of
the current `is_agv_amr` boolean from Pass 1.

**Until Step 7:** Existing Pass 1 (`is_agv_amr`) and Pass 4a (`agv_type`) remain
unchanged. `scope_registry.json` is generated but used read-only for the legacy-
values mapping and reference. No classification behavior changes before Step 7.

### 3.5 Field Tab Column Format (all scope tabs identical)

**Columns in every scope tab:**

| Column | Required | Description | Example |
|--------|----------|-------------|---------|
| `uuid` | Yes | Auto-assigned on first entry. Never changes. | `18b0abbe-...` |
| `field_name` | Yes | Lowercase, underscores. May repeat across industries (UUID disambiguates). MUST equal db_column name (see §5.1 invariant). | `max_payload_kg` |
| `entity` | Yes | `Company`, `Product`, or `Base Model` | `Base Model` |
| `data_type` | Yes | `Text`, `Integer`, `Float`, `Boolean`, `Multi-Select`, `Dropdown`, `Date`, `URL` | `Float` |
| `unit` | No | Physical unit | `kg` |
| `level` | Yes | `KO`, `COND_KO`, `SCORING`, `CONTEXT` | `KO` |
| `operator` | Cond. | Required if level ≠ CONTEXT. `KO_IF_LT`, `KO_IF_GT`, `KO_IF_NEQ`, `KO_BOOL_REQUIRED`, `KO_BOOL_EXCLUSIVE`, `KO_SUBSET` | `KO_IF_LT` |
| `allowed_values` | Cond. | Pipe-separated. Required for Dropdown/Multi-Select. | `None\|Open Pallet\|Tote` |
| `scoring_weight` | Cond. | Required if level=SCORING | `0.15` |
| `score_function` | Cond. | `LINEAR`, `THRESHOLD`, `STEP`. Required if SCORING. | `LINEAR` |
| `threshold_a` | No | Score function parameter A | `100` |
| `threshold_b` | No | Score function parameter B | `500` |
| `value_if_null` | No | LL-11 default for NULL supplier values | `False` |
| `plausibility_min` | No | Minimum plausible value (LLM validation) | `0` |
| `plausibility_max` | No | Maximum plausible value | `50000` |
| `llm_hint` | No | LLM extraction instruction | `Maximum payload in kg...` |
| `ui_hint` | No | Clarification Dialog help text | `Max load the AGV can carry` |
| `display_mode` | No | `always`, `on_value`, `never` | `on_value` |

**Derived at generation time — NOT columns in xlsx:**

| Key in fields.json | Derivation |
|--------------------|-----------|
| `scope` | From Scope Registry: scope_id whose `tab_name` matches this tab |
| `tender_key` | Auto-derived: `"required_" + field_name` for all supplier fields. Tender-only fields use `field_name` directly. Never manually entered. |

`generate_all.py` asserts at generation time:
- Every field with `level ≠ CONTEXT` has a non-blank `operator`.
- Every field with `data_type = Dropdown` or `Multi-Select` has non-blank `allowed_values`.
- Every field with `level = SCORING` has non-blank `scoring_weight`.
- No duplicate `field_name` along any resolution chain (see §5.1 invariant M7).
- `tender_key` for no two fields in the same scope share a value.

---

## 4. Generated Artifacts

### 4.1 `config/fields.json` — Unified Field Registry

**Key:** UUID (unchanged).

**Changes from current:**
- `scope` added (derived from tab; replaces `sheet`).
- `sheet` key removed (breaking change — consumers updated in Step 3, §8.3).
- All other keys unchanged.

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
    "allowed_values": ["Laser Reflector", "Natural Feature (SLAM)", "QR/DM Code"],
    "scoring_weight": null,
    "value_if_null":  null,
    "hint":           "...",
    "ui_hint":        "...",
    "display_mode":   "on_value"
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
    "Forklift AGV": "Logistics:AGV:Forklift",
    "Tugger AGV":   "Logistics:AGV:Tugger",
    "Mobile AMR":   "Logistics:AGV:AMR",
    "VNA Forklift": "Logistics:AGV:Forklift"
  }
}
```

`legacy_map` is a flat reverse index of all `legacy_values` across all scopes.
`matching.py` uses `legacy_map[prod.agv_type]` to resolve supplier scope_id.
This resolves Blocker B6.

### 4.3 `config/sqlite_schema.json` — Derived from Field Registry

Generated as today, but source changes:
- Structural sections (PK, FK, admin columns) → from `② Structure` tab
- Business column sections → from `fields.json` grouped by entity

No change to the consumer interface: `companies_columns`, `products_columns`,
`extensions_columns` lists remain. `sync_airtable.py` unchanged through Step 5.

### 4.4 `config/vehicle_types.json`

Kept until Step 7. After Step 7, superseded by `scope_registry.json`.
`generate_all.py` continues to generate it from the `Vehicle Types` tab until Step 7.

### 4.5 Literal inventory — all strings to de-hardcode

Complete list of locations containing scope/industry/sheet names that must be
resolved by the end of migration:

| Location | Literal | Resolved in Step |
|----------|---------|-----------------|
| `generate_all.py:66` | `DATA_SHEETS = [...]` | Step 1 |
| `generate_all.py:243` | `sheet_map` dict (scoring weights) | Step 1 |
| `generate_all.py:739` | `build_extraction_template` sheet loop | Step 1 |
| `generate_all.py:891` | `basic_template` AGV literals | Step 7 |
| `generate_all.py:1283` | sheet name reference | Step 1 |
| `matching.py` | `_SHARED_SHEET` constant | Step 3 |
| `matching.py:441` | `prod.agv_type` filter | Step 3 (via legacy_map) |
| `app.py` | `_VALID_VTS`, vehicle type constants | Step 3 |
| `app.py` | `is_agv_amr` pass | Step 7 |
| `context_builder.py` | `fields_by_sheet()` calls | Step 3 |
| Test files | `_SHARED_SHEET` imports | Step 3 |
| `/api/field-meta` endpoint | `sheet` key in response | Step 3 |
| Frontend JS | `_fieldMeta[key].sheet` usage | Step 3 |

---

## 5. Invariants

These hold after every migration step and in all future development.

1. **UUID is the primary key** for every field. Never changes after first assignment.
2. **`field_name` may repeat across industries.** UUID disambiguates. Within a single
   resolution chain, no `field_name` may appear more than once (see §5.1).
3. **`field_name == db_column` always.** The field_name in the AP0 is the SQLite column
   name — no mapping, no alias. A rename requires a DB migration.
4. **No industry/scope/sheet names hardcoded in Python** after Step 7.
5. **`generate_all.py` is the sole writer** of all files under `config/`.
   `config/unit_semantics.json` is the only manually maintained exception.
6. **Full test suite must be green after every step.**
7. **Steps 1–5 are behavior-neutral:** golden run output identical before and after.
8. **Step 6 (Content Changes) has its own Golden Refresh.** It is the only step
   that intentionally changes matching behavior.

### 5.1 field_name uniqueness along a resolution chain

`generate_all.py` asserts at generation time:
- No two fields in the same resolution chain share a `field_name`.
- Sibling scopes (e.g. `Logistics:AGV:Forklift` and `Logistics:AGV:Tugger`) may share
  a `field_name` only if `entity`, `data_type`, and `unit` are identical. This allows
  the same physical spec to exist in both subtypes without type collision.
- Violation → generation fails with an explicit error naming the conflicting fields.

This is the condition under which the `field_name == db_column` invariant (§5, point 3)
holds without type collision in the wide `base_model_extensions` table.

### 5.2 NULL semantics in base_model_extensions

`base_model_extensions` is a single wide table covering all industries.
A NULL value in a scope-specific column means **"unknown or not applicable."**
This is consistent with the existing Blank ≠ Zero principle (LL-06): NULL means
the value was not provided, not that the capability is zero.
Scope-irrelevant columns (e.g. a Printing-scope column for an AGV product) will
always be NULL and are never evaluated by the matching engine (scope-filtered
field loading prevents it).

---

## 6. Runtime Architecture

### 6.1 Startup

```
load scope_registry.json   → _SCOPE_REGISTRY, _VALID_SCOPES, _LEGACY_MAP
load fields.json           → _FIELDS (all scopes, indexed by UUID)
build per-scope field sets → for each leaf scope: apply resolution_order to collect fields
load sqlite_schema.json    → existing schema constants (unchanged)
load unit_semantics.json   → _SIGNED_UNITS (unchanged)
```

`_LEGACY_MAP` enables `matching.py` to resolve `prod.agv_type = "Forklift AGV"` →
scope_id `"Logistics:AGV:Forklift"` during the transition period (Steps 3–6).
After Step 7, `prod.agv_type` values are scope_ids directly.

### 6.2 Scope Detection (until Step 7 — unchanged behavior)

Pass 1 continues to detect `is_agv_amr`. Pass 4a continues to detect `agv_type`
(Forklift/Tugger/AMR). The scope_id is resolved via `_LEGACY_MAP` at runtime.
No change to extraction or classification behavior before Step 7.

### 6.3 Scope Detection (Step 7 — new behavior)

Replaces hardcoded Pass 1 + Pass 4a with a unified classification pass using
`scope_registry.json` classification guides. See §3.4 for full definition.
Step 7 requires its own sub-spec before implementation.

### 6.4 Field Loading by Scope

```python
# After scope detection: scope_id = "Logistics:AGV:Forklift"
resolution = _SCOPE_REGISTRY["resolution_order"]["Logistics:AGV:Forklift"]
# → ["*", "Logistics:AGV", "Logistics:AGV:Forklift"]

active_fields = {
    uuid: spec
    for uuid, spec in _FIELDS.items()
    if spec["scope"] in resolution
}
```

This replaces `fields_by_sheet()` + `_SHARED_SHEET` pattern throughout the codebase.

### 6.5 Matching and Extraction

Matching engine (`matching.py`): field collection replaces sheet-based with
scope-based lookup. All operator logic, null rules, and scoring unchanged.

Extraction (`app.py`, `context_builder.py`): `extraction_template.txt` generation
uses scope-filtered fields. Context builder uses `fields_by_scope()`. No change
to prompt structure, LLM call structure, or output parsing.

---

## 7. Data Layer

### 7.1 SQLite tables (unchanged structure through Step 5)

```
companies              PK: company_id
  [structural: ② Structure]
  [business: entity=Company fields from Global tab]

products               PK: product_id  FK→companies
  [structural: ② Structure incl. active, is_oem_product]
  [business: entity=Product fields from Global tab]
  agv_type             ← RETAINED as structural column through Step 6
                          (technical debt; resolved in Step 7)

base_models            PK: base_model_id  FK→companies (oem)
  [structural only: oem_company_id, oem_link_public, last_updated]
  [NO business fields]

base_model_extensions  PK: extension_id  FK→base_models
  [ALL entity=Base Model business fields from ALL scope tabs]
```

`agv_type` in `products` is retained as a structural column through Step 6.
It is populated by Airtable sync and used by `data_loader.py` for VT filtering.
Step 7 migrates it to a scope_id-valued field in `base_model_extensions`.
This is **explicitly accepted technical debt**, documented here.

### 7.2 Airtable Sync

`sync_airtable.py` reads column lists from `sqlite_schema.json`
(`_CO_COLUMNS`, `_PROD_COLUMNS`, `_EXT_COLUMNS`). As long as `sqlite_schema.json`
emits the same column lists, `sync_airtable.py` requires no changes.

**Exception — Step 5 (Denormalization):** Removing duplicate fields from SHARED tab
reduces `extensions_columns`. This changes which columns `sync_airtable.py` writes to
`base_model_extensions`. A full CSV re-export from Airtable and DB rebuild is required
after Step 5. This is a **mandatory post-Step-5 operation** (see §8.5).

---

## 8. Migration Steps

**Global invariant:** Test suite green after every step. Steps 1–5: golden run output
identical. Step 6: intentional behavior change with its own golden refresh.

### Step 1 — De-hardcode DATA_SHEETS

**What:** `generate_all.py` reads the field-tab list from ③ Scope Registry
(`tab_name` column) instead of the hardcoded `DATA_SHEETS` list. All sheet-name
string literals in `generate_all.py` at lines 66, 243, 739, 1283 replaced with
dynamic lookups from the scope registry.

**AP0 change required:**
- Add `③ Scope Registry` tab with current scopes and their `tab_name` values.
- `tab_name` values for current tabs: `SHARED – All AGV Types` → `tab_name = "SHARED – All AGV Types"` (no rename needed yet).

**Output:** byte-identical `fields.json` and `sqlite_schema.json`.

**DoD:**
- `DATA_SHEETS` constant removed from `generate_all.py`
- `③ Scope Registry` tab exists with all 4 current scopes + Global row
- `generate_all.py` output byte-identical vs. before
- Adding an empty new row to ③ with a new (non-existent) `tab_name` → generates warning, no crash
- All tests green

---

### Step 2 — Structure Registry (replaces Entity Model)

**What:** Add `② Structure` tab with PK/FK/admin columns + entity→table mapping.
`generate_all.py` reads structural sections from `② Structure` instead of Entity Model.

**Output:** Identical `sqlite_schema.json`. Entity Model tab becomes documentation-only
(add a note: "DOCUMENTATION ONLY — not read by any script").

**DoD:**
- `② Structure` tab populated with all current PKs, FKs, admin columns, and entity-table mapping
- `generate_all.py` no longer reads Entity Model tab for schema generation
- `sqlite_schema.json` identical before and after
- All tests green

---

### Step 3 — `scope` in fields.json (replace `sheet`)

**What:** `generate_all.py` derives `scope` for each field from the ③ Scope Registry
and writes it to `fields.json`. The `sheet` key is removed.

All consumers updated to use `scope` instead of `sheet`:
- `matching.py`: `_SHARED_SHEET` constant removed; field loading uses `scope` + resolution_order
- `app.py`: `_VALID_VTS` sourced from `scope_registry.json` `legacy_map`; `prod.agv_type` →
  scope_id via `_LEGACY_MAP`
- `context_builder.py`: `fields_by_sheet()` → `fields_by_scope(scope_id)`
- `/api/field-meta` endpoint: `sheet` key replaced by `scope` in response
- Frontend JS: all `_fieldMeta[key].sheet` usages replaced by `_fieldMeta[key].scope`
- Test files: `_SHARED_SHEET` imports removed

`scope_registry.json` generated and loaded at startup.
`vehicle_types.json` still generated (unchanged) — full supersession in Step 7.

**Output:** `fields.json` has `scope` instead of `sheet`. Matching behavior identical
(legacy_map translates agv_type → scope_id transparently).

**DoD:**
- `sheet` key absent from `fields.json`
- `_SHARED_SHEET` constant absent from all Python files
- `scope_registry.json` generated and loaded at startup
- `/api/field-meta` response contains `scope` key
- Frontend JS uses `.scope` not `.sheet`
- All test files compile without `_SHARED_SHEET` import
- All tests green
- 5 golden tenders: identical output

---

### Step 4 — Tab Restructuring (Global tab + field movement)

**What:** Create `Global` tab in AP0 xlsx. Move all `entity=Company` and
`entity=Product` fields from `SHARED – All AGV Types` to `Global`.
Add `Global` to ③ Scope Registry with `tab_name = "Global"`.

Rename `SHARED – All AGV Types` → `AGV_Shared` (or keep old name — tab_name in
Scope Registry controls the link, not the tab name itself).
Add `scope_id = "Logistics:AGV"` to Scope Registry pointing to the SHARED tab.

**This step is purely AP0 content rearrangement.** No Python changes.
`generate_all.py` already reads all tabs listed in ③ dynamically (after Step 1).

Fields moved to `Global` tab (entity=Company or entity=Product):
- `country`, `employee_count_range`, `founding_year`, `website`, `certifications_generic`,
  `languages_spoken`, `export_capable` (Company)
- `product_name`, `product_description`, `reference_count`, `lead_time_weeks`,
  `distribution_model`, `service_coverage`, `active` (Product)

**Output:** Same fields.json content, now with correct `scope` values (`*` for global
fields, `Logistics:AGV` for shared AGV fields).

**DoD:**
- `Global` tab exists with all Company + Product fields
- `SHARED` tab contains only `entity=Base Model` fields
- ③ Scope Registry has entries for `*` (Global tab) and `Logistics:AGV` (AGV_Shared tab)
- `generate_all.py` output: each moved field now has `scope = "*"` instead of `scope = "Logistics:AGV"`
- All tests green
- 5 golden tenders: identical output (scope change is metadata; matching uses scope-aware field loading)

---

### Step 5 — Remove Denormalization

**What:** Remove fields that appear in multiple scope tabs.
Current duplicates:
- `agv_type`: in SHARED (now AGV_Shared) as matching field. In `products` table as structural column.
  → Remove from AGV_Shared field tab. Retain in `products` as structural column (Step 7 resolves this).
- Any field that appears in both Global and AGV_Shared → remove from AGV_Shared.

Remove `_company_in_ext` / `shared_in_product_columns` logic from `generate_all.py`.

**Post-Step-5 mandatory operations:**
1. Re-export all tables from Airtable as CSV (to pick up schema changes)
2. DB rebuild: `python3 sync_airtable.py --local` (applies schema migration)
These are not optional. They must be documented and executed as part of Step 5.

**DoD:**
- No field_name appears in more than one scope tab
- `generate_all.py` has no `_company_in_ext` / `shared_in_product_columns` logic
- `extensions_columns` count reduced by duplicate count (document expected delta)
- CSV re-export + DB rebuild completed
- All tests green
- 5 golden tenders: identical output

---

### Step 6 — Content Changes (AP0 field level/operator changes)

**What:** Apply all AP0 content changes from the July 2026 review. This is the ONLY
step that intentionally changes matching behavior. Requires its own golden refresh.

**Content changes (complete list):**

| Field | Change | Data migration required? |
|-------|--------|--------------------------|
| `navigation_type` | COND_KO → CONTEXT | No |
| `battery_type` | SCORING → CONTEXT | No |
| `fleet_management_system` | COND_KO → CONTEXT | No |
| `max_fleet_size` | SCORING → CONTEXT | No |
| `ingress_protection_rating` | COND_KO → CONTEXT | No |
| `floor_flatness_req` | COND_KO → CONTEXT | No |
| `infrastructure_required` | Rename → `infrastructure_free`, Boolean inverted, operator stays KO_BOOL_REQUIRED | YES — all supplier values inverted (migration script mandatory before AP0 change takes effect) |
| `load_type` | allowed_values updated: None / Open Pallet / Closed Pallet / Tote / Custom Container / Other | Mapping script for existing values mandatory |
| `integration_capability` | SCORING → COND_KO, operator KO_SUBSET, allowed_values: None / WMS / Physical IO / Industrial Bus | Mapping script for existing values mandatory |

**For each field with "data migration required":**
- Migration script written and reviewed BEFORE AP0 change is committed
- Script is idempotent (safe to re-run)
- Script verified on dev DB before production

**DoD:**
- All content changes applied in AP0 xlsx
- `generate_all.py` run; `config/` regenerated
- Data migration scripts run for infrastructure_free + load_type + integration_capability
- Golden run on all 5 tenders with updated expectations documented
- All tests updated for new behavior
- New golden baseline committed

---

### Step 7 — Generalize Scope Detection

Replaces hardcoded `is_agv_amr` + Pass 4a with classification guide-driven detection.
This is the step that achieves "zero Python changes for a new industry."

**Pre-condition:** Steps 1–6 complete and stable.
**This step requires its own sub-spec before implementation begins.**

Scope: `app.py` Pass 1 + Pass 4a restructuring; `basic_template` AGV literals removed;
`vehicle_types.json` superseded by `scope_registry.json`.

---

## 9. Open Items (explicitly out of scope for this migration)

| ID | Description |
|----|-------------|
| OI-A | CONTEXT fields display section in result card UI |
| OI-B | Ordinal operator (`KO_IF_ORD`) for ordered categorical fields |
| OI-C | `Other` in load_type → triggers Request flow |
| OI-D | Country restructuring: HQ_Country + HQ_City + Offices + service_reach |
| OI-E | max/min_project_value_eur removal from Entity Model (Step 2 prerequisite check) |
| OI-F | integration_capability LLM extraction hint (how LLM maps "SAP WM" → WMS) |
| OI-G | Step 7 sub-spec |

---

## 10. Acceptance Criteria (Steps 1–6 complete)

- [ ] `DATA_SHEETS` constant absent from all Python files
- [ ] `_SHARED_SHEET` constant absent from all Python files
- [ ] Entity Model tab marked documentation-only
- [ ] `fields.json`: every entry has `scope`, no `sheet` key
- [ ] `scope_registry.json` generated, loaded at startup, contains classification guides
- [ ] No field appears in more than one AP0 scope tab
- [ ] Adding a new scope (new Scope Registry row + new tab): zero Python changes needed
- [ ] `infrastructure_free` Boolean inversion complete + verified in matching
- [ ] `load_type` + `integration_capability` new option sets active + data migrated
- [ ] Test suite ≥ 204 passing
- [ ] 5 golden tenders: Steps 1–5 produce identical output; Step 6 has new baseline
- [ ] `sync_airtable.py --local` completes without error after each step

---

*End of Spec v0.2*
