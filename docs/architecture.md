# Haystacked Platform — Architecture

**Version:** based on AP0 v0.10 (v1.3)  
**Last updated:** 2026-06-02 (run 9)

---

## What the system does

Haystacked is a B2B matching platform for AGV (Automated Guided Vehicle) and AMR (Autonomous Mobile Robot) tenders. A procurement team uploads a tender PDF. The system:

1. Extracts text from the PDF
2. Runs three or four LLM passes to understand what the buyer is asking for
3. Validates the LLM output against the AP0 field specification
4. Runs a rule-based matching engine against the supplier database
5. Returns a ranked list of qualified suppliers, streamed live to the browser

The whole process takes roughly 30–90 seconds per PDF.

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
    ├─► LLM Pass 1: basic_extraction     (buyer, project, is_agv_amr)
    ├─► LLM Pass 2: contact_fallback     (conditional — if contact missing)
    ├─► LLM Pass 3: nace_classification  (NACE code, in_scope flag)
    ├─► LLM Pass 4: agv_extraction       (conditional — if is_agv_amr=true)
    │       │
    │       ├─► validate_tender_values()   (AP0 allowed_values filter)
    │       └─► validate_agv_criteria()    (plausibility ranges + mm→m)
    │
    ├─► Vehicle type normalization (vt_map + text_overrides)
    ├─► VNA detection → required_vna logic
    └─► match_suppliers_new()  (rule engine, src/matching.py)
            │
            ▼
    SSE events → browser (step, log, result)
```

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

**The golden rule: never edit generated files.** Any change to `config/field_levels.json`, `config/vehicle_types.json`, `config/scoring_weights.json`, or any file under `config/prompts/` will be silently overwritten the next time `generate_all.py` runs or the app starts and detects a checksum mismatch.

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

**`--local` mode:** running `python3 sync_airtable.py --local` skips the Airtable API call entirely and rebuilds `data/haystacked.db` directly from the CSV files already in `data/raw/`. No `.env` file or Airtable credentials are needed. This is the standard workflow for contributors who do not have Airtable access.

**Airtable data versioned in git:** `data/raw/*.csv` and `data/haystacked.db` are committed to the repository alongside each release tag. This gives every contributor a reproducible supplier dataset without requiring Airtable credentials. The `.gitignore` deliberately does not exclude these files.

The sync is idempotent. Multi-select fields are stored as pipe-separated strings (e.g. `"Laser Reflector|Natural Feature (SLAM)"`). Boolean fields are stored as `0`/`1` integers. The SQLite schema (CREATE TABLE SQL) comes from `config/sqlite_schema.json`, which is itself generated from the AP0 Entity Model sheet.

### 2. Data loader (src/data_loader.py)

At startup, `app.py` calls `load_suppliers()` which executes a single 3-way JOIN:

```sql
SELECT p.*, c.*, bme.*
FROM products p
JOIN companies c ON p.company_id = c.company_id
JOIN base_model_extensions bme ON p.base_model_id = bme.base_model_id
WHERE p.active = 1
```

Each result row is parsed into a `SupplierRecord` dataclass (from `src/models.py`) containing a `Product` and an `Extension`. All type conversions happen here: pipe strings → lists, `"true"`/`"1"` → Python `True`, empty strings → `None`.

**Critical invariant — Blank ≠ Zero:** `None` means "unknown". It never means "this supplier lacks this capability". A supplier with `max_payload_kg=None` is not a zero-payload machine — the data simply has not been entered yet.

### 3. PDF upload and text extraction

`pdfplumber` extracts text page by page. Pages with no text are skipped. The combined text is capped at 50,000 characters (approximately 14,000 tokens) — well within the 32,768-token context window of qwen2.5:7b. If truncated, `[... Dokument gekürzt ...]` is appended.

### 4. LLM passes

All LLM calls go to Ollama running locally at `http://localhost:11434` using `qwen2.5:7b` at `temperature=0.0`. Each pass uses a system prompt (role definition) and a user prompt (template filled with document text).

**Pass 1 — basic extraction** (always runs)
- System: `basic_system.txt`
- Template: `basic_template.txt`, filled with `{text}`
- Extracts: buyer, project_name, project_location, tender_date, deadline, contact fields, buyer_industry, tender_category, is_agv_amr, summary
- Output: JSON, parsed by `repair_and_parse()`

**Pass 2 — contact fallback** (conditional: only if contact fields all missing AND document > 6,000 chars)
- System: `contact_system.txt`
- Template: `contact_template.txt`, filled with last 4,000 chars of document
- Extracts: contact_name, contact_email, contact_phone, deadline, tender_date
- Merges into Pass 1 result; only fills gaps (never overwrites existing values)

**Pass 3 — NACE classification** (always runs)
- System: `nace_system.txt`
- Template: `nace_template.txt`, filled with `{tender_category}`, `{buyer_industry}`, `{category_list}`
- Extracts: nace_tender, nace_tender_name, priority, confidence, in_scope (bool)
- `in_scope=false` means this is not an AGV/AMR tender — the platform shows results but flags it

**Pass 4 — AGV extraction** (conditional: only if `is_agv_amr=true`)
- System: `build_system_context()` from `src/context_builder.py`. This is the **canonical and only active source** of the AGV extraction system prompt in normal operation. It concatenates:
  1. `config/industry_readme.md` — full domain knowledge
  2. KO and COND_KO field descriptions from `config/field_levels.json`
  3. Nine critical extraction rules, numbered 1–9:
     - Rule 8: CONSERVATIVE VALUES — extract worst-case values (max of minimums, min of maximums)
     - Rule 9: ANTI-HALLUCINATION — every non-null value must be traceable to an exact sentence in the document; never infer from warehouse type, AGV type, or domain defaults; do not read numbers from dates, filenames, or version strings
- `extraction_system.txt` in `config/prompts/` is **dead code in normal operation**. It exists as a static text fallback only for the rare case where `haystacked.db` is unavailable (`_DB_AVAILABLE=False`). This path is not reached in production. `scripts/test_pipeline.py` was updated to use `build_system_context()` so test prompts match production exactly.
- Template: `extraction_template.txt`, filled with `{text}`. This template is fully generated by `generate_all.py` — it contains the vehicle type classification guide, the Chain-of-Thought ordering instructions, and all field definitions with their AP0 extraction hints
- On parse failure: automatic retry using `extraction_retry_system.txt` + `extraction_retry_template.txt`

### 5. Post-LLM validation

Two validation steps clean the LLM output before matching:

**`validate_tender_values()` (src/matching.py)**
Checks every Dropdown and Multi-Select field against its `allowed_values` list from `field_levels.json`. Values not in the allowed list are set to `None` and logged. Case-insensitive substring matching. For example, if the LLM returns `"Floor delivery"` for `required_load_types` (allowed: `Pallet EUR|Pallet ISO|Tote|Roll Container|...`), it is rejected and set to `None`.

**`validate_agv_criteria()` (app.py)**
Checks numeric fields against plausibility ranges from `config/plausibility.json`. Auto-converts mm→m for dimensional fields (aisle width, lift height) when the value appears to be in millimetres (value > 10 and in-range after conversion). Out-of-range values are set to `None` with a warning.

### 6. Vehicle type normalization

After AGV extraction, `app.py` runs two normalization layers:

**Layer 1 — vt_map lookup**
The LLM output string (e.g. `"vna"`, `"forklift agv"`, `"agv"`) is lowercased and looked up in `_VT_MAP_CFG`. This maps it to a canonical type: `"Forklift AGV"`, `"Tugger AGV"`, or `"Mobile AMR"`. If not found in the map, `agv_type_keyword_fallback()` scans the first 5,000 characters of the document for known keywords.

**Layer 2 — text_overrides**
A list of regex patterns from `vehicle_types.json` is checked against the full document text. If a pattern matches (e.g. `\bVNA\b` or `(?i)schmalgangstapler`), the canonical type and/or VNA flag can be forced, overriding the LLM's output. This is the mechanism that ensures German tender documents using "Schmalgangstapler" are correctly classified as VNA even if the LLM returned a generic type.

### 7. VNA logic

VNA (Very Narrow Aisle) is the most complex single piece of logic. After vehicle type normalization:

- If `is_vna_subtype=True` (LLM returned "vna"/"very narrow aisle" OR a text override fired): `required_vna = "required"`
- If the canonical type is in `vna_applicable_types` (currently only `"Forklift AGV"`) but VNA was not detected: `required_vna = "not_required"`
- For all other canonical types (Tugger, Mobile AMR): `required_vna = None` — no VNA gate applies

The `required_vna` field maps to the `vna_capable` supplier field with operator `KO_BOOL_EXCLUSIVE`:
- `required_vna = "required"` → supplier must have `vna_capable=True`, otherwise K.O.
- `required_vna = "not_required"` → supplier must NOT have `vna_capable=True`, otherwise K.O. (VNA machines excluded from standard-aisle tenders)
- `required_vna = None` → no constraint

VNA detection does not inject a `required_drive_type` value. Drive type is CONTEXT level and carries no matching operator. The VNA gate is enforced entirely through the `vna_capable` field using `KO_BOOL_EXCLUSIVE`.

**VNA always implies rack operations (Section 5 rule).** When VNA is detected, the industry README instructs the LLM that `required_station_types` must include at least one rack type — even if the tender does not name the rack model. This is encoded in `Spec/haystacked_industry_readme.md` (Section 5) and synced to `config/industry_readme.md`, which is injected into the AGV extraction system prompt.

**VNA does not exclude floor or conveyor stations.** A VNA turret truck can serve floor-level or conveyor pick/drop points alongside rack operations. The presence of floor or conveyor station types in a VNA tender is not a contradiction and must not cause the LLM to suppress the VNA classification.

### 8. Matching engine

`match_suppliers_new()` in `src/matching.py` runs the rule engine against all loaded `SupplierRecord` objects. Rules come exclusively from `config/field_levels.json`. There is no domain knowledge in `matching.py` itself.

For each supplier:
1. Hard K.O. rules (`level="KO"`) are checked. The first failure immediately disqualifies the supplier and stops evaluation.
2. Conditional K.O. rules (`level="COND_KO"`) are checked. Failures add to a list but do not stop evaluation — if any COND_KO fails, the supplier is still disqualified.
3. Null penalty: for numeric KO fields where the tender has a value but the supplier has `None`, a `-15 pt` penalty is applied (not a disqualification).
4. Scoring rules run for all non-disqualified suppliers. Points are awarded based on supplier capability data and the rules in `config/scoring_weights.json`.

Qualified suppliers are sorted by score (descending). Disqualified suppliers follow, also sorted by score.

### 9. SSE streaming

Results are streamed to the browser using Server-Sent Events. Events are emitted at each processing step so the frontend can show a live progress indicator:
- `step` — progress update (id, status: running/done/error, message)
- `log` — diagnostic detail (not shown to end user by default)
- `result` — final payload containing all extracted fields, agv_criteria, matches (top 5), and matches_all (all scored suppliers)
- `error` — fatal error, stops processing

**Progress indicator:** all five steps (upload, extract, llm, parse, agv) are set to `pending` state when the upload begins — including the AGV Matching step. This means the full progress bar is visible from the start of upload; no step appears or disappears mid-flow.

### 10. Clarification questions (frontend)

After AGV extraction, the frontend may prompt the user for missing values before running matching (e.g. aisle width if the LLM did not extract it). The `min_aisle_width_mm` clarification question is skipped automatically when the extracted `required_station_types` contains no rack-type stations (floor-only or conveyor-only tenders have no aisles to measure). This check runs in the browser using the extracted `required_station_types` value from the LLM result.

---

## Key components

| File | Role |
|---|---|
| `app.py` | FastAPI entry point. LLM orchestration, vehicle type normalization, VNA logic, SSE streaming |
| `src/matching.py` | Pure rule engine. Operators, TenderRequirements, Matcher, validate_tender_values |
| `src/data_loader.py` | SQLite 3-way JOIN → list[SupplierRecord] |
| `src/models.py` | Dataclasses: Company, Product, Extension, SupplierRecord |
| `src/context_builder.py` | Builds AGV extraction system prompt; keyword fallback |
| `src/llm_client.py` | Standalone LLM client with retry and repair_and_parse (used by tests; app.py has its own inline version) |
| `scripts/generate_all.py` | Config pipeline: reads AP0 xlsx → writes all config/ files |
| `sync_airtable.py` | Airtable API pull → CSV → SQLite import. `--local` flag skips API and rebuilds from committed CSVs |
| `config/field_levels.json` | Generated. Matching rules per field (level, operator, tender_key, allowed_values) |
| `config/vehicle_types.json` | Generated. vt_map, VNA subtypes, text_overrides, keyword_map, scoring_bucket_map |
| `config/scoring_weights.json` | Generated. Scoring weights and rules per field per AGV-type bucket |
| `config/plausibility.json` | Generated. Plausibility ranges for LLM value validation |
| `config/sqlite_schema.json` | Generated. CREATE TABLE SQL for sync_airtable.py to use |
| `config/prompts/*.txt` | Generated. All LLM prompt files |
| `config/industry_readme.md` | Synced from Spec/ by generate_all.py. Domain knowledge for the AGV extraction system prompt |

---

## Key invariants

**Blank ≠ Zero.** `None` in a supplier record means the data has not been entered, not that the capability is absent. The null rule (LL-06) implements this: `None` on either side of a K.O. comparison never triggers disqualification for numeric and categorical operators.

**No domain logic in Python.** All field definitions, operators, vehicle type names, scoring thresholds, and LLM extraction hints come from the AP0 xlsx via `generate_all.py`. If you find yourself writing a supplier name, AGV type string, or numeric threshold in Python code, that is an architecture violation.

**Never edit generated files.** Files under `config/` are generated. Edits will be overwritten. The only files under `config/` that are safe to edit are those not written by `generate_all.py`: currently none — even `config/industry_readme.md` is synced from `Spec/haystacked_industry_readme.md`.

**AP0 level strings are exact.** `generate_all.py` uses a strict mapping: `"K.O."` → `"KO"`, `"Cond. K.O."` → `"COND_KO"`, `"Scoring"` → `"SCORING"`, `"Context"` → `"CONTEXT"`. A typo like `"Cond.K.O."` or `"COND_KO"` in the xlsx will cause the field to be silently ignored.

**drive_type is CONTEXT level, not KO or COND_KO.** After the 2026-06-02 fix, `drive_type` carries no matching operator. It is displayed in the results panel but does not affect filtering or scoring. VNA is hard-gated via `vna_capable` (`KO_BOOL_EXCLUSIVE`) — no separate drive_type injection is needed. The dead `required_drive_type` injection that previously ran in `app.py` (lines 573–578) has been removed. The extraction prompt still instructs the LLM: "ONLY extract if tender explicitly names drive type — do NOT infer from task description."

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
