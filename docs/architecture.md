# Haystacked Platform — Architecture

**Version:** based on AP0 v0.10 (v1.3)  
**Last updated:** 2026-06-03 (run 10 — Pass 4c + source-span hallucination guard)

---

## What the system does

Haystacked is a B2B matching platform for AGV (Automated Guided Vehicle) and AMR (Autonomous Mobile Robot) tenders. A procurement team uploads a tender PDF. The system:

1. Extracts text from the PDF
2. Runs up to 16 LLM passes to understand what the buyer is asking for
3. Validates LLM output against the AP0 field specification and source-span citations
4. Runs a rule-based matching engine against the supplier database
5. Returns a ranked list of qualified suppliers, streamed live to the browser

For AGV tenders the process takes roughly 330 seconds (~5.5 minutes) wall time due to 13–16 sequential Ollama calls.

---

## High-level architecture

```
AP0 xlsx (Spec/)
    │
    ▼
generate_all.py ──────────────────────────────────────────────┐
    │                                                          │
    ├─► config/field_levels.json   (matching rules)           │
    ├─► config/vehicle_types.json  (type map, VNA logic)      │
    ├─► config/scoring_weights.json                           │
    ├─► config/nace_codes.json                                │
    ├─► config/plausibility.json   (LLM value ranges)         │
    ├─► config/sqlite_schema.json  (CREATE TABLE SQL)         │
    ├─► config/extraction_hints.json (tender_key → hint+sheet)│
    └─► config/prompts/*.txt       (all LLM prompts)          │
                                                              │
Airtable ──► sync_airtable.py ──► data/raw/*.csv ──► data/haystacked.db ◄──┘
                 │ (--local flag skips Airtable fetch,
                 │  rebuilds DB from committed CSVs)
                                        │
                                  data_loader.py
                                  (3-way JOIN, active=1)
                                        │
                                  list[SupplierRecord]

PDF upload
    │
    ▼
app.py (FastAPI, SSE streaming)
    ├─► pdfplumber  (text extraction)
    ├─► LLM Pass 1: basic_extraction    (buyer, project, is_agv_amr)
    ├─► LLM Pass 2: contact_fallback    (conditional — if contact missing)
    ├─► LLM Pass 3: nace_classification (NACE code, in_scope flag)
    │
    └── if is_agv_amr = true:
        ├─► LLM Pass 4a: vehicle_type_classification (vehicle type + VNA flag)
        ├─► LLM Pass 4b: agv_extraction (all ~40 fields in one JSON blob)
        │       └─► AP0 allowed-values retry (max 2 correction calls)
        ├─► LLM Pass 4c: per_field_extraction (8 focused calls, numeric KO fields)
        ├─► Source-span enforcement (Layer 1 + Layer 2 hallucination guard)
        ├─► validate_tender_values()   (AP0 allowed_values filter)
        ├─► validate_agv_criteria()    (plausibility ranges + mm→m)
        │
        └─► match_suppliers_new()  (rule engine, src/matching.py)
                │
                ▼
        SSE events → browser (step, log, result)
```

---

## LLM call budget per tender

| Pass | Label | Purpose | Calls |
|---|---|---|---|
| 1 | `basic` | Buyer, project, contact, is_agv_amr, summary | 1 |
| 2 | `contact` | Contact fallback (last 4,000 chars, only if contact missing) | 0–1 |
| 3 | `nace` | NACE code + in_scope classification | 1 |
| 4a | `agv_4a` | Vehicle type classification + VNA flag | 1 |
| 4b | `agv_4b` | Batch extraction of all ~40 fields in one JSON blob | 1 |
| 4b correction | `agv_4b_correction1/2` | AP0 allowed-values retry (max 2) | 0–2 |
| 4c | `agv_4c_<field>` | Per-field focused extraction for numeric KO fields | ~8 |

**Typical total: 13–16 calls per AGV tender. ~330 s wall time.**

Non-AGV tenders (is_agv_amr=false) stop after Pass 3: 2–3 calls total.

---

## AP0 xlsx: the single source of truth

The file `Spec/haystacked_AP0_field_spec_v0_10.xlsx` is the authoritative source for every piece of business logic in the platform. If you want to change how matching works, you change this file — not Python code.

**What lives in the AP0 xlsx:**

| Sheet | What it controls |
|---|---|
| SHARED – All AGV Types | Fields that apply to all vehicle types: payload, navigation, temperatures, fleet management, etc. Each row is one field with its Level (K.O./Cond. K.O./Scoring/Context), operator, data type, tender JSON key, allowed values, and LLM extraction hint |
| Forklift AGV | Forklift-specific fields: lifting height, aisle width, drive type, VNA capability, fork type, etc. |
| Tugger AGV | Tugger-specific fields: towing capacity, auto hitch, trailer count, etc. |
| Mobile AMR | AMR-specific fields: workflow capability, grid requirement, picking mechanism, etc. |
| Vehicle Types | Maps LLM output strings to canonical types; VNA subtype flags; text override regexes; keyword fallback lists; LLM classification guide text |
| Entity Model | Three-layer data model: Company (L1), Product (L2), Base Model + Extension (L3). Source for SQLite CREATE TABLE generation |
| Scoring (inline) | Scoring Weight, Scoring Rule, Threshold 1, Threshold 2 columns in each data sheet |
| Field Fallbacks | Regex-driven field overrides: if text matches regex, force a given tender_key value |

**The AP0 Description column is especially important.** It is the source for LLM extraction hints in `config/extraction_hints.json` and in the generated prompt templates. When you edit a Description cell in the AP0 xlsx, you directly change what the LLM is told about that field. Keep description text factual and pattern-focused. Never include numeric example values — a 7B model will copy them as hallucinations.

**The golden rule: never edit generated files.** Any change to `config/field_levels.json`, `config/vehicle_types.json`, `config/scoring_weights.json`, `config/extraction_hints.json`, or any file under `config/prompts/` will be silently overwritten the next time `generate_all.py` runs or the app starts and detects a checksum mismatch.

### Auto-regeneration at startup

`app.py` computes an MD5 checksum of the AP0 xlsx at startup (`_check_and_regen()`). If it differs from the stored checksum in `config/ap0_checksum.txt`, it automatically calls `generate_all.py`. This means deploying a new AP0 xlsx is enough — no manual config step needed.

---

## Data flow: step by step

### 1. Airtable → SQLite

`sync_airtable.py` fetches four tables from Airtable via the REST API:
- `companies` — supplier companies
- `products` — individual AGV products (one company can have many)
- `base_models` — physical hardware base models (an OEM unit can be rebadged by multiple companies)
- `extensions` (`base_model_extensions`) — technical specification fields per base model and AGV type

**`--local` mode:** running `python3 sync_airtable.py --local` skips the Airtable API call entirely and rebuilds `data/haystacked.db` directly from the CSV files already in `data/raw/`. No `.env` file or Airtable credentials are needed.

**Airtable data versioned in git:** `data/raw/*.csv` and `data/haystacked.db` are committed alongside each release tag. The `.gitignore` deliberately does not exclude these files.

The sync is idempotent. Multi-select fields are stored as pipe-separated strings (e.g. `"Laser Reflector|Natural Feature (SLAM)"`). Boolean fields are stored as `0`/`1` integers. The SQLite schema (CREATE TABLE SQL) comes from `config/sqlite_schema.json`, generated from the AP0 Entity Model sheet.

### 2. Data loader (src/data_loader.py)

At startup, `app.py` calls `load_suppliers()` which executes a single 3-way JOIN:

```sql
SELECT p.*, c.*, bme.*
FROM products p
JOIN companies c ON p.company_id = c.company_id
JOIN base_model_extensions bme ON p.base_model_id = bme.base_model_id
WHERE p.active = 1
```

Each result row is parsed into a `SupplierRecord` dataclass containing a `Product` and an `Extension`. All type conversions happen here: pipe strings → lists, `"true"`/`"1"` → Python `True`, empty strings → `None`.

**Critical invariant — Blank ≠ Zero:** `None` means "unknown". A supplier with `max_payload_kg=None` is not a zero-payload machine — the data has not been entered yet.

### 3. PDF upload and text extraction

`pdfplumber` extracts text page by page. Pages with no text are skipped. The combined text is capped at 50,000 characters (approximately 14,000 tokens) — well within the 32,768-token context window of qwen2.5:7b. If truncated, `[... Dokument gekürzt ...]` is appended.

### 4. LLM passes

All LLM calls go to Ollama running locally at `http://localhost:11434` using `qwen2.5:7b` at `temperature=0.0`. Each pass uses a system prompt (role definition) and a user prompt (template filled with document text).

**Pass 1 — basic extraction** (always runs)
- System: `basic_system.txt`
- Template: `basic_template.txt`, filled with `{text}`
- Extracts: buyer, project_name, project_location, tender_date, deadline, contact fields, buyer_industry, tender_category, is_agv_amr, summary
- After parsing, keyword fallback runs: if is_agv_amr was not set but the first 5,000 chars contain known AGV keywords, is_agv_amr is forced to True

**Pass 2 — contact fallback** (conditional: only if all contact fields missing AND document > 6,000 chars)
- System: `contact_system.txt`
- Template: `contact_template.txt`, filled with last 4,000 chars of document
- Extracts: contact_name, contact_email, contact_phone, deadline, tender_date
- Merges into Pass 1 result; only fills gaps (never overwrites existing values)

**Pass 3 — NACE classification** (always runs)
- System: `nace_system.txt`
- Template: `nace_template.txt`, filled with `{tender_category}`, `{buyer_industry}`, `{category_list}`
- Extracts: nace_tender, nace_tender_name, priority, confidence, in_scope (bool)
- `in_scope=false` means this is not an AGV/AMR tender — the platform shows results but flags it

If `is_agv_amr=false`, processing stops here (no AGV passes). Total: 2–3 LLM calls.

**Pass 4a — vehicle type classification** (only if is_agv_amr=true)
- System: `AGV_SYSTEM` (built by `context_builder.build_system_context()`)
- Template: `vehicle_type_template.txt`, filled with `{text}`
- Extracts: required_vehicle_type (exactly one of: Forklift AGV / Tugger AGV / Mobile AMR) and required_vna (boolean)
- AP0 validation on required_vehicle_type: up to 2 correction retries if the LLM returns an invalid value
- After parsing: vehicle type is normalized through vt_map; VNA flag is set; text_overrides run against full document

**Pass 4b — batch field extraction** (only if is_agv_amr=true)
- System: `AGV_SYSTEM`
- Template: type-specific `extraction_template_<type>.txt` (e.g. `extraction_template_forklift_agv.txt`), filled with `{text}`, `{vehicle_type}`, `{vna_context}`
- Extracts all ~40 AP0 fields for the detected vehicle type in a single JSON blob
- Numeric KO fields include a companion `<field>_source` key — the LLM must quote the verbatim source sentence
- AP0 validation: up to 2 correction calls (`agv_4b_correction1/2`) for invalid dropdown/multi-select values

**Pass 4c — per-field extraction for numeric KO fields** (runs after 4b, before source-span enforcement)
- System: `AGV_SYSTEM`
- Prompt: constructed inline in `app.py` — one focused prompt per field, never a generated file
- Runs for all Float/Integer fields with KO_IF_LT or KO_IF_GT operator, scoped to the detected vehicle type (SHARED sheet + type-specific sheet)
- Typical field count: ~8 per tender
- Per-field prompt structure: vehicle type context → find the value of `<field>` → Step 1: scan for direct statement → Step 2: if found, copy verbatim and extract number → Step 3: if not found, output null for both field and source
- Extraction direction is operator-derived from `_4C_EXTRACTION_DIRECTION`:
  - KO_IF_LT → "extract the MAXIMUM — the supplier must meet or exceed this threshold"
  - KO_IF_GT → "extract the MINIMUM — the supplier must not exceed this constraint"
- NULL RULE clause is stripped from the hint to reduce null-bias (the system prompt already contains the anti-hallucination rule)
- Non-null 4c results override 4b values; null 4c results are recorded in `_4c_abstained` set — they are never unconditionally applied (this is the key to Layer 2 enforcement below)

### 5. Source-span hallucination guard

After Pass 4c, `app.py` iterates over all fields in `_NUMERIC_KO_TENDER_KEYS` and applies two enforcement layers in sequence:

**Layer 1 — missing source (always active)**
If `<field>_source` is absent or null for a field that has a non-null value: the value is set to null. Rationale: if the LLM had an explicit textual source it would have cited it. Absence of citation implies inference.

**Layer 2 — abstention + fake source (scoped to 4c abstentions)**
Triggered only when both conditions hold:
1. The field is in `_4c_abstained` (Pass 4c returned null or failed for this field)
2. `_source_confirms_value(agv_criteria[field], agv_criteria[field+"_source"])` returns False

`_source_confirms_value()` is a pure numeric check in `app.py`:
- Strips thousands separators ("1,000" → 1000)
- Tests direct match
- Tests mm/m scale (value 1.9 matches 1900 in source; value 2000 matches 2.0)
- Zero values always pass (a deliberate zero is not hallucination)
- Contains no field names, no domain logic — fully field-agnostic

When Layer 2 fires, the value from 4b is nulled. This catches the specific case where 4b extracted a value AND wrote a plausible-looking source sentence, but the independent 4c pass (shorter, more focused prompt) abstained. The 4c abstention is evidence that the 4b source may be a fabricated citation.

### 6. Post-LLM validation

**`validate_tender_values()` (src/matching.py)**
Checks every Dropdown and Multi-Select field against its `allowed_values` list from `field_levels.json`. Values not in the allowed list are set to `None`. Case-insensitive substring matching.

**`validate_agv_criteria()` (app.py)**
Checks numeric fields against plausibility ranges from `config/plausibility.json`. Auto-converts mm→m for dimensional fields (aisle width, lift height) when the value appears to be in millimetres (value > 10 and in-range after conversion). Out-of-range values are set to `None`.

**Field text fallbacks**
After both validation steps, `app.py` applies regex-driven field overrides from `vehicle_types.json` → `field_text_fallbacks`. If the full PDF text matches a pattern, the corresponding tender_key is set to the configured fallback value. The `only_if_null` flag controls whether the fallback overwrites an existing value.

### 7. Vehicle type normalization

After AGV extraction, `app.py` runs two normalization layers:

**Layer 1 — vt_map lookup**
The LLM output string (e.g. `"vna"`, `"forklift agv"`, `"agv"`) is lowercased and looked up in `_VT_MAP_CFG`. This maps it to a canonical type: `"Forklift AGV"`, `"Tugger AGV"`, or `"Mobile AMR"`. If not found in the map, `agv_type_keyword_fallback()` scans the first 5,000 characters of the document for known keywords.

**Layer 2 — text_overrides**
Regex patterns from `vehicle_types.json` are checked against the full document text. If a pattern matches (e.g. `\bVNA\b` or `(?i)schmalgangstapler`), the canonical type and/or VNA flag can be forced. This ensures German tenders using "Schmalgangstapler" are correctly classified as VNA even if the LLM returned a generic type.

### 8. VNA logic

After vehicle type normalization:
- If `is_vna_subtype=True` (LLM returned "vna"/"very narrow aisle" OR a text override fired): `required_vna = "required"`
- If canonical type is in `vna_applicable_types` (only `"Forklift AGV"`) but VNA not detected: `required_vna = "not_required"`
- For Tugger AGV or Mobile AMR: `required_vna = None` — no VNA gate applies

The `required_vna` field maps to the `vna_capable` supplier field with operator `KO_BOOL_EXCLUSIVE`:
- `required_vna = "required"` → supplier must have `vna_capable=True`; otherwise K.O.
- `required_vna = "not_required"` → supplier must NOT have `vna_capable=True`; otherwise K.O.
- `required_vna = None` → no constraint

`drive_type` is CONTEXT level and carries no matching operator. The VNA gate is enforced entirely through `vna_capable`.

### 9. Matching engine

`match_suppliers_new()` in `src/matching.py` runs the rule engine against all loaded `SupplierRecord` objects. Rules come exclusively from `config/field_levels.json`. There is no domain knowledge in `matching.py` itself.

For each supplier:
1. Hard K.O. rules (`level="KO"`) are checked. The first failure immediately disqualifies the supplier and stops evaluation.
2. Conditional K.O. rules (`level="COND_KO"`) are checked. Failures add to a list but do not stop evaluation.
3. Null penalty: for numeric KO fields where the tender has a value but the supplier has `None`, a `-15 pt` penalty is applied (not a disqualification).
4. Scoring rules run for all non-disqualified suppliers.

Qualified suppliers are sorted by score (descending). Disqualified suppliers follow.

### 10. SSE streaming

Results are streamed to the browser using Server-Sent Events:
- `step` — progress update (id, status: running/done/error, message)
- `log` — diagnostic detail (not shown to end user by default)
- `result` — final payload containing all extracted fields, agv_criteria, matches (top 5), and matches_all
- `error` — fatal error, stops processing

---

## Module-level constants in app.py

These constants are built at startup from the generated config files and are the foundation for Pass 4c and the source-span guard:

| Constant | Type | Built from | Purpose |
|---|---|---|---|
| `_NUMERIC_KO_TENDER_KEYS` | `frozenset[str]` | `field_levels.json` | All tender keys with KO_IF_LT or KO_IF_GT operator and Float/Integer data type. Non-empty is asserted at startup. |
| `_NUMERIC_KO_FIELD_HINTS` | `dict` | `extraction_hints.json` filtered by `_NUMERIC_KO_TENDER_KEYS` | Maps tender_key → {hint, sheet} for numeric KO fields that have a hint and a sheet assignment. Used to build Pass 4c prompts. |
| `_4C_EXTRACTION_DIRECTION` | `dict` | `field_levels.json` operators | Maps tender_key → extraction direction string. KO_IF_LT → "extract MAXIMUM". KO_IF_GT → "extract MINIMUM". |
| `_SHARED_SHEET` | `str` | `vehicle_types.json` key `shared_sheet_name` | The name of the AP0 shared sheet. Used to scope Pass 4c to the right fields per vehicle type. Never hardcoded. |
| `_AP0_CONSTRAINED_FIELDS` | `dict` | `field_levels.json` | Maps tender_key → {allowed set, allowed list} for all Dropdown/Multi-Select fields with allowed_values. Used in _find_invalid_ap0_fields(). |

---

## Key components

| File | Role |
|---|---|
| `app.py` | FastAPI entry point. LLM orchestration (all passes), vehicle type normalization, VNA logic, source-span guard, SSE streaming |
| `src/matching.py` | Pure rule engine. Operators, TenderRequirements, Matcher, validate_tender_values |
| `src/data_loader.py` | SQLite 3-way JOIN → list[SupplierRecord] |
| `src/models.py` | Dataclasses: Company, Product, Extension, SupplierRecord |
| `src/context_builder.py` | Builds AGV extraction system prompt (AGV_SYSTEM); keyword fallback |
| `scripts/generate_all.py` | Config pipeline: reads AP0 xlsx → writes all config/ files |
| `sync_airtable.py` | Airtable API pull → CSV → SQLite import. `--local` flag skips API |
| `config/field_levels.json` | Generated. Matching rules per field (level, operator, tender_key, allowed_values, data_type) |
| `config/vehicle_types.json` | Generated. vt_map, VNA subtypes, text_overrides, keyword_map, scoring_bucket_map, shared_sheet_name |
| `config/scoring_weights.json` | Generated. Scoring weights and rules per field per AGV-type bucket |
| `config/plausibility.json` | Generated. Plausibility ranges for LLM value validation |
| `config/sqlite_schema.json` | Generated. CREATE TABLE SQL and field type lists for sync_airtable.py |
| `config/extraction_hints.json` | Generated. Maps tender_key → {hint, sheet} for all 51 extraction fields. Powers Pass 4c. |
| `config/prompts/basic_*.txt` | Generated. Pass 1 system and template |
| `config/prompts/contact_*.txt` | Generated. Pass 2 system and template |
| `config/prompts/nace_*.txt` | Generated. Pass 3 system and template |
| `config/prompts/vehicle_type_template.txt` | Generated. Pass 4a user template |
| `config/prompts/extraction_template.txt` | Generated. Full combined Pass 4b template (fallback) |
| `config/prompts/extraction_template_forklift_agv.txt` | Generated. Forklift-specific Pass 4b template |
| `config/prompts/extraction_template_tugger_agv.txt` | Generated. Tugger-specific Pass 4b template |
| `config/prompts/extraction_template_mobile_amr.txt` | Generated. Mobile AMR-specific Pass 4b template |
| `config/prompts/extraction_retry_*.txt` | Generated. JSON-parse failure retry templates |
| `config/prompts/extraction_system.txt` | Generated but inactive in normal operation — loaded only as fallback when DB unavailable |
| `config/industry_readme.md` | Synced from Spec/ by generate_all.py. Domain knowledge injected into AGV_SYSTEM |

---

## Key invariants

**Blank ≠ Zero.** `None` in a supplier record means the data has not been entered, not that the capability is absent. The null rule (LL-06) implements this: `None` on either side of a K.O. comparison never triggers disqualification for numeric and categorical operators.

**No domain logic in Python.** All field definitions, operators, vehicle type names, scoring thresholds, extraction hints, and extraction directions come from the AP0 xlsx via `generate_all.py`. If you find yourself writing a supplier name, AGV type string, or numeric threshold in Python code, that is an architecture violation.

**Never edit generated files.** Files under `config/` are generated. Edits will be overwritten.

**AP0 level strings are exact.** `"K.O."` → `"KO"`, `"Cond. K.O."` → `"COND_KO"`, `"Scoring"` → `"SCORING"`, `"Context"` → `"CONTEXT"`. A typo will cause the field to be silently ignored.

**drive_type is CONTEXT level, not KO.** It is displayed in results but does not affect filtering or scoring. VNA is hard-gated via `vna_capable` (`KO_BOOL_EXCLUSIVE`).

**No numeric literals in AP0 Description cells.** A 7B model copies example numbers in extraction hints as hallucinations (the "prompt poisoning" failure mode documented in project_companyx_hallucinations.md). Describe patterns verbally instead of numerically.

**_source_confirms_value() is field-agnostic.** It contains no field names, no domain knowledge, and no AP0 allowed-value lists. It is a pure numeric string-matching function. Any domain logic added to it is an architecture violation.

**Pass 4c abstentions are not unconditional overrides.** When 4c returns null, the 4b value is preserved unless Layer 2 also fires. Abstention alone does not null a field.

---

## Technology stack

| Layer | Technology |
|---|---|
| API server | Python, FastAPI, Uvicorn |
| LLM | Ollama (local), qwen2.5:7b, temperature 0.0 |
| PDF extraction | pdfplumber |
| Supplier database | SQLite (data/haystacked.db) |
| Supplier data source | Airtable (synced via REST API) |
| Config generation | openpyxl (reads AP0 xlsx) |
| Frontend | Server-Sent Events, Jinja2 templates |
| Testing | pytest |

---

## Test inventory

| Module | Test IDs | Coverage |
|---|---|---|
| `tests/unit/test_matching_logic.py` | U-M-01 to U-M-28 | KO operators, COND_KO, scoring, VNA gate, null penalty, regression guards |
| `tests/unit/test_extraction_nulls.py` | U-E-01 to U-E-07 | Golden extraction values for Dragonfly tender; _source_confirms_value boundaries; _NUMERIC_KO_TENDER_KEYS non-empty guard |
| `tests/unit/test_json_repair_parser.py` | U-J-01 to U-J-08 | repair_and_parse (markdown fences, prose before JSON, truncated JSON, unescaped newlines) |
| `tests/unit/test_agv_keyword_fallback.py` | U-K-01 to U-K-08 | agv_type_keyword_fallback (VNA, Schmalgangstapler, Routenzug, AMR, no-match, 5000-char boundary) |
| `tests/unit/test_data_loader.py` | U-D-01 to U-D-16 | _parse_multiselect, _parse_bool, _parse_int, _parse_float edge cases |
| `tests/integration/test_llm_preflight.py` | I-S-01 to I-S-02 | Ollama reachability; qwen2.5:7b in manifest; JSON inference smoke test |

**Total: 68 tests** (28 matching + 7 extraction + 8 JSON repair + 8 keyword fallback + 14 data loader + 2 integration + 1 integration smoke)

### Coverage gaps

- No live extraction tests: the unit tests pin expected null/value outcomes but do not call Ollama
- No end-to-end SSE test: the streaming endpoint has no integration test
- No test for `repair_and_parse` brace-balanced Step 0 (the new stray-`}` guard)
- No test for `_build_correction_prompt` output format
- No test for `validate_agv_criteria` mm→m conversion
- No test for Layer 1 source-span enforcement (field nulled when `_source` absent)
- No test for Layer 2 source-span enforcement (4b value nulled when 4c abstained and source does not confirm)
- No test for field text fallbacks (regex → forced value)
