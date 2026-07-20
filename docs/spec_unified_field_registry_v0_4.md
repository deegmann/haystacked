# haystacked Platform — Unified Field Registry Architecture
## Spec v0.4 — DRAFT FOR SENIOR REVIEW

**Status:** APPROVED FOR IMPLEMENTATION (Senior Architect, 2026-07-09). Steps 1–5 may begin.
**Authored:** 2026-07-09
**Changes vs v0.3:**
- B-v3-1: §7.2 delta corrected — all 10 duplicates live in extensions; remove from
  extensions only; products/companies unchanged.
- B-v3-2: Step 6 migration order corrected — AP0 + generate_all before CSV re-export.
- N-1: `agv_type` excluded from Step 4 move rule; stays in AGV_Shared as transitional.
- N-2: Step 5 pre-flight assert hardened (data check, not conceptual check).
- N-3: No-op DoD criterion removed from Step 5.
- §3.4 wording contradiction resolved (non-leaf result).
- §3.5 xlsx-column → JSON-key mapping table added.
- Tab rename timing clarified (Step 1 = current names; Step 4 = renames).
- §4.4 literal inventory completed (app.py:1064, context_builder.py verified clean,
  test file named, line numbers corrected).

---

## 1. Motivation & Problem Statement

### 1.1 The structural rip

```
Entity Model tab  → generate_all.py → sqlite_schema.json → DB columns
DATA_SHEETS tabs  → generate_all.py → fields.json        → matching/scoring
```

A field needing both DB storage AND matching must be maintained in both sections
manually, with no cross-check. Additionally, 10 business fields are duplicated from
the SHARED tab into `base_model_extensions` (verified in `generate_all.py:501-520`).

### 1.2 Hardcoded scope names

```python
DATA_SHEETS = ["SHARED – All AGV Types", "Forklift AGV", "Tugger AGV", "Mobile AMR"]
```

Adding a new industry or subcategory requires Python changes. This migration removes
that constraint.

### 1.3 Design goals

1. One entry per field. Defined exactly once; all properties on that one row.
2. No hardcoded scope/industry names in Python after Step 7.
3. Industry → Category → Subcategory hierarchy. Adding a new industry = AP0 changes
   only. Zero Python changes (after Step 7).
4. UUID as primary key for fields.
5. Complete spec before any implementation.

---

## 2. Glossary

| Term | Definition |
|------|-----------|
| **Scope** | Context a field applies in. Written `Industry:Category:Subcategory`. Colons are notation only — NOT Excel tab names. |
| **Structural field** | PK, FK, ADMIN columns. Lives in ② Structure. Not in Field Registry. |
| **PLAIN field** | Stored in DB, no matching semantics. `role=PLAIN` in ②. Not a business field. E.g. `product_description`, `is_oem_product`. |
| **Field Registry** | All business fields (KO/COND_KO/SCORING/CONTEXT) across all scopes. Lives in scope tabs. |
| **Scope Registry** | Scope hierarchy + classification guides. Tab ③. |
| **Structure Registry** | DB table structure (PK/FK/PLAIN/ADMIN). Tab ②. Replaces Entity Model. |
| **Classification Guide** | Per-scope text for scope detection only. No influence on extraction or matching. |
| **Resolution order** | Ordered scopes applied to a leaf scope. `Logistics:AGV:Forklift` → `[*, Logistics:AGV, Logistics:AGV:Forklift]`. |
| **Legacy values** | Old string values (e.g. `"Forklift AGV"`) mapping to a scope_id. Defined in ③. |

---

## 3. AP0 xlsx — New Tab Structure

### 3.1 Tab inventory

**Fixed metadata tabs** (not scope tabs):

| Tab name | Purpose | Read by generate_all.py? |
|----------|---------|--------------------------|
| `① Read me & changes` | Human documentation | No |
| `② Structure` | DB table PKs, FKs, PLAIN/ADMIN columns, entity-table mapping | Yes — dedicated parser |
| `③ Scope Registry` | Scope hierarchy + classification guides → scope_registry.json | Yes — dedicated parser |
| `Field Fallbacks` | Regex field overrides | Yes — existing parser unchanged |
| `Vehicle Types` | Superseded in Step 7. Kept until then. | Yes until Step 7 |
| `Representatives` | Data entry only | No |

**Scope tabs** (enumerated in ③ `tab_name` column):

| Target tab name | Scope ID | Parent scope |
|-----------------|----------|--------------|
| `Global` | `*` | — |
| `AGV_Shared` | `Logistics:AGV` | `*` |
| `AGV_Forklift` | `Logistics:AGV:Forklift` | `Logistics:AGV` |
| `AGV_Tugger` | `Logistics:AGV:Tugger` | `Logistics:AGV` |
| `AGV_AMR` | `Logistics:AGV:AMR` | `Logistics:AGV` |

**Tab rename timing:** ③ is populated at Step 1 using the *current* tab names verbatim
(e.g. `"SHARED – All AGV Types"`, `"Forklift AGV"`). Physical tab renames (to the
target names above) happen in Step 4, alongside the ③ row updates — zero code
impact by design (generate_all.py reads tab_name dynamically).

**Error policy:** Blank `tab_name` = valid intermediate node (no own fields). Non-blank
`tab_name` absent from the workbook = **hard generation error**. No warning-then-continue.

### 3.2 Tab `② Structure` — DB Table Definitions

**Role enum:**

| Role | Meaning |
|------|---------|
| `PK` | Primary key column |
| `FK` | Foreign key referencing another table |
| `ADMIN` | System column: `active`, `last_updated`, `is_oem_product`, etc. |
| `PLAIN` | Stored in DB, no matching semantics. Not a Field Registry entry. |
| `DERIVED` | Computed at query time, not stored. |

**Columns in ② Structure:** `table`, `column`, `sqlite_type`, `role`, `references`
(FK only: `table.column`), `nullable` (`✓` or blank), `notes`.

**Entity → physical table mapping** (machine-readable via PK rows in ② Structure):

| entity_id | physical_table | pk_column | fk_column | fk_references |
|-----------|----------------|-----------|-----------|---------------|
| `Company` | `companies` | `company_id` | — | — |
| `Product` | `products` | `product_id` | `company_id` | `companies.company_id` |
| `Base Model` | `base_model_extensions` | `extension_id` | `base_model_id` | `base_models.base_model_id` |

`base_models` is structural only (no business fields). FK inventory:
- `base_model_extensions.base_model_id → base_models.base_model_id`
- `products.base_model_id → base_models.base_model_id` (JOIN anchor)
- `base_models.oem_company_id → companies.company_id`

**Current PLAIN columns** (do NOT create Field Registry entries for these):
`product_description`, `is_oem_product`, `website`,
`min_project_value_eur`, `max_project_value_eur`
Note: `export_capable` was removed entirely in Step 2 (was never matched, never in scope tabs).

**Step 2 reconciliation requirement:** Before building ②, every column in the
current Entity Model tab must be classified:
- Structural → ② with role PK/FK/ADMIN/PLAIN/DERIVED
- Business field → must exist in a scope tab's Field Registry

Any column without a classification = **Step 2 blocking error**.

**Column ordering:** ② defines column order per table. Generation emits in ② order.
Required for deterministic "identical output" DoD comparison.

### 3.3 Tab `③ Scope Registry` — Columns

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `scope_id` | Text | Unique. `Industry:Category:Subcategory` notation. `*` = global. | `Logistics:AGV:Forklift` |
| `parent_scope` | Text | Parent scope_id. Blank for root scopes. | `Logistics:AGV` |
| `display_name` | Text | Human-readable label | `Forklift AGV` |
| `tab_name` | Text | Excel tab holding this scope's fields. Blank = valid intermediate node. | `AGV_Forklift` |
| `legacy_values` | Text | Pipe-separated old values mapping to this scope_id. | `Forklift AGV\|VNA Forklift` |
| `active` | Boolean | `✓` if currently in use | `✓` |
| `classification_guide` | Long Text | See §3.4 | multi-line |
| `classification_keywords` | Text | Pipe-separated trigger words | `forklift\|reach truck` |

**Step 1 note:** ③ is created with all current scopes. The `*` row has blank
`tab_name` (valid intermediate node). Step 4 fills `tab_name = "Global"` when the
Global tab is created.

### 3.4 Classification Guide

`classification_guide` is per-scope free text teaching the LLM what a tender must
look like to belong to that scope. Used **exclusively** for scope detection — the
classification pass (currently Pass 4a; generalized in Step 7). No influence on
field extraction, matching rules, or scoring.

**Required content per entry:**
1. What this scope IS (positive definition)
2. What this scope is NOT (exclusion criteria, boundary with adjacent scopes)
3. Typical tender phrases
4. Boundary examples (edge cases with correct classification)

**Classification pass (Step 7 behavior):**
- LLM input: scope hierarchy from scope_registry.json, classification_guide +
  classification_keywords per active leaf scope, extracted tender text
- LLM output: a `scope_id` (leaf preferred; non-leaf permitted as partial
  classification if certainty is low) or `"OUT_OF_SCOPE"` if no scope matches
- `*` is reserved as the Global scope_id. It is **never** returned by the classifier.
  Out-of-scope tenders return `"OUT_OF_SCOPE"`.
- Non-leaf result: apply ancestor-scope fields only, no subcategory KO rules.
  The result UI must surface this state explicitly (banner + "not checked" field
  state). This requirement flows into the Step 7 sub-spec (OI-G).

**Until Step 7:** Classification guides are authored in ③ but not yet consumed by
the LLM pipeline. Pass 1 (`is_agv_amr`) and Pass 4a (`agv_type`) remain unchanged.

### 3.5 Field Tab Column Format (all scope tabs identical)

**Columns in every scope tab:**

| xlsx column | Required | Description |
|-------------|----------|-------------|
| `uuid` | Yes | Auto-assigned on first entry. Never changes. |
| `field_name` | Yes | Lowercase, underscores. Must equal db_column name (invariant §5.3). May repeat across industries — UUID disambiguates. |
| `entity` | Yes | `Company`, `Product`, or `Base Model` |
| `data_type` | Yes | Text / Integer / Float / Boolean / Multi-Select / Dropdown / Date / URL |
| `unit` | No | Physical unit (e.g. `kg`, `mm`, `°C`) |
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
| `llm_hint` | No | LLM extraction instruction. No numeric literals. |
| `user_description` | No | Clarification Dialog help text |
| `display_mode` | No | `always` / `on_value` / `never` |

**xlsx column → JSON key mapping** (where they differ):

| xlsx column | JSON key in fields.json | Consumed at |
|-------------|------------------------|-------------|
| `llm_hint` | `hint` | `app.py:168` (`_NUMERIC_KO_FIELD_HINTS`), Pass-4c prompt construction |
| `user_description` | `user_description` | `app.py:1133` (`/api/field-meta`) |
| All other columns | same name | — |

**Derived at generation time — NOT xlsx columns:**

| Key in fields.json | Derivation |
|--------------------|-----------|
| `scope` | From ③ Scope Registry: scope_id whose `tab_name` matches this field's tab |
| `tender_key` | Auto-derived as `"required_" + field_name` for all current supplier fields. No tender-only fields exist in the current schema. If added in future: `entity=Tender` must first be defined in ② with explicit tender_key rule. |

**`generate_all.py` asserts at generation time:**
- Every field with `level ≠ CONTEXT` has a non-blank `operator`
- Every field with `data_type ∈ {Dropdown, Multi-Select}` has non-blank `allowed_values`
- Every field with `level = SCORING` has non-blank `scoring_weight`
- No duplicate `field_name` along any resolution chain (§5.1)
- No two fields in the same scope share a `tender_key`
- Pairwise disjointness: `extensions_columns ∩ products_columns` = join keys only AND `extensions_columns ∩ companies_columns` = join keys only (three-way intersection is insufficient — it passes even when the two pairwise overlaps remain)

---

## 4. Generated Artifacts

### 4.1 `config/fields.json` — Unified Field Registry

**Key:** UUID.

**Normative key set:** Current fields.json keys, minus `sheet`, plus `scope`. All
other keys (`uuid`, `field_name`, `tender_key`, `entity`, `level`, `operator`,
`data_type`, `unit`, `allowed_values`, `scoring_weight`, `score_function`,
`threshold_a`, `threshold_b`, `value_if_null`, `plausibility_min`, `plausibility_max`,
`hint`, `user_description`, `display_mode`) are unchanged.

The sample below is illustrative and non-exhaustive:
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
      "scope_id": "*", "parent": null, "display_name": "Global",
      "tab_name": "Global", "legacy_values": [], "active": true
    },
    "Logistics:AGV:Forklift": {
      "scope_id": "Logistics:AGV:Forklift", "parent": "Logistics:AGV",
      "display_name": "Forklift AGV", "tab_name": "AGV_Forklift",
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

**Miss guard:** `prod.agv_type` not in `legacy_map` → supplier skipped with explicit
logged error (also surfaced as SSE warning, consistent with the non-leaf UI-surfacing
principle). Never silently passes. Additionally, `sync_airtable.py` runs a post-load
check: all distinct DB `agv_type` values must resolve via `legacy_map`; unknown values
abort sync with an explicit error.

### 4.3 `config/sqlite_schema.json`

Structural and PLAIN sections → from ② Structure (PK/FK/ADMIN/PLAIN roles).
Business column sections → from `fields.json` grouped by entity.
Consumer interface unchanged: `companies_columns`, `products_columns`,
`extensions_columns` lists remain. `sync_airtable.py` unchanged through Step 5.

### 4.4 Literal inventory — all strings to de-hardcode

| Location | Literal | Resolved in Step |
|----------|---------|-----------------|
| `generate_all.py:66` | `DATA_SHEETS = [...]` | Step 1 |
| `generate_all.py:243` | `sheet_map` dict (scoring weights per sheet) | Step 1 |
| `generate_all.py:739` | `build_extraction_template` sheet loop | Step 1 |
| `generate_all.py:891` | `basic_template` AGV literals | Step 7 |
| `generate_all.py:1283` | sheet name reference | Step 1 |
| `matching.py` | `_SHARED_SHEET` constant | Step 3 |
| `matching.py:441` | `prod.agv_type` string filter | Step 3 (via legacy_map) |
| `app.py:168` | `_NUMERIC_KO_FIELD_HINTS` uses `spec.sheet` | Step 3 |
| `app.py:657-671` | Pass 4a allowed-values validation uses sheet | Step 3 |
| `app.py:1054` | `/rematch` writes `required_agv_type` | Step 3 |
| `app.py:1064` | `/rematch` clarification-meta path uses `spec.sheet` | Step 3 |
| `app.py:1131-1142` | `/api/field-meta` exports `sheet` key + `shared_sheet_name` | Step 3 |
| `app.py` | `is_agv_amr` pass | Step 7 |
| `context_builder.py` | No `fields_by_sheet()`/`_SHARED_SHEET` hits — clean for Step 3. Contains `_FALLBACK_README` + inline AGV industry rules (VNA/Tugger/VDA5050 literals in `build_system_context()`) — Step 7 scope, tracked in OI-G. | Step 7 |
| `tests/unit/test_4c_direction_constants.py` | `_SHARED_SHEET` import | Step 3 |
| `tests/unit/test_rematch_endpoint.py` | `_SHARED_SHEET` import | Step 3 |
| `tests/unit/test_ap0_consistency.py` | `_SHARED_SHEET` import | Step 3 |
| Frontend JS | `.sheet` and `shared_sheet_name` usages | Step 3 |

---

## 5. Invariants

1. **UUID is the primary key** for every field. Never changes after first assignment.
2. **`field_name` may repeat across industries.** UUID disambiguates.
3. **`field_name == db_column` always.** No mapping, no alias. A rename requires a
   DB migration.
4. **No scope/industry names hardcoded in Python** after Step 7.
5. **`generate_all.py` is the sole writer** of all files under `config/`.
   Exception: `config/unit_semantics.json` is manually maintained
   (loaded by `matching.py:40` and `app.py:83`).
6. **Test suite green after every step.**
7. **Steps 1–5 are behavior-neutral** — match results identical (see §5.3).
8. **Step 6 has its own Golden Refresh** — the only step that intentionally changes
   matching behavior.

### 5.1 field_name uniqueness along a resolution chain

No two fields in the same resolution chain share a `field_name`. Sibling scopes may
share a `field_name` only if `entity`, `data_type`, and `unit` are all identical.
Violation → generation fails with explicit error.

### 5.2 NULL semantics in base_model_extensions

`base_model_extensions` is a wide table covering all industries. NULL = "unknown or
not applicable." Scope-irrelevant columns will always be NULL and are never evaluated
(scope-filtered field loading prevents it). Explicitly accepted design decision.

### 5.3 Definition of "identical output" (Steps 1–5 DoD)

"Identical" = per-supplier match results: `{disqualified, disqualified_by, score,
score_details}` for all 5 golden tenders. Excludes the field-meta API response
envelope (which changes in Step 3 when `sheet` → `scope`). The golden test fixtures
carry no `sheet` key and compare cleanly.

---

## 6. Runtime Architecture

### 6.1 Startup

```
load scope_registry.json  → _SCOPE_REGISTRY, _VALID_SCOPES, _LEGACY_MAP
load fields.json          → _FIELDS (all scopes, indexed by UUID)
build per-scope field sets → resolution_order per leaf scope
load sqlite_schema.json   → existing schema constants (unchanged)
load unit_semantics.json  → _SIGNED_UNITS (unchanged)
```

### 6.2 Scope Detection (until Step 7 — unchanged behavior)

Pass 1 (`is_agv_amr`) and Pass 4a (`agv_type`) unchanged. Scope resolved at runtime:
`_LEGACY_MAP[prod.agv_type]` → scope_id. Unknown value → logged error + SSE warning,
supplier skipped.

### 6.3 Scope Detection (Step 7 — new behavior)

Unified classification pass using scope_registry.json guides. Returns a scope_id
(leaf or non-leaf) or `"OUT_OF_SCOPE"`. Never `*`. Step 7 requires its own sub-spec
(OI-G).

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

`agv_type` continues as a normal registry field (entity=Product, level=KO, KO_IF_NEQ)
routed into `products`. Its matching semantics are NOT retired until Step 7. All other
matching logic, null rules, and scoring unchanged.

Extraction: `extraction_template.txt` uses scope-filtered fields. Context builder uses
`fields_by_scope(scope_id)`. Prompt structure, LLM call structure, and output parsing
unchanged.

---

## 7. Data Layer

### 7.1 SQLite tables (unchanged structure through Step 5)

```
companies              PK: company_id
  [structural: ② Structure (PK/FK/ADMIN/PLAIN)]
  [business: entity=Company fields from Global tab]

products               PK: product_id  FK→companies via company_id
  [structural: ② Structure]
  [business: entity=Product fields from all scope tabs — each field in its canonical table]
  agv_type             ← entity=Product registry field (level=KO, KO_IF_NEQ).
                          Generated into products via entity routing.
                          NOT a duplicate. Transitional until Step 7.

base_models            PK: base_model_id  FK→companies via oem_company_id
  [structural only: oem_link_public, last_updated — no business fields]

base_model_extensions  PK: extension_id  FK→base_models via base_model_id
  [ALL entity=Base Model business fields from ALL scope tabs]
```

### 7.2 The 10 denormalization duplicates (Step 5 targets)

Verified in `generate_all.py:501-520`. All 10 duplicate copies live in
`base_model_extensions`. Canonical home (entity column) holds the real data.

**`_company_in_ext`** (3 Company fields cloned into extensions):
`employee_count_range`, `hq_city`, `founding_year`

**`shared_in_product_columns` cloned into extensions** (7 fields whose canonical
home is `products` or `companies`, also emitted into extensions):
`certifications_generic`, `country`, `distribution_model`, `languages_spoken`,
`lead_time_weeks`, `reference_count`, `service_coverage`

**Removal rule:** Remove all 10 from `extensions_columns`. Do NOT touch
`products_columns` or `companies_columns` — those hold the canonical data.

**Expected delta:** `extensions_columns` −10; `products_columns` ±0;
`companies_columns` ±0.

Verified: all 10 extensions copies are currently empty in the live DB (canonical
sides hold the data: `companies.country` = 27 rows, `companies.hq_city` = 18 rows,
all extensions copies = 0). Pre-flight hard assert confirms this before removal
(see Step 5).

### 7.3 Airtable Sync

`sync_airtable.py` reads column lists from `sqlite_schema.json`. Unchanged through
Step 5. Step 5 exception: CSV re-export + DB rebuild mandatory (see §8.5).

---

## 8. Migration Steps

**Global invariant:** Test suite green after every step. Steps 1–5: match results
identical per §5.3. Step 6: intentional behavior change with own golden refresh.

---

### Step 1 — De-hardcode DATA_SHEETS

**What:** `generate_all.py` reads field-tab list from ③ `tab_name` column instead of
hardcoded `DATA_SHEETS`. All sheet-name string literals in `generate_all.py` at lines
66, 243, 739, 1283 replaced with dynamic lookups.

**AP0 change required:**
- Add `③ Scope Registry` tab with all current scopes and the Global row.
- Populate `tab_name` with **current** tab names verbatim (e.g. `"SHARED – All AGV Types"`,
  `"Forklift AGV"`). No renames at this step.
- Global row (`*`): `tab_name` = blank (valid intermediate node; Step 4 fills it).

**DoD:**
- `DATA_SHEETS` constant removed from `generate_all.py`
- ③ Scope Registry tab exists with 5 rows (4 current scopes + Global with blank tab_name)
- `generate_all.py` output byte-identical vs. before
- Non-blank `tab_name` absent from workbook → hard generation error (test by adding a dummy row)
- All tests green

---

### Step 2 — Structure Registry (replaces Entity Model)

**What:** Add `② Structure` tab with PK/FK/ADMIN/PLAIN/DERIVED columns and
entity-table mapping. `generate_all.py` reads structural + PLAIN sections from ②
instead of Entity Model. Entity Model tab marked documentation-only.

**Pre-implementation reconciliation (mandatory before building ②):**
Every column in the current Entity Model tab must be classified as structural (→ ②)
or business field (must exist in a scope tab). PLAIN columns listed in §3.2.
Unclassified column = blocking error.

**Column ordering:** ② defines column order per table; generation emits in ② order.

**DoD:**
- ② Structure fully populated and reconciliation reviewed
- `generate_all.py` no longer reads Entity Model tab
- `sqlite_schema.json` identical before and after (including column order)
- Entity Model tab annotated "DOCUMENTATION ONLY — not read by any script"
- All tests green

---

### Step 3 — `scope` in fields.json (replace `sheet`)

**What:** `generate_all.py` derives `scope` for each field from ③ and writes it to
`fields.json`. The `sheet` key is removed. `scope_registry.json` generated and loaded
at startup. `vehicle_types.json` continues to be generated (full supersession Step 7).

**All consumers updated** (see §4.4 for locations):
- `matching.py`: `_SHARED_SHEET` removed; field collection uses §6.4 pattern;
  `prod.agv_type` → `_LEGACY_MAP[prod.agv_type]` with miss guard
- `app.py:168`: `_NUMERIC_KO_FIELD_HINTS` uses `spec.scope` instead of `spec.sheet`
- `app.py:657-671`: Pass 4a validation uses scope-filtered `agv_type` field
- `app.py:1054`: `/rematch` unchanged (writes `required_agv_type` by field_name — ok)
- `app.py:1064`: `/rematch` clarification-meta path updated to use `spec.scope`
- `app.py:1131-1142`: `/api/field-meta` response: `sheet` → `scope`; `shared_sheet_name` removed
- `context_builder.py`: verified clean — no `fields_by_sheet()` calls
- `tests/unit/test_4c_direction_constants.py`: `_SHARED_SHEET` import removed
- Frontend JS: `.sheet` → `.scope`; `shared_sheet_name` usage removed

**DoD:**
- `sheet` key absent from `fields.json`
- `_SHARED_SHEET` constant absent from all Python files
- `scope_registry.json` generated and loaded at startup
- `/api/field-meta` response has `scope` key; no `sheet`; no `shared_sheet_name`
- Frontend JS uses `.scope`
- `legacy_map` miss guard active (logged error + SSE warning + supplier skipped)
- `sync_airtable.py` post-load agv_type validation active
- All tests green
- 5 golden tenders: match results identical (per §5.3)

---

### Step 4 — Tab Restructuring (Global tab + field movement)

**What:** Create `Global` tab in AP0 xlsx. Move `entity=Company` and `entity=Product`
fields from SHARED to Global. Rename physical tabs to target names and update ③ rows.
**This step is purely AP0 content rearrangement. No Python changes.**

**Move list** (derived mechanically: all fields.json entries with `entity ∈ {Company,
Product}` currently in the SHARED tab, **excluding `agv_type`**):

Entity=Company → `Global` tab:
`country`, `employee_count_range`, `founding_year`, `hq_city`,
`certifications_generic`, `languages_spoken`

Entity=Product → `Global` tab:
`reference_count`, `lead_time_weeks`, `distribution_model`, `service_coverage`

**`agv_type` stays in AGV_Shared** (entity=Product, transitional until Step 7).
It is AGV-specific — moving it to Global (`*`) would inject an AGV KO field into
every future industry's resolution chain.

**PLAIN/structural columns** (`product_name`, `product_description`, `active`,
`website`) are NOT registry fields. Do NOT create scope-tab entries
for them. They belong in ② Structure.
Note: `export_capable` was removed in Step 2.

**Tab rename actions:**
- `SHARED – All AGV Types` → rename to `AGV_Shared`; update ③ row `tab_name`
- `Forklift AGV` → rename to `AGV_Forklift`; update ③ row
- `Tugger AGV` → rename to `AGV_Tugger`; update ③ row
- `Mobile AMR` → rename to `AGV_AMR`; update ③ row
- Create `Global` tab; fill ③ `*` row `tab_name = "Global"`

**DoD:**
- `Global` tab exists with all entity=Company + entity=Product fields (except `agv_type`)
- `AGV_Shared` tab contains only entity=Base Model fields + `agv_type`
- ③ `*` row has `tab_name = "Global"`
- Moved fields have `scope = "*"` in generated `fields.json`
- `agv_type` has `scope = "Logistics:AGV"` in generated `fields.json`
- All tests green
- 5 golden tenders: match results identical

---

### Step 5 — Remove Denormalization

**What:** Remove the 10 duplicate columns (§7.2) from `extensions_columns` in
`sqlite_schema.json`. Remove `_company_in_ext` and `shared_in_product_columns` logic
from `generate_all.py`. Add cross-table disjointness assert at generation time.

**Pre-flight hard assert (mandatory, runs before any schema change):**
For each of the 10 target columns, the migration script checks:
```sql
SELECT COUNT(*) FROM base_model_extensions WHERE <col> IS NOT NULL AND <col> != ''
```
Must be 0. If any column has non-null, non-empty extensions data that does not equal
the canonical side → **abort with a reconciliation report**. Do not proceed until
resolved. (Today's live DB passes: all 10 extensions copies are empty.)

**Post-Step-5 mandatory operations:**
1. Re-export all tables from Airtable as CSV
2. DB rebuild: `python3 sync_airtable.py --local`

**DoD:**
- `_company_in_ext` and `shared_in_product_columns` absent from `generate_all.py`
- `extensions_columns` delta: −10 (document exact pre/post counts)
- `products_columns` and `companies_columns`: unchanged
- Cross-table disjointness assert active at generation time
- Pre-flight assert confirmed clean before column drop
- CSV re-export + DB rebuild completed
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
| `infrastructure_required` | Rename → `infrastructure_free`; Boolean inverted; operator stays `KO_BOOL_REQUIRED` | **YES — 3-front migration** |
| `load_type` | `allowed_values` updated | **YES — value mapping** |
| `integration_capability` | SCORING → COND_KO; `KO_SUBSET`; new `allowed_values` | **YES — value mapping** |

**For `infrastructure_free` — mandatory 3-front migration order:**

1. Apply rename and Boolean inversion **in Airtable** (rename field `infrastructure_required`
   → `infrastructure_free`, invert all values: True↔False, nulls stay null)
2. Apply rename + operator change in **AP0 xlsx**
3. Run `python3 scripts/generate_all.py` (schema now contains `infrastructure_free`,
   not `infrastructure_required`)
4. Full CSV re-export from Airtable
5. Run `python3 sync_airtable.py --local` — DB rebuild against updated schema

**Why this order:** Steps 4+5 must follow Step 3 so that `sync_airtable.py` reads
from a schema that already contains `infrastructure_free`. Reading a CSV with the
new column name against an old schema silently drops the column.

**Idempotency + null-preservation (A1 — mandatory):** Implement as a new Airtable
formula field:
```
IF(infrastructure_required = BLANK(), BLANK(), NOT(infrastructure_required))
```
Do NOT use `NOT(old)` alone — `NOT(BLANK())` evaluates to TRUE, which would promote
every supplier with unknown `infrastructure_required` to `infrastructure_free = TRUE`
(Blank ≠ Zero violation on a KO-relevant field).
Migration assert required before deleting the old field:
`blank-count(infrastructure_required) == blank-count(infrastructure_free)`.
After verification, convert the formula field to a static field, then delete
`infrastructure_required`. A naive in-place inversion is NOT idempotent.

**For `load_type` and `integration_capability`:** Same 3-front sequence (Airtable
value mapping → AP0 change → `generate_all.py` → CSV re-export → `sync --local`).
Scripts must be idempotent. Verify on dev DB before production.

**DoD:**
- All content changes applied in AP0 xlsx
- `generate_all.py` run; `config/` regenerated
- 3-front migration complete for all three fields (Airtable → AP0 → config → CSV → DB)
- DoD spot checks for `infrastructure_free`: old column absent from rebuilt DB;
  ≥5 suppliers spot-checked for correct inversion; NULL count ≤ pre-migration baseline
- All tests updated for new matching behavior
- New golden baseline committed with documented expected changes per tender

---

### Step 7 — Generalize Scope Detection

Replaces hardcoded `is_agv_amr` + Pass 4a with unified classification pass using
`scope_registry.json` classification guides. First activation of the
`classification_guide` content from ③.

**Pre-conditions:** Steps 1–6 complete and stable.
**This step requires its own sub-spec before implementation** (OI-G).

Sub-spec must include: classification pass prompt design, hierarchy traversal logic,
`"OUT_OF_SCOPE"` handling, partial-classification UI surfacing (banner + "not checked"
field state), `vehicle_types.json` retirement plan, `agv_type` matching semantics
retirement and replacement disqualification mechanism.

---

## 9. Open Items (out of scope for this migration)

| ID | Description |
|----|-------------|
| OI-A | CONTEXT fields display section in result card UI |
| OI-B | Ordinal operator (`KO_IF_ORD`) for ordered categorical fields |
| OI-C | `Other` in load_type → triggers Request flow |
| OI-D | Country restructuring: HQ_Country + HQ_City + Offices + service_reach |
| OI-E | `min/max_project_value_eur` — confirm as PLAIN or promote to CONTEXT field |
| OI-F | `integration_capability` LLM extraction hint (mapping "SAP WM" → WMS) |
| OI-G | Step 7 sub-spec: classification pass design, non-leaf UI surfacing, vehicle_types.json retirement, agv_type matching retirement, `context_builder.py` `_FALLBACK_README` + inline critical-rules block migration to generated per-scope prompt config |
| OI-H | Admin UI consideration: evaluate when second industry is added |

---

## 10. Acceptance Criteria (Steps 1–6 complete)

- [ ] `DATA_SHEETS` constant absent from all Python files
- [ ] `_SHARED_SHEET` constant absent from all Python files
- [ ] Entity Model tab marked documentation-only
- [ ] `fields.json`: every entry has `scope` key; no `sheet` key
- [ ] `scope_registry.json` generated and loaded at startup
- [ ] Non-blank `tab_name` absent from workbook → hard generation error (tested)
- [ ] `extensions_columns ∩ products_columns ∩ companies_columns` = join keys only (generation assert active)
- [ ] `agv_type` has `scope = "Logistics:AGV"` (not `"*"`)
- [ ] No PLAIN/structural column has a Field Registry entry
- [ ] `legacy_map` miss guard active (logged error + SSE warning)
- [ ] `sync_airtable.py` validates all `agv_type` values against `legacy_map` at load
- [ ] Adding a new scope (new ③ row + new tab): zero Python changes needed
- [ ] `/api/field-meta` response has `scope` key; no `sheet` key; no `shared_sheet_name`
- [ ] `infrastructure_free` 3-front migration complete and spot-checked
- [ ] `load_type` + `integration_capability` value migrations complete
- [ ] Test suite ≥ 204 passing
- [ ] Steps 1–5: 5 golden tenders match results identical to pre-migration baseline
- [ ] Step 6: new golden baseline committed with documented expected delta
- [ ] `sync_airtable.py --local` completes without error after each step

---

*End of Spec v0.4*
