# haystacked Platform — Architecture

> Version: based on AP0 v0.10 — UFR Sprint (Steps 1–6)
> Last updated: 2026-07-10 — scope-registry architecture, 226 tests

---

## 1. Purpose

haystacked is a B2B AGV tender-matching platform. Buyers upload a tender PDF; the system extracts technical requirements using a local LLM, then scores and ranks all supplier products in the database against those requirements using a pure rule engine. Results are streamed to the browser in real time via SSE.

---

## 2. High-Level Architecture

```
PDF (or JSON replay)
        |
        v
  pdfplumber text extraction
        |
        v
  Ollama (qwen2.5:7b) — up to 16 LLM calls
  +-------------------------------------------------+
  | Pass 1:  basic_extraction (always)              |
  | Pass 2:  contact_fallback (conditional)         |
  | Pass 3:  nace_classification (always)           |
  | Pass 4a: vehicle_type (AGV only)                |
  | Pass 4b: agv_extraction (AGV only)              |
  | Pass 4c: per_field_extraction x N (AGV only)   |
  +-------------------------------------------------+
        |
        v
  enforce_source_spans() — 3-layer hallucination guard (src/json_repair.py)
        |
        v
  validate_tender_values() — AP0 allowed_values filter (src/matching.py)
        |
        v
  validate_agv_criteria() — plausibility + unit conversion (app.py)
        |
        v
  field_text_fallbacks — regex overrides (from vehicle_types.json)
        |
        v
  match_suppliers_new() — pure rule engine against SQLite (src/matching.py)
        |
        v
  SSE stream -> browser
```

Typical AGV tender: 13-16 LLM calls, approximately 330 seconds wall time.

---

## 3. Single Source of Truth: AP0 xlsx

`Spec/haystacked_AP0_field_spec_v0_10.xlsx` is the single authoritative source for all field definitions, matching rules, scoring weights, vehicle types, and LLM extraction hints.

**Never edit generated files directly.** Always edit the AP0 xlsx, then run:

```bash
python3 scripts/generate_all.py
```

`scripts/generate_all.py` also reads `Spec/haystacked_platform_config.xlsx` for cross-industry data (NACE codes, platform scope, unit conversion rules).

### 3.1 AP0 xlsx Tab Structure

| Tab | Machine-readable | Purpose |
|-----|-----------------|---------|
| `Global` | Yes | Fields scoped to all industries (`scope: "*"`) |
| `AGV_Shared` | Yes | Fields shared across all AGV vehicle types (`scope: "Logistics:AGV"`) |
| `AGV_Forklift` | Yes | Fields specific to Forklift AGVs (`scope: "Logistics:AGV:Forklift"`) |
| `AGV_Tugger` | Yes | Fields specific to Tugger AGVs (`scope: "Logistics:AGV:Tugger"`) |
| `AGV_AMR` | Yes | Fields specific to Mobile AMRs (`scope: "Logistics:AGV:AMR"`) |
| `③ Scope Registry` | Yes | Scope hierarchy: scope_id, parent_scope, tab_name, active |
| `② Structure` | Yes | SQLite structural columns (PK/FK/ADMIN) per table — not business fields |
| `Vehicle Types` | Yes | LLM output -> canonical type map, VNA detection, text overrides, fallback keywords |
| `Field Fallbacks` | Yes | Regex-driven field value overrides |
| `Entity Model` | **No** | Documentation only — not read by generate_all.py |

### 3.2 Platform Config Tabs (haystacked_platform_config.xlsx)

| Tab | Purpose |
|-----|---------|
| `NACE Codes` | NACE classification list for scope determination |
| `Platform Scope` | In-scope / out-of-scope prose for NACE prompt |
| `Basic Extraction Schema` | Non-AGV fields extracted in Pass 1 (buyer, contact, etc.) |
| `Unit Conversions` | Cross-industry unit conversion rules (e.g. m <-> mm) |

### 3.3 Generated Config Files (never edit manually)

| File | Consumer(s) |
|------|------------|
| `config/fields.json` | `src/field_spec.py`, `app.py`, `src/matching.py`, `src/data_loader.py` |
| `src/field_spec.py` | All modules that need field metadata |
| `config/vehicle_types.json` | `app.py`, `src/matching.py`, `src/context_builder.py` |
| `config/scope_registry.json` | `app.py`, `src/matching.py` |
| `config/nace_codes.json` | `app.py` (NACE prompt) |
| `config/sqlite_schema.json` | `sync_airtable.py`, `src/data_loader.py` |
| `config/plausibility.json` | `app.py` (validate_agv_criteria) |
| `config/prompts/*.txt` | `app.py` (all LLM calls) |
| `config/ap0_checksum.txt` | `app.py` (startup auto-regen trigger) |

### 3.4 Manually Maintained Config Files

| File | Purpose | Notes |
|------|---------|-------|
| `config/unit_semantics.json` | Units with signed domain (°C, °F) | NOT generated — edit manually when adding signed-domain units |
| `config/industry_readme.md` | Domain knowledge for AGV system prompt | Synced from `Spec/haystacked_industry_readme.md` by generate_all.py |

---

## 4. Scope Registry System

### 4.1 Scope Tree

The scope tree defines which AP0 tabs contain fields relevant to each vehicle type:

```
* (Global tab)
+-- Logistics:AGV (AGV_Shared tab)
    +-- Logistics:AGV:Forklift (AGV_Forklift tab)
    +-- Logistics:AGV:Tugger   (AGV_Tugger tab)
    +-- Logistics:AGV:AMR      (AGV_AMR tab)
```

### 4.2 scope_registry.json Contents

Three top-level keys:

**scopes** — metadata per scope node:
```json
{
  "*":                    {"scope_id": "*",                   "parent": null, "tab_name": "Global"},
  "Logistics:AGV":        {"scope_id": "Logistics:AGV",       "parent": "*",  "tab_name": "AGV_Shared"},
  "Logistics:AGV:Forklift":{"scope_id": "Logistics:AGV:Forklift","parent": "Logistics:AGV","tab_name": "AGV_Forklift"}
}
```

**resolution_order** — for each leaf scope, the ordered chain of scope_ids from root to leaf:
```json
{
  "Logistics:AGV:Forklift": ["*", "Logistics:AGV", "Logistics:AGV:Forklift"],
  "Logistics:AGV:Tugger":   ["*", "Logistics:AGV", "Logistics:AGV:Tugger"],
  "Logistics:AGV:AMR":      ["*", "Logistics:AGV", "Logistics:AGV:AMR"]
}
```

**legacy_map** — canonical VT name -> leaf scope_id (the bridge between the LLM world and the scope world):
```json
{
  "Forklift AGV": "Logistics:AGV:Forklift",
  "Tugger AGV":   "Logistics:AGV:Tugger",
  "Mobile AMR":   "Logistics:AGV:AMR"
}
```

### 4.3 How Resolution Is Used

**Matching engine (src/matching.py):**

```python
vt_scope   = _LEGACY_MAP.get(prod.agv_type)
# "Forklift AGV" -> "Logistics:AGV:Forklift"

resolution = _scope_registry["resolution_order"].get(vt_scope, [])
# ["*", "Logistics:AGV", "Logistics:AGV:Forklift"]

relevant   = [f for f in _fields.values() if f.scope in resolution]
# Only Global + AGV_Shared + AGV_Forklift fields are evaluated
```

This implements OI-47: a Forklift supplier is never evaluated against Tugger or AMR-specific fields.

**Pass 4c scope filter (app.py):**

```python
_leaf_scope = _LEGACY_MAP.get(canonical_agv_type, "")
_4c_scopes  = frozenset(_RESOLUTION_ORDER.get(_leaf_scope, [_SHARED_SCOPE, _leaf_scope]))
_4c_fields  = {
    k: v for k, v in _NUMERIC_KO_FIELD_HINTS.items()
    if v["scope"] in _4c_scopes
}
```

Forklift-specific numeric KO fields (e.g. `lifting_height_mm`) are not sent to Pass 4c for a Tugger tender.

### 4.4 Legacy Map Startup Assertion

`matching.py` asserts at startup that every canonical VT name present in `vt_map` has a corresponding entry in `legacy_map`. This fails fast if a new vehicle type is added to the Vehicle Types tab without a corresponding scope entry in the Scope Registry tab.

---

## 5. Data Layer

### 5.1 Airtable Sync (sync_airtable.py)

Pulls four Airtable tables, writes CSV snapshots to `data/raw/`, imports into `data/haystacked.db` (SQLite). Idempotent — safe to run multiple times.

- **Live mode** (default): requires `AIRTABLE_TOKEN` and `AIRTABLE_BASE_ID` in `.env`
- **Local mode** (`--local` flag): re-imports from existing CSVs in `data/raw/` — no Airtable credentials needed

The SQLite schema comes entirely from `config/sqlite_schema.json` (generated from AP0). No table structure is hardcoded in sync_airtable.py.

### 5.2 SQLite Schema

Four tables:

- `companies` — structural: company_id (PK), company_name; business: country, languages_spoken, certifications_generic, etc.
- `products` — structural: product_id (PK), company_id (FK), base_model_id (FK), product_name, agv_type, active; business: reference_count, lead_time_weeks, service_coverage, etc.
- `base_models` — structural: base_model_id (PK), base_model_name
- `base_model_extensions` — structural: extension_id (PK), base_model_id (FK); business: ALL KO/COND_KO/SCORING fields from scope tabs (payload, aisle width, lifting height, vna_capable, navigation_type, etc.)

Structural columns come from the `② Structure` tab. Business field columns are appended per entity from the scope data sheets. A startup assertion in `data_loader.py` (OI-56) verifies no Base Model field name collides with explicitly-selected Product/Company columns.

### 5.3 Data Loader (src/data_loader.py)

`load_suppliers()` executes a 3-way JOIN:

```sql
SELECT p.product_id, p.company_id, ..., c.company_name, c.country, ..., bme.*
FROM products p
JOIN companies c ON p.company_id = c.company_id
JOIN base_model_extensions bme ON p.base_model_id = bme.base_model_id
WHERE p.active = 1 AND p.product_id IS NOT NULL
```

For each row, builds a `SupplierRecord(product, values)` where:
- `product` is a `Product` dataclass with structural fields parsed and type-coerced
- `values` is `dict[uuid -> FieldValue]` — `_build_field_values()` iterates all FieldSpec entries from `fields.json` and routes each field to the correct source dict (Product, Company, or Base Model) based on `spec.entity`

Multi-select fields (pipe-separated in SQLite) are split by `_parse_multiselect()`. None is used for all unknown values — never 0, False, or [].

### 5.4 Data Models (src/models.py)

| Class | Purpose |
|-------|---------|
| `Company` | Company-level attributes |
| `Product` | Product-level attributes + joined company columns |
| `FieldValue` | One capability value self-described by its FieldSpec; value is None if unknown |
| `ExtractionValue` | One LLM-extracted value with optional source quote; spec can be None for orphaned UUIDs |
| `TenderRun` | Complete record of one pipeline run: uuid-keyed values dict + basic_info |
| `SupplierRecord` | product + dict[uuid -> FieldValue] covering all AP0 fields |

**Blank != Zero invariant:** `None` means unknown, never absent capability. A supplier with `None` for `max_payload_kg` is not disqualified under KO_IF_LT — it receives a null penalty instead (LL-06).

---

## 6. LLM Pass Topology

All LLM calls go to Ollama at `http://localhost:11434` using model `qwen2.5:7b`. Temperature: 0.0. Context window: 32,768 tokens. Maximum PDF input: 50,000 chars.

### Pass 1 — Basic Extraction (always)

**Prompt:** `basic_system.txt` + `basic_template.txt`
**Placeholder:** `{text}` — full document (up to 50,000 chars)
**Extracts:** buyer, project_name, contact_name/email/phone, deadline, tender_date, buyer_industry, tender_category, is_agv_amr, summary, missing_info

After parsing: if `is_agv_amr` is False/missing but AGV keywords appear in the first 5,000 chars (`agv_detection_keywords` from vehicle_types.json), `is_agv_amr` is forced to True.

### Pass 2 — Contact Fallback (conditional)

**Runs only if:** all contact fields (contact_name, contact_email, contact_phone) are missing AND `len(text) > 6000`
**Prompt:** `contact_system.txt` + `contact_template.txt`
**Placeholder:** `{text}` — last 4,000 chars of document
**Extracts:** contact_name, contact_email, contact_phone, deadline, tender_date (only non-null values merged into Pass 1 result)

### Pass 3 — NACE Classification (always)

**Prompt:** `nace_system.txt` + `nace_template.txt`
**Placeholders:** `{tender_category}`, `{buyer_industry}`, `{category_list}` (from nace_codes.json)
**Extracts:** nace_tender, nace_tender_name, in_scope, priority, confidence

On failure, `in_scope` defaults to True (results are not hidden on classification error).

### Pass 4a — Vehicle Type (AGV only)

**Prompt:** `vehicle_type_template.txt` (generated from Vehicle Types tab)
**Placeholder:** `{text}`
**Extracts:** required_agv_type, required_vna_capable
**Up to 3 attempts** (AP0 correction loop for required_agv_type only; other fields excluded from 4a correction)

After Pass 4a:
- LLM output string -> `_VT_MAP_CFG` -> canonical_agv_type ("Forklift AGV" / "Tugger AGV" / "Mobile AMR")
- `is_vna_subtype` = True if raw LLM output is in `_VNA_CFG` OR `required_vna_capable` is truthy
- Text override pass: `_VT_OVERRIDES` regexes applied against full PDF text; first match overrides both `canonical_agv_type` and `is_vna_subtype`
- `_4c_fields` computed now (scope filter applied for the detected VT)

### Pass 4b — AGV Batch Extraction (AGV only)

**Prompt:** VT-specific template from `vt_prompt_map` in vehicle_types.json:
- `extraction_template_agv_forklift.txt` for Forklift AGV
- `extraction_template_agv_tugger.txt` for Tugger AGV
- `extraction_template_agv_amr.txt` for Mobile AMR
- `extraction_template.txt` as fallback (combined, all scopes)

**Placeholders:** `{text}`, `{vehicle_type}`, `{vna_context}`
**Up to 3 attempts** (AP0 correction loop; skips fields in `_4A_SKIP` already validated in 4a)

Each numeric KO field in the template has a companion `<field>_source` key. The LLM must copy the verbatim sentence from the document that states the value.

### Pass 4c — Per-Field Extraction (AGV, numeric KO fields)

Runs after 4b, before source-span enforcement. One focused LLM call per numeric KO field scoped to the detected vehicle type.

**Scope filter:** only fields from `_NUMERIC_KO_FIELD_HINTS` whose `scope` is in `_4c_scopes` (resolution chain for detected VT, including Global "*")

**Prompt is constructed inline** — no separate prompt file. Contains: vehicle type, field name, field hint (definition only, NULL RULE prose stripped), extraction direction from `_4C_EXTRACTION_DIRECTION`, and the full document.

**4c non-null result:** overrides 4b value for that field.
**4c null result (abstention):** field added to `_4c_abstained` set; used in Layer 2 of source-span guard.
**Typical count:** approximately 8 calls for Forklift AGV.

---

## 7. Source-Span Hallucination Guard

Implemented in `src/json_repair.py::enforce_source_spans()`. Runs after Pass 4c on all fields in `_NUMERIC_KO_TENDER_KEYS`. For each field with a non-null value, three layers run in order — first match nulls the value and stops:

**Layer 1 (always):** `<field>_source` absent or empty -> null the value. No citation = inference = rejected.

**Layer 0 (always):** Source present but not grounded in the real PDF text -> null. Catches a fabricated value+quote pair. Implemented by `source_is_grounded(value, source, document)`, which requires:
1. The value's digit-string (with locale and x1000/÷1000 scale tolerance) must occur somewhere in the real document
2. At least one distinctive content word from the source quote must appear within 80 chars of an anchor occurrence in the document

**Layer 2 (4c abstentions only):** 4c returned null AND `source_confirms_value(value, source)` returns False for the 4b source -> null. Catches cases where 4b extracted a value but 4c disagreed (abstained) and the 4b source quote does not numerically match the 4b value.

**Invariants:**
- Both `source_confirms_value()` and `source_is_grounded()` are completely field-agnostic. They contain no field names, no AP0 allowed-values lists, no domain knowledge.
- 4c abstention (null) does not unconditionally override 4b — only Layer 2 can do that, and it requires `source_confirms_value()` to also fail.
- Zero values always pass all three layers (deliberate zero is not an inference hallucination).

---

## 8. Post-LLM Validation

### 8.1 AP0 Allowed-Values Filter

`validate_tender_values()` in `src/matching.py`. Rejects extracted values for Dropdown/Multi-Select fields not in the AP0 `allowed_values` list (case-insensitive substring match). Also splits slash-compound strings ("REST / OPC UA" -> ["REST", "OPC UA"]) before checking. Fields not in allowed values are set to None. Fields in `_AP0_SKIP_VALIDATION` (required_vna_capable, required_outdoor_capable) are excluded — they are coerced separately.

### 8.2 Plausibility Filter

`validate_agv_criteria()` in `app.py`. Reads ranges from `config/plausibility.json`. For each numeric field:
- If value exceeds the unit-conversion threshold, auto-convert (e.g. 12000 mm -> 12 m for lifting_height_mm)
- If value is outside [min, max] after conversion, set to None

### 8.3 Field Text Fallbacks

Regex-based overrides from `vehicle_types.json["field_text_fallbacks"]` applied against the full PDF text after all other validation. Each rule specifies a tender_key, a regex, a fallback value (must be an AP0 allowed value), and an `only_if_null` flag.

---

## 9. Matching Engine (src/matching.py)

Pure rule engine. All rules come from `config/fields.json`. No domain knowledge hardcoded.

### 9.1 Scope Filtering (OI-47)

Before evaluating any field, the matcher resolves which fields are relevant for the supplier's vehicle type using the resolution chain from `scope_registry.json`. A Forklift supplier is never evaluated against AMR-specific fields.

### 9.2 Operators

| Operator | Semantics | Null behavior |
|----------|-----------|---------------|
| `KO_IF_LT` | K.O. if supplier value < tender value | None on either side -> no K.O. |
| `KO_IF_GT` | K.O. if supplier value > tender value | None on either side -> no K.O. |
| `KO_IF_NEQ` | K.O. if supplier value != tender value | None on either side -> no K.O. |
| `KO_BOOL_REQUIRED` | K.O. if tender=required AND supplier=False | None supplier -> no K.O. |
| `KO_BOOL_EXCLUSIVE` | Bidirectional: required->must be True; not_required->must NOT be True | None supplier -> no K.O. (LL-06) |
| `KO_SUBSET` | K.O. if no overlap (substring matching) between tender list and supplier list | Empty on either side -> no K.O. |

### 9.3 Null Rule (LL-06)

`None` on either side never triggers a hard K.O. for numeric or categorical operators.

For `KO_IF_LT`: tender value of 0 is treated as "no effective requirement" unless the field unit is in `_SIGNED_UNITS` (°C, °F from `unit_semantics.json`), where zero is a real constraint.

**Null KO penalty (15 pts):** When a tender specifies a numeric KO requirement but the supplier has no data for that field, a -15 pt penalty is applied instead of disqualification. This ranks confirmed suppliers above unverified ones. Defined by `NULL_KO_PENALTY = 15` in `src/matching.py`.

### 9.4 Matching Flow per Supplier

1. Resolve `relevant` fields for supplier's VT (scope filter)
2. Evaluate all KO fields: first hard K.O. -> disqualified=True, stop immediately
3. Evaluate all COND_KO fields: failures accumulate but do not disqualify
4. If not disqualified: apply null KO penalty for each numeric KO field with active tender requirement but None supplier value
5. Track `null_gap_fields` (KO+COND_KO fields: active tender requirement, no supplier data)
6. Track `null_pass_fields` (KO+COND_KO fields: no tender requirement — trivially passed)
7. Evaluate SCORING fields: add points per `score_function`

### 9.5 Scoring Functions

| Function | Semantics |
|----------|-----------|
| `bool` | Full points if supplier value is True |
| `bool_cond` | Full points if tender requires it AND supplier has it; partial points otherwise |
| `proportional` | Points scale linearly from 0 to max (capped at threshold_a) |
| `nonempty` | Full points if supplier value is non-empty/non-null |
| `threshold_lower` | Full points if value <= threshold_a |
| `threshold_upper` | Full points if value >= threshold_a; half points if value >= threshold_b |
| `tiered_lower` | Full points if value <= threshold_a; half if <= threshold_b; else 0 |
| `tiered_upper` | Full points if value >= threshold_a; half if >= threshold_b; else 0 |

### 9.6 VNA Logic

VNA detection is two-layer:
- **Layer 1 (LLM):** Pass 4a returns `required_vna_capable=true`; raw LLM output matches a value in `_VNA_CFG`
- **Layer 2 (text):** `_VT_OVERRIDES` regexes applied to PDF text (e.g. "schmalgangstapler" -> VNA=True)

VNA -> matching conversion:
```python
new_req["required_vna_capable"] = (
    "required"     if is_vna_subtype else
    "not_required" if canonical_agv_type in _VNA_APPLICABLE else
    None
)
```

`_VNA_APPLICABLE = ["Forklift AGV"]` — only Forklifts participate in the VNA gate. Tugger/AMR tenders set `required_vna_capable=None` (no gate).

`KO_BOOL_EXCLUSIVE` on `vna_capable`:
- Tender VNA=required -> supplier must have vna_capable=True (else K.O.)
- Tender VNA=not_required -> supplier must have vna_capable=False (VNA equipment unsuitable)
- Tender VNA=None -> no gate applied (LL-06)

### 9.7 infrastructure_free Semantics

`infrastructure_free` is a boolean:
- **True** = vehicle operates without fixed infrastructure (SLAM/contour navigation, no tape/magnets/QR codes)
- **False** = vehicle requires fixed infrastructure

This replaced the former `infrastructure_required` field. Semantics are inverted from the old field name.

---

## 10. Module Map

| Module | Responsibility |
|--------|---------------|
| `app.py` | FastAPI entry; startup constants and assertions; all LLM pass orchestration; SSE streaming; /analyze, /match, /rematch endpoints |
| `src/matching.py` | Rule engine: operators, TenderRequirements, Matcher, MatchResult, validate_tender_values, null penalty |
| `src/field_spec.py` | Generated FieldSpec dataclass; load_fields(), fields_by_tender_key(), fields_by_field_name() |
| `src/data_loader.py` | 3-way JOIN; load_suppliers() -> list[SupplierRecord]; type coercion by FieldSpec |
| `src/models.py` | Dataclasses: Company, Product, FieldValue, ExtractionValue, TenderRun, SupplierRecord |
| `src/json_repair.py` | repair_and_parse() (5-stage LLM JSON repair); enforce_source_spans() (3-layer guard); source_confirms_value(); source_is_grounded() |
| `src/context_builder.py` | build_system_context() (industry README + KO field descriptions); agv_type_keyword_fallback() |
| `src/tender_store.py` | SQLite persistence of TenderRun records; build_tender_run(), persist_tender_run() |
| `scripts/generate_all.py` | AP0 pipeline: reads xlsx files, writes all config, generates prompt templates, writes field_spec.py, writes scope_registry.json |
| `sync_airtable.py` | Airtable -> CSV -> SQLite sync; schema-driven from sqlite_schema.json |

---

## 11. API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Serve frontend (index.html) |
| `/analyze` | POST | Upload PDF or JSON replay; returns SSE stream |
| `/match` | POST | Direct matching from structured UUID-keyed JSON |
| `/rematch` | POST | Re-run matching with user overrides against cached extraction |
| `/db-status` | GET | Supplier count + DB availability |

### SSE Event Types (from /analyze)

| Event | Payload |
|-------|---------|
| `step` | `{id, status, message, done?, total?}` — progress update |
| `log` | `{message}` — diagnostic info |
| `result` | Full result dict (extraction + match results) |
| `error` | `{message}` — fatal error |
| `warning` | `{field, message}` — non-fatal AP0 violation |

---

## 12. Startup Sequence

```
app.py imported
  -> _check_and_regen(): MD5 checksum of AP0 xlsx; auto-run generate_all.py if changed
  -> init_db() (tender_store.py — creates TenderRun persistence table)
  -> load_suppliers() -> _SUPPLIERS cached at module level
  -> Load all config into module-level constants
  -> Startup assertions (fail-fast if config is broken):
       _LEGACY_MAP non-empty
       _SHARED_SCOPE found (exactly 1 child of "*")
       vt_map values are subset of legacy_map keys
       _NUMERIC_KO_TENDER_KEYS non-empty
       _NUMERIC_KO_FIELD_HINTS non-empty
       _4C_EXTRACTION_DIRECTION non-empty
       Plausibility conversion factors present for lifting_height_mm, min_aisle_width_mm
       Allowed_values consistency across multi-VT tender_keys
       _SIGNED_UNITS not None
```

### start.sh

1. Check if Ollama is running; start it if not
2. Check if `qwen2.5:7b` model is available; pull it if not
3. Launch FastAPI via uvicorn on port 8000 with `--reload-include "*.json"` (config changes trigger reload)

---

## 13. Test Coverage

226 tests (all unit). Run with `pytest tests/`.

| File | Coverage area |
|------|--------------|
| `test_matching_logic.py` | KO operators, null rule, scoring functions, VNA gate, null penalty, COND_KO |
| `test_source_span_enforcement.py` | L1/L0/L2 guard: absent source, ungrounded source, 4c abstention paths |
| `test_source_confirms_value.py` | Locale handling (EN), unit-scale tolerance, zero-pass rule |
| `test_source_confirms_value_german.py` | DE locale number formats |
| `test_source_is_grounded.py` | Anchor + co-location logic, fabricated quote rejection |
| `test_validate_tender_values.py` | AP0 allowed-values filter, slash-splitting, multi-value, None passthrough |
| `test_find_invalid_ap0_fields.py` | _find_invalid_ap0_fields() used in AP0 correction loop |
| `test_4c_direction_constants.py` | _4C_EXTRACTION_DIRECTION constant derivation from fields.json |
| `test_ap0_consistency.py` | fields.json: allowed_values consistency across multi-VT scopes |
| `test_data_loader.py` | load_suppliers(), type coercion, None handling, entity routing |
| `test_uuid_keying.py` | _criteria_to_uuid_keyed(), TenderRequirements.from_dict() |
| `test_rematch_endpoint.py` | /rematch VT change, field clearing, None handling, unit conversion |
| `test_extraction_nulls.py` | Source-span guard: null propagation end-to-end |
| `test_agv_keyword_fallback.py` | agv_type_keyword_fallback() keyword scoring |
| `test_json_repair_parser.py` | repair_and_parse() all 5 stages |
| `test_golden_extraction.py` | Golden run regression against stored tender fixtures |
| `test_tender_store.py` | TenderRun persistence and retrieval |

---

## 14. Open Items

Key open items tracked in project memory:

- **OI-47** (resolved in UFR Sprint): VT-foreign fields in matching — fixed by scope filter in Matcher._score_one()
- **OI-55**: Unit-suffix drift warning (e.g. lifting_height_mm with AP0 unit=m). Warning only, not a runtime error.
- **OI-56**: Column-name collision guard in data_loader — startup assertion prevents Base Model fields from shadowing Product/Company columns.
- **OI-66–73**: UFR Sprint follow-ups including sub-spec OI-73 (multi-domain scoping future work).
- **M1**: m->mm conversion factor hardcoded inline in validate_agv_criteria — should come from plausibility.json.
- **H2**: Positional INSERTs in sync_airtable.py — schema-driven column ordering not yet fully complete.
