---
title: Haystacked Platform — Technical Reference
version: auto-generated
date: 2026-06-17
author: app-documentation-writer agent
---

# Haystacked Platform — Technical Reference

## 1. System Overview

### 1.1 Purpose and business context

Haystacked is a B2B matching platform for AGV (Automated Guided Vehicle) and AMR (Autonomous Mobile Robot) procurement tenders. A procurement team uploads a PDF tender document. The platform:

1. Extracts plain text from the PDF
2. Runs a sequence of LLM passes to identify what the buyer is asking for
3. Validates the LLM output against the AP0 field specification and source-span citations
4. Runs a pure rule-based matching engine against the supplier database
5. Returns a ranked, scored list of qualified suppliers, streamed live to the browser

The core value proposition: a buyer uploads a 30-page tender document and within ~330 seconds receives a ranked list of suppliers whose technical capabilities match the stated requirements, with explicit K.O. reasons for excluded suppliers.

### 1.2 High-level architecture

```
AP0 xlsx (Spec/)
    │
    ▼
generate_all.py ──────────────────────────────────────────────────────┐
    ├─► config/field_levels.json     matching rules                   │
    ├─► config/vehicle_types.json    type map, VNA, keywords          │
    ├─► config/scoring_weights.json  scoring rules                    │
    ├─► config/nace_codes.json       NACE Prio-1 list                 │
    ├─► config/plausibility.json     LLM value ranges                 │
    ├─► config/sqlite_schema.json    CREATE TABLE SQL                 │
    ├─► config/extraction_hints.json tender_key → hint+sheet          │
    └─► config/prompts/*.txt         all LLM prompt files             │
                                                                      │
Airtable ──► sync_airtable.py ──► data/raw/*.csv ──► haystacked.db ◄─┘
                │ (--local: skip API, rebuild from CSVs)
                                          │
                                    data_loader.py
                                    (3-way JOIN, active=1)
                                          │
                                    list[SupplierRecord]

PDF upload
    │
    ▼
app.py (FastAPI + SSE streaming)
    ├─► pdfplumber           text extraction
    ├─► Pass 1: basic        buyer, project, is_agv_amr
    ├─► Pass 2: contact      conditional — last 4,000 chars
    ├─► Pass 3: nace         NACE code + in_scope
    │
    └── if is_agv_amr = true ─────────────────────────────
        ├─► Pass 4a: vehicle_type   classify + VNA flag
        ├─► Pass 4b: agv_batch      ~40 fields in one JSON
        │     └─► correction1/2     AP0 allowed-values retry
        ├─► Pass 4c: per_field      ~8 focused calls
        ├─► Source-span guard  (enforce_source_spans() in src/json_repair.py)
        │     ├─► Layer 1  source absent → null value
        │     ├─► Layer 0  source not grounded in document → null value
        │     └─► Layer 2  4c abstained + source digit mismatch → null
        ├─► validate_tender_values()
        ├─► validate_agv_criteria()
        ├─► field_text_fallbacks
        └─► match_suppliers_new() ──► SSE events → browser
```

### 1.3 Technology stack

| Layer | Technology |
|---|---|
| API server | Python 3.11, FastAPI, Uvicorn |
| LLM | Ollama (local), qwen2.5:7b, temperature=0.0, num_ctx=32768 |
| PDF extraction | pdfplumber |
| Supplier database | SQLite (`data/haystacked.db`) |
| Supplier data source | Airtable REST API |
| Config generation | openpyxl (reads AP0 xlsx) |
| Frontend | Server-Sent Events, Jinja2 templates |
| Testing | pytest (139 tests as of 2026-06-17) |

---

## 2. Repository Structure

```
/
├── app.py                      FastAPI entry point; all LLM orchestration; source-span guard; SSE
├── sync_airtable.py            Airtable → CSV → SQLite import; --local mode
├── start.sh                    Start Ollama + Uvicorn; auto-pulls model if missing
├── CLAUDE.md                   Architecture overview for Claude Code
│
├── Spec/
│   ├── haystacked_AP0_field_spec_v0_10.xlsx   Single source of truth (ALL business logic)
│   ├── haystacked_platform_config.xlsx         NACE codes, basic extraction schema, scope
│   └── haystacked_industry_readme.md           Domain knowledge; synced → config/ by generate_all.py
│
├── scripts/
│   ├── generate_all.py         Config pipeline: reads AP0 xlsx → writes config/
│   ├── test_pipeline.py        Manual end-to-end test harness (requires Ollama)
│   └── migrate_ap0_scoring_rules.py  One-time migration helper (historical)
│
├── src/
│   ├── matching.py             Pure rule engine; all operators; TenderRequirements; Matcher
│   ├── data_loader.py          SQLite 3-way JOIN → list[SupplierRecord]
│   ├── models.py               Dataclasses: Company, Product, Extension, SupplierRecord
│   ├── context_builder.py      Builds AGV_SYSTEM prompt; keyword fallback
│   ├── llm_client.py           Standalone LLM client (call_llm, retry logic)
│   └── json_repair.py          repair_and_parse; enforce_source_spans(); source_is_grounded(); source_confirms_value()
│
├── config/                     ALL generated — never edit manually
│   ├── field_levels.json       Matching rules per field
│   ├── vehicle_types.json      vt_map, VNA, text_overrides, keywords, shared_sheet_name
│   ├── scoring_weights.json    Scoring weights and rules
│   ├── nace_codes.json         NACE Prio-1 list + scope
│   ├── plausibility.json       Plausibility ranges for LLM values
│   ├── sqlite_schema.json      CREATE TABLE SQL + field type lists
│   ├── extraction_hints.json   tender_key → {hint, sheet} for all 51 extraction fields
│   ├── industry_readme.md      Domain knowledge (synced from Spec/)
│   ├── ap0_checksum.txt        MD5 of AP0 xlsx; triggers auto-regen if changed
│   └── prompts/
│       ├── basic_system.txt
│       ├── basic_template.txt
│       ├── contact_system.txt
│       ├── contact_template.txt
│       ├── nace_system.txt
│       ├── nace_template.txt
│       ├── vehicle_type_template.txt
│       ├── extraction_template.txt               Full combined template (fallback)
│       ├── extraction_template_forklift_agv.txt  Forklift-specific Pass 4b template
│       ├── extraction_template_tugger_agv.txt    Tugger-specific Pass 4b template
│       ├── extraction_template_mobile_amr.txt    AMR-specific Pass 4b template
│       ├── extraction_retry_system.txt
│       ├── extraction_retry_template.txt
│       └── extraction_system.txt                 Dead code — static fallback only
│
├── data/
│   ├── haystacked.db           SQLite supplier database
│   └── raw/                    Committed CSVs (versioned with each release)
│
├── tests/
│   ├── unit/
│   │   ├── test_matching_logic.py           U-M-01–U-M-28
│   │   ├── test_extraction_nulls.py         U-E-01–U-E-07
│   │   ├── test_source_span_enforcement.py  U-SS-01–U-SS-11 (enforce_source_spans, all 3 layers)
│   │   ├── test_source_is_grounded.py       U-SG-01–U-SG-12 (source_is_grounded)
│   │   ├── test_source_confirms_value.py    source_confirms_value boundary cases
│   │   ├── test_source_confirms_value_german.py  German locale / negative temperatures
│   │   ├── test_4c_direction_constants.py   _4C_EXTRACTION_DIRECTION completeness
│   │   ├── test_find_invalid_ap0_fields.py  _find_invalid_ap0_fields()
│   │   ├── test_validate_tender_values.py   U-V-01–U-V-08
│   │   ├── test_golden_extraction.py        U-GE-xx parametrized (≥5 tenders)
│   │   ├── test_json_repair_parser.py       U-J-01–U-J-10
│   │   ├── test_agv_keyword_fallback.py     U-K-01–U-K-08
│   │   └── test_data_loader.py              U-D-01–U-D-16
│   ├── integration/
│   │   └── test_llm_preflight.py            I-S-01–I-S-02 (requires live Ollama)
│   ├── tenders/                             Tender JSON fixtures + golden run files
│   └── benchmark_results/                   timestamped benchmark JSON files
│
├── docs/
│   ├── architecture.md         Detailed architecture reference
│   ├── TECHNICAL_REFERENCE.md  This document
│   ├── matching-rules.md       Operator reference for non-engineers
│   ├── ap0-change-guide.md     How to make changes via the AP0 xlsx
│   └── test-report-*.md        Timestamped test reports
│
├── airtable/
│   ├── ap2_schema.py           Fetches Airtable table IDs → airtable_schema_ids.json
│   └── ap2_import.py           Low-level Airtable import helpers
│
└── static/ templates/          Frontend assets and Jinja2 HTML templates
```

---

## 3. Single Source of Truth: AP0 xlsx

### 3.1 What lives in the xlsx

The file `Spec/haystacked_AP0_field_spec_v0_10.xlsx` is the authoritative source for every matching rule, scoring weight, extraction hint, and vehicle type definition. No field name, operator, or threshold appears in Python code that does not trace back to this file.

**Sheets and their roles:**

| Sheet | Content | Consumed by |
|---|---|---|
| SHARED – All AGV Types | Fields common to all vehicle types (payload, navigation, temperature, etc.) — Level, Operator, Data Type, Tender JSON Key, Allowed Values, Description, Scoring Weight | generate_all.py → field_levels.json, extraction_hints.json, scoring_weights.json, extraction_template.txt |
| Forklift AGV | Forklift-specific fields (lift height, aisle width, VNA, drive type, fork options) | Same pipeline |
| Tugger AGV | Tugger-specific fields (towing capacity, auto hitch, trailer count) | Same pipeline |
| Mobile AMR | AMR-specific fields (workflow, grid, picking mechanism) | Same pipeline |
| Vehicle Types | LLM output → canonical type map; VNA subtype flags; text override regexes; keyword lists; LLM classification guide | generate_all.py → vehicle_types.json, vehicle_type_template.txt |
| Entity Model | Three-layer data model: Company (L1), Product (L2), Base Model + Extension (L3) | generate_all.py → sqlite_schema.json |
| Field Fallbacks | Regex → forced tender_key value (only_if_null flag) | generate_all.py → vehicle_types.json → field_text_fallbacks |

**The Description column is critical.** It is the source for LLM extraction hints in `extraction_hints.json` and all generated prompt templates. Every word in a Description cell is injected into LLM prompts. Keep hints factual and pattern-focused. Never include numeric example values — a 7B model copies them as hallucinations ("prompt poisoning").

### 3.2 generate_all.py pipeline

`scripts/generate_all.py` reads both xlsx files and writes all runtime config. It is invoked:
- Manually: `python3 scripts/generate_all.py`
- Automatically: by `app.py` at startup when the AP0 xlsx MD5 checksum has changed
- Dry-run: `python3 scripts/generate_all.py --dry-run` (prints what would be written)

**Pipeline sequence:**

1. `read_field_levels(wb)` — iterates over all four data sheets; builds dict mapping field_name → {level, data_type, operator, tender_key, allowed_values}
2. `read_vehicle_types(wb)` — builds vt_map, vna_subtypes, text_overrides, keyword_map, llm_guide from Vehicle Types sheet; adds computed keys: scoring_bucket_map, vna_applicable_types, shared_sheet_name, agv_detection_keywords
3. `read_field_text_fallbacks(wb)` — reads Field Fallbacks sheet → list of {tender_key, regex, value, only_if_null}; merged into vehicle_types output
4. `read_scoring_weights(wb)` — reads Scoring Weight, Scoring Rule, Threshold 1, Threshold 2 columns per sheet → nested dict {bucket → field → {weight, rule, t1, t2}}
5. `read_extraction_schema(wb)` — builds list of {key, db_field, mandatory, hint, sheet} for all fields with a Tender JSON Key; this is the authoritative list of all 51 extractable fields
6. `read_sqlite_schema(wb)` — generates CREATE TABLE SQL from Entity Model sheet + AGV-type sheets; also extracts bool_fields, int_fields, float_fields, extensions_columns lists
7. `build_plausibility_config()` — converts PLAUSIBILITY_RANGES module constant (7 fields) → config dict [TO VERIFY: these ranges are still hardcoded in generate_all.py, not read from AP0]
8. `read_platform(platform_path)` — reads platform_config.xlsx: NACE codes (Prio-1 only), scope strings, basic extraction schema
9. `build_vehicle_type_template()` — generates Pass 4a user prompt from llm_guide entries
10. `build_extraction_template()` — generates Pass 4b templates with source instrumentation:
    - Called once with no `sheet_filter` → full combined template (backward compat)
    - Called once per DATA_SHEET with `sheet_filter=<sheet>` → type-specific template (SHARED + type fields only, 4a fields excluded)
    - For each numeric KO field (Float/Integer + KO_IF_LT/KO_IF_GT): adds `<field>_source` companion entry to field list AND JSON schema; appends operator-derived extraction direction to hint text
11. Writes all config files; prunes stale `extraction_template_*.txt` files; syncs industry_readme.md; writes extraction_hints.json; writes ap0_checksum.txt

**extraction_hints.json** is written by step 11: `{f["key"]: {"hint": f["hint"], "sheet": f["sheet"]} for f in extraction_schema}`. This is the flat lookup consumed by Pass 4c at runtime.

### 3.3 Generated files and their consumers

| File | Written by | Read by |
|---|---|---|
| `config/field_levels.json` | generate_all.py | src/matching.py (operators, allowed_values); app.py (_NUMERIC_KO_TENDER_KEYS, _AP0_CONSTRAINED_FIELDS, _4C_EXTRACTION_DIRECTION) |
| `config/vehicle_types.json` | generate_all.py | app.py (_VT_MAP_CFG, _VNA_CFG, _VT_OVERRIDES, _SHARED_SHEET, _FIELD_TEXT_FALLBACKS); src/matching.py (_SCORING_BUCKET_MAP); src/context_builder.py (AGV_KEYWORDS) |
| `config/scoring_weights.json` | generate_all.py | src/matching.py (Matcher._w) |
| `config/nace_codes.json` | generate_all.py | app.py (CATEGORY_LIST for Pass 3 prompt) |
| `config/plausibility.json` | generate_all.py | app.py (AGV_PLAUSIBILITY, _MM_TO_M_FIELDS) |
| `config/sqlite_schema.json` | generate_all.py | sync_airtable.py (CREATE TABLE SQL, _EXT_COLUMNS) |
| `config/extraction_hints.json` | generate_all.py | app.py (_extraction_hints, _NUMERIC_KO_FIELD_HINTS for Pass 4c) |
| `config/prompts/*.txt` | generate_all.py | app.py (_load_prompt) |
| `config/industry_readme.md` | synced from Spec/ by generate_all.py | src/context_builder.py (build_system_context) |
| `config/ap0_checksum.txt` | generate_all.py | app.py (_check_and_regen) |

### 3.4 How to make a rule change (step-by-step)

1. Open `Spec/haystacked_AP0_field_spec_v0_10.xlsx`
2. Find the field row in the relevant sheet (SHARED, Forklift AGV, Tugger AGV, or Mobile AMR)
3. Change the Level, Matching Operator, Allowed Values, or Description cell as needed
4. Save the xlsx
5. Run: `python3 scripts/generate_all.py`
6. Check the console output for CONSISTENCY WARNINGS
7. Run: `pytest tests/` — all tests should pass
8. Restart the app (or rely on startup auto-regen if already running)

**No Python changes are needed for most rule changes.** Python changes are only needed when:
- Adding a new operator type not yet in the OPERATORS dict in src/matching.py
- Adding a new scoring rule type not yet in the Matcher scoring loop
- Changing the plausibility ranges (still hardcoded in PLAUSIBILITY_RANGES in generate_all.py)

---

## 4. Data Layer

### 4.1 Airtable → SQLite Sync (sync_airtable.py)

**Tables synced:**

| Airtable table | SQLite table | Notes |
|---|---|---|
| companies | companies | L1 — supplier companies |
| products | products | L2 — individual AGV products |
| base_models | base_models | L3 — OEM hardware models |
| extensions | base_model_extensions | L3 — technical specs per model and AGV type |

**Sync modes:**
- Live mode (default): fetches from Airtable REST API with pagination and rate-limit retry (429 → wait 30s, 3 attempts). Requires `.env` with `AIRTABLE_TOKEN` and `AIRTABLE_BASE_ID`.
- Local mode (`--local`): skips API, reads from `data/raw/*.csv`. No credentials needed.

The sync is idempotent: tables are dropped and recreated from scratch on each run. Multi-select fields are stored as pipe-separated strings. Boolean fields are stored as 0/1 integers. The CREATE TABLE SQL comes from `config/sqlite_schema.json` — `sync_airtable.py` never hardcodes schemas.

`_EXT_COLUMNS` (the ordered list of extension table column names) is also read from `sqlite_schema.json` (key `extensions_columns`). This means column order for INSERT statements is always in sync with the generated schema.

**Frequency / trigger:** Manual. Run after any Airtable data change. Git-committed CSVs act as the dataset for contributors without Airtable access.

**Error handling:** On connection error, retries 3 times. On 429, waits 30 seconds. On persistent failure, exits with an error message. On schema drift (AP0 field added but not yet in SQLite), `generate_all.py` logs a CONSISTENCY WARNING.

### 4.2 SQLite Schema

Four tables. Schema generated from AP0 Entity Model sheet.

```
companies             L1 — company_id (PK), company_name, country, certifications_generic, ...
products              L2 — product_id (PK), company_id (FK), base_model_id (FK), agv_type, active, ...
base_models           L3 — base_model_id (PK), oem_company_id (FK), ...
base_model_extensions L3 — extension_id (PK), base_model_id (FK), agv_type, [all AP0 extension fields], extra_fields
```

The `base_model_extensions` table contains all technical specification fields from all four AP0 data sheets (SHARED + type-specific). Fields from the Forklift sheet live in the same wide table as Tugger and AMR fields — most are NULL for inapplicable vehicle types.

### 4.3 Data Loader (src/data_loader.py)

`load_suppliers()` executes one SQL query:

```sql
SELECT p.product_id, p.company_id, p.base_model_id, p.product_name, p.agv_type,
       p.product_description, p.reference_count, p.min_project_value_eur,
       p.max_project_value_eur, p.lead_time_weeks, p.distribution_model,
       p.is_oem_product, p.service_coverage, p.active,
       c.company_name, c.country, c.languages_spoken, c.certifications_generic,
       bme.*
FROM products p
JOIN companies c ON p.company_id = c.company_id
JOIN base_model_extensions bme ON p.base_model_id = bme.base_model_id
WHERE p.active = 1
```

Each row is parsed into `SupplierRecord(product=Product(...), extension=Extension(...))`. Parse helpers:
- `_parse_multiselect(val)`: None or "" → []; otherwise splits on `|`
- `_parse_bool(val)`: None → None; 0/"false"/"no" → False; 1/"true"/"yes" → True
- `_parse_int(val)`: None or "" → None; float strings handled (int(float("1500.0")) = 1500)
- `_parse_float(val)`: None or "" → None; NaN → None

The `SupplierRecord` is the only representation of supplier data used by the matching engine. Company fields are denormalized into `Product` at load time (company_name, country, languages_spoken, certifications_generic).

### 4.4 Key Invariants

**None ≠ 0 and None ≠ []**

`None` in any field means the value has not been entered in Airtable. It never means the supplier lacks that capability. The null rule (LL-06) in the matching engine enforces this: `None` on either side of a numeric or categorical K.O. comparison never triggers disqualification.

Corollary: do not use `0` or `[]` to represent unknown values. A supplier with `reference_count=None` has unknown references — not zero references.

---

## 5. PDF Ingestion & LLM Pipeline

### 5.1 PDF Text Extraction

`extract_text_from_pdf(pdf_bytes)` uses `pdfplumber`:
- Opens PDF from bytes (no temp file)
- Extracts text page by page; skips pages with no text
- Joins pages with double newline
- Caps at 50,000 characters (~14,000 tokens); appends truncation marker if cut
- Logs page count, character count, and pages-with-text count

The 50,000-char cap fits comfortably within the 32,768-token context window (configured via `num_ctx=32768` in all Ollama calls).

### 5.2 LLM Passes (in sequence)

All calls go through `call_ollama(system, user, label)` which:
- Posts to `http://localhost:11434/api/generate` via httpx (timeout=180s)
- Sets `stream=False`, `temperature=0.0`, `num_predict=4096`, `num_ctx=32768`
- Logs system size, prompt size, elapsed time, and response size
- Returns raw string response

#### Pass 1 — basic (always runs)

| Element | Value |
|---|---|
| System | `config/prompts/basic_system.txt` |
| Template | `config/prompts/basic_template.txt` |
| Placeholder | `{text}` ← full PDF text |
| Response schema | JSON object |
| Key fields | buyer, project_name, project_location, tender_date, deadline, contact_name, contact_email, contact_phone, buyer_industry, tender_category, is_agv_amr (bool), summary, missing_info |

After parsing, string "null" values are converted to Python None. Then keyword fallback: if `is_agv_amr` is still False but the first 5,000 chars contain any keyword from `_AGV_DETECT_KWS` (loaded from `vehicle_types.json` → `agv_detection_keywords`), `is_agv_amr` is forced to True.

#### Pass 2 — contact (conditional)

Runs only if all three contact fields (contact_name, contact_email, contact_phone) are missing AND the document is longer than 6,000 characters.

| Element | Value |
|---|---|
| System | `config/prompts/contact_system.txt` |
| Template | `config/prompts/contact_template.txt` |
| Placeholder | `{text}` ← last 4,000 chars of document |
| Response schema | JSON object |
| Key fields | contact_name, contact_email, contact_phone, deadline, tender_date |

Only fills gaps — never overwrites values already found in Pass 1.

#### Pass 3 — nace (always runs)

| Element | Value |
|---|---|
| System | `config/prompts/nace_system.txt` |
| Template | `config/prompts/nace_template.txt` |
| Placeholders | `{tender_category}`, `{buyer_industry}`, `{category_list}` |
| Response schema | JSON with nace_tender, nace_tender_name, priority, confidence, in_scope |

`{category_list}` is a newline-separated list of NACE Prio-1 entries loaded from `config/nace_codes.json`. Falls back to tender_category = "unknown service" and buyer_industry = "unknown industry" if Pass 1 did not find them.

If `in_scope=false`, processing continues (matching still runs) but the result is flagged in the frontend.

If `is_agv_amr=false`, processing stops after Pass 3. Total: 2–3 calls.

#### Pass 4a — vehicle type (conditional: is_agv_amr=true)

| Element | Value |
|---|---|
| System | `AGV_SYSTEM` = `build_system_context()` |
| Template | `config/prompts/vehicle_type_template.txt` |
| Placeholder | `{text}` ← full PDF text |
| Response schema | `{"required_vehicle_type": null, "required_vna": null}` |

`build_system_context()` concatenates:
1. `config/industry_readme.md` (full domain knowledge)
2. KO and COND_KO field names from `config/field_levels.json`
3. Nine critical extraction rules (Rule 8: conservative values; Rule 9: anti-hallucination)

After parsing, AP0 validation runs on `required_vehicle_type` only. Up to 2 correction retries (`agv_4a_correction1/2`) if the value is not in the allowed list. If still invalid after 3 attempts, a warning is emitted and keyword fallback is used.

Post-4a: vehicle type normalization (vt_map lookup, then text_overrides regex scan) sets `canonical_agv_type` and `is_vna_subtype`.

#### Pass 4b — batch extraction (conditional: is_agv_amr=true)

| Element | Value |
|---|---|
| System | `AGV_SYSTEM` |
| Template | `config/prompts/extraction_template_<type>.txt` (type-specific) or `extraction_template.txt` (fallback) |
| Placeholders | `{text}`, `{vehicle_type}`, `{vna_context}` |
| Response schema | JSON object with ~40 fields + `<field>_source` for each numeric KO field |

The type-specific template is selected via `_AGV_TYPE_TEMPLATES` dict (built from `vehicle_types.json` → `vt_prompt_map`). Template choice is data-driven — no type names hardcoded in Python.

AP0 validation (`_find_invalid_ap0_fields`) runs on all 4b fields except those already validated in 4a (loaded from `vehicle_types.json` → `4a_fields`). Up to 2 correction retries (`agv_4b_correction1/2`).

Numeric KO fields have automatic `<field>_source` companion keys in the template (injected by `build_extraction_template()` during config generation). The LLM must populate both or the source-span guard will null the value.

#### Pass 4c — per-field extraction (conditional: is_agv_amr=true, runs after 4b)

Pass 4c is a collection of individual LLM calls, one per numeric KO field. It is not driven by a pre-generated template file — prompts are constructed inline in `app.py`.

**Field selection:** `_4c_fields` = fields in `_NUMERIC_KO_FIELD_HINTS` where `sheet` is either `_SHARED_SHEET` or `canonical_agv_type`. This scopes the pass to fields relevant to the detected vehicle type.

**Per-field prompt structure:**

```
Vehicle type: {canonical_agv_type}. {vna_context}

Find the value of '{field_key}' in the tender document.

Field meaning: {hint_stripped_of_null_rule}

Step 1: Scan the document for any sentence, table cell, or labelled line
        that states this value directly.
Step 2: If found, copy it verbatim as the source and extract the number
        (note: commas in numbers are thousands separators — '1,000' means 1000).
        {extraction_direction}
Step 3: If not found anywhere in the document text, output null for both
        — do NOT infer from vehicle type, warehouse layout, or industry standards.

DOCUMENT:
{text}

Output ONLY this JSON:
{"<field_key>": <number or null>, "<field_key>_source": "<verbatim quote or null>"}
```

Key design decisions:
- **NULL RULE stripped from hint**: the system prompt already contains the anti-hallucination rule. Including the NULL RULE in the per-field hint would triple-reinforce null-bias and over-suppress valid values.
- **Extraction direction from operator**: `_4C_EXTRACTION_DIRECTION[field_key]` is derived from `field_levels.json` — KO_IF_LT → "extract the MAXIMUM", KO_IF_GT → "extract the MINIMUM". No domain logic hardcoded.
- **Positive framing**: "Find the value of" rather than "Extract if present" — reduces the LLM's tendency to defer to the null path.
- **Quote-first steps**: Step 1 finds the source sentence before Step 2 extracts the number — this mirrors human reasoning and reduces fabrication.

**Result handling:**
- If 4c returns a non-null value → stored in `agv_criteria[field_key]` and `agv_criteria[field_key+"_source"]`; `_4c_count` incremented
- If 4c returns null → field added to `_4c_abstained`; 4b value is preserved for now
- If 4c fails (parse error, call error, field absent from dict) → field added to `_4c_abstained`

### 5.3 Source-Span Hallucination Guard

After Pass 4c, `app.py` calls `enforce_source_spans(agv_criteria, document_text, _NUMERIC_KO_TENDER_KEYS, _4c_abstained)` from `src/json_repair.py`. This pure function (no async, no I/O) applies three enforcement layers per field; the first match nulls the value and stops:

```
Layer 1: source absent/empty → null (no citation = inference)
Layer 0: source present but not grounded in real document → null
Layer 2 (4c abstentions only): source's own digit doesn't confirm value → null
```

Returns `(agv_criteria, messages)` — messages is a list of human-readable log strings surfaced as SSE `log` events.

**Layer 1 — missing source (always active)**

If `<field>_source` is absent or null for a non-null field value: value is set to null. No citation = the LLM inferred the value rather than reading it from the document.

**Layer 0 — source not grounded in the real document (always active)**

`source_is_grounded(value, source, document)` in `src/json_repair.py`:

Two binary conditions must both hold:
1. **Anchor**: value's digit-string (locale-aware via `_interpret_number_token()`, with ×1000/÷1000 unit-scale variants) must occur somewhere in the real document text.
2. **Co-location**: at least one distinctive content word from the source quote (length > 3, not in the DE/EN function-word set `_FUNCTION_WORDS`) must appear within `_GROUNDING_WINDOW_CHARS` (80 chars) of an anchor occurrence.

Zero values always pass (LL-06). Non-numeric values return True (field-agnostic). The 80-character window is a corpus-derived text-layout property — not a calibrated parameter.

**Real regression case (CompanyX, 2026-06-16):** The model fabricated 7 numeric KO values, each paired with a self-consistent but document-absent quote. Examples:
- `required_max_lift_height_m=4.8` with quote "The maximum lift height of the AGVs is up to 4.8 m." — the digit "4.8" does not appear anywhere in the 17,900-character CompanyX.pdf text.
- `required_temp_max_c=40` with quote "from -25 °C to +40 °C." — "40" does occur in the document (in an unrelated shelf/transfer-point table), but none of the quote's content words ("operating", "temperature", "range") appear within 80 characters of those occurrences. Anchor-only detection would false-accept this; co-location correctly rejects it.

All 7 fabrications are now pinned as regression tests in `tests/unit/test_source_is_grounded.py` (U-SG-07, U-SG-08) and `tests/unit/test_source_span_enforcement.py` (U-SS-04, U-SS-11).

**Layer 2 — abstention + numeric mismatch (scoped to 4c abstentions)**

Triggered only when both conditions hold:
1. The field is in `_4c_abstained` (Pass 4c returned null or failed)
2. `source_confirms_value(value, source_text)` in `src/json_repair.py` returns False

`source_confirms_value(value, source_text)`:
- Uses `_interpret_number_token()` for locale-aware number parsing (handles "3,4" → 3.4, "1,000" → 1000)
- Returns True if: value is zero; direct float match; value × 1000 in source; value ÷ 1000 in source
- Field-agnostic: no field names, no domain knowledge
- Note: this function was previously named `_source_confirms_value()` in `app.py`; it was extracted to `src/json_repair.py` and made public in this branch

**Why three layers, and why Layer 0 runs unconditionally:**
- Layer 1 catches absent citations — easy, high confidence
- Layer 0 catches fabricated citations (value + quote both fabricated) — the fabricated quote is internally consistent but absent from the document. This is unconditional because a citation not in the real document is always wrong, regardless of what 4c did.
- Layer 2 catches a narrower case: the source quote is genuinely in the document (L0 passes) but the quote's own digit doesn't spell out the extracted value. This could be a legitimate paraphrase — so the 4c abstention is required as additional evidence before nulling.

### 5.4 Post-LLM Validation

#### validate_tender_values() — src/matching.py

Checks every Dropdown and Multi-Select field in the LLM output against `allowed_values` from `field_levels.json`. Case-insensitive substring matching: `"pallet eur"` matches `"Pallet EUR"`. Values not matching are set to None.

Skipped fields (normalized separately by app.py after validation): `required_vehicle_type`, `required_vna`, `required_outdoor`.

#### validate_agv_criteria() — app.py

Checks numeric fields against plausibility ranges from `config/plausibility.json`:

| Field | Range | Unit | mm→m? |
|---|---|---|---|
| required_weight_capacity_kg | 100 – 50,000 | kg | No |
| required_max_speed_ms | 0.3 – 5.0 | m/s | No |
| required_min_aisle_width_m | 0.5 – 5.0 | m | Yes (if > 10) |
| required_max_lift_height_m | 0.5 – 30.0 | m | Yes (if > 10) |
| required_temp_min_c | -40 – 30 | °C | No |
| required_temp_max_c | 0 – 60 | °C | No |
| required_quantity | 1 – 10,000 | units | No |

mm→m conversion: if a field has `mm_to_m: true` and the value exceeds 10, the function divides by 1000 and checks if the result is in range. If so, uses the converted value and logs a warning. Otherwise, sets to None.

#### Field text fallbacks

After both validation steps, `app.py` applies regex-driven overrides from `_FIELD_TEXT_FALLBACKS` (loaded from `vehicle_types.json`). For each fallback rule `{tender_key, regex, value, only_if_null}`: if the full PDF text matches the regex and (`only_if_null` is False or the field is currently None), the field is set to the configured value. These rules allow AP0-driven overrides for cases where the LLM consistently misses a value that is reliably detectable by regex.

### 5.5 TenderRequirements

`TenderRequirements` (src/matching.py) wraps the raw LLM output dict. The matching engine calls `req.get("navigation_type")` using the AP0 `db_field` name, and the class resolves it to the `tender_key` ("required_navigation"), looks up the value in the raw dict, and coerces it to the AP0 `data_type`.

```python
def get(self, field: str):
    meta = _field_levels.get(field, {})
    tender_key = meta.get("tender_key", field)
    raw_val = self.raw.get(tender_key) or self.raw.get(field)
    data_type = meta.get("data_type", "Text")
    coerce = _COERCE.get(data_type, lambda v: v)
    return coerce(raw_val)
```

Type coercions: Float → `_f()`, Integer → `_i()`, Multi-Select → `_ms()` (splits on `|` or `,`), Boolean → identity, Dropdown → identity, Text → identity.

---

## 6. Prompt System

### 6.1 Prompt File Inventory

All prompt files live in `config/prompts/`. All are generated by `generate_all.py`. Never edit manually.

| File | Pass | System or Template | Key placeholders |
|---|---|---|---|
| `basic_system.txt` | 1 | System | — |
| `basic_template.txt` | 1 | Template | `{text}` |
| `contact_system.txt` | 2 | System | — |
| `contact_template.txt` | 2 | Template | `{text}` |
| `nace_system.txt` | 3 | System | — |
| `nace_template.txt` | 3 | Template | `{tender_category}`, `{buyer_industry}`, `{category_list}` |
| `vehicle_type_template.txt` | 4a | Template | `{text}` |
| `extraction_template_forklift_agv.txt` | 4b | Template | `{text}`, `{vehicle_type}`, `{vna_context}` |
| `extraction_template_tugger_agv.txt` | 4b | Template | `{text}`, `{vehicle_type}`, `{vna_context}` |
| `extraction_template_mobile_amr.txt` | 4b | Template | `{text}`, `{vehicle_type}`, `{vna_context}` |
| `extraction_template.txt` | 4b fallback | Template | `{text}` |
| `extraction_retry_system.txt` | 4b retry | System | — |
| `extraction_retry_template.txt` | 4b retry | Template | `{text}` |
| `extraction_system.txt` | — | Static fallback | — |

Pass 4c prompts are constructed inline in `app.py` (not from files) to allow per-field parameterization.

The AGV extraction system prompt (`AGV_SYSTEM`) is not a file — it is built by `build_system_context()` in `src/context_builder.py` at startup.

### 6.2 _fill() Function

```python
def _fill(template: str, **kwargs) -> str:
    for key, value in kwargs.items():
        template = template.replace("{" + key + "}", str(value) if value is not None else "")
    return template
```

Uses explicit string replacement rather than Python's `.format()` so that JSON template literals like `{"field":null}` in the prompt are never interpreted as format specifiers. None values become empty strings.

### 6.3 Context Builder (src/context_builder.py)

`build_system_context()` assembles the AGV extraction system prompt (`AGV_SYSTEM`) used for all AGV passes (4a, 4b, 4c):

1. Loads `config/industry_readme.md` (domain knowledge: AGV/AMR classification, VNA, G2P, battery types, VDA 5050, etc.). Falls back to a hard-coded brief summary if the file is missing.
2. Builds a field section listing all KO and COND_KO fields with their level tags.
3. Appends nine numbered critical matching rules:
   - Rules 1–7: domain-specific extraction guidance
   - Rule 8: CONSERVATIVE VALUE EXTRACTION — extract worst-case values (maximum for minimum-capability fields, minimum for maximum-constraint fields)
   - Rule 9: ANTI-HALLUCINATION — every non-null value must be traceable to an exact sentence; never infer from warehouse type, AGV type, or domain defaults; do not read numbers from dates, filenames, or version strings

`agv_type_keyword_fallback(text)` is also in context_builder.py. It scans the first 5,000 chars of the document against the `keyword_map` from `vehicle_types.json` and returns the canonical type with the most keyword hits (or None if no hits).

### 6.4 Source Instrumentation in Templates

`build_extraction_template()` in `generate_all.py` automatically adds `<field>_source` companion entries for each numeric KO field:

```
- required_weight_capacity_kg: ... CONSERVATIVE EXTRACTION: ...
- required_weight_capacity_kg_source: The EXACT verbatim sentence or phrase from the document
  that contains the value above. null if the value was not found explicitly in the
  document — in which case required_weight_capacity_kg MUST also be null.
```

This instrumentation is also reflected in the JSON schema at the end of the template:
```json
{"required_weight_capacity_kg":null,"required_weight_capacity_kg_source":null,...}
```

---

## 7. Matching Engine (src/matching.py)

### 7.1 Architecture

The matching engine is a pure rule interpreter. It reads all rules from `config/field_levels.json` at module load time. No supplier names, AGV type strings, numeric thresholds, or domain decisions appear in the Python source.

The module-level docstring explicitly states this and lists the permitted operators. Any addition of domain knowledge to this file is an architecture violation.

### 7.2 Operator Reference

All operators are registered in the `OPERATORS` dict and called by name from `field_levels.json`.

#### KO_IF_LT

**Semantics:** K.O. if supplier value < tender value.  
**Use cases:** payload capacity, lifting height, towing capacity, battery runtime.  
**Null behavior:** None on either side → no K.O. (LL-06).  
**Example:** tender `required_weight_capacity_kg=2000`, supplier `max_payload_kg=1000` → K.O. ("1000.0 < required 2000.0").

#### KO_IF_GT

**Semantics:** K.O. if supplier value > tender value.  
**Use cases:** aisle width (supplier needs wider aisle than available), minimum temperature (supplier's lowest rated temp is higher than site minimum).  
**Null behavior:** None on either side → no K.O.  
**Example:** tender `required_min_aisle_width_m=1900` (mm), supplier `min_aisle_width_mm=2400` → K.O. ("needs 2400, only 1900 available").

#### KO_IF_NEQ

**Semantics:** K.O. if supplier value ≠ tender value (case-insensitive string comparison).  
**Use cases:** agv_type (exact type match required).  
**Null behavior:** None on either side → no K.O.  
**Lists:** if either value is a list, returns no K.O. (use KO_SUBSET instead).

#### KO_BOOL_REQUIRED

**Semantics:** K.O. only if tender="required" AND supplier=False.  
**Use cases:** outdoor_capable, infrastructure_required, forks_free_floating, multi_load_compatibility.  
**Null behavior:** supplier=None → no K.O. (LL-06: unknown ≠ absent).  
**Example:** tender `required_outdoor="required"`, supplier `outdoor_capable=False` → K.O. ("required but supplier does not support it"). Supplier `outdoor_capable=None` → no K.O.

#### KO_BOOL_EXCLUSIVE

**Semantics:** Bidirectional boolean K.O.  
**Use cases:** vna_capable (the only field currently using this operator).  
**Behavior:**
- tender="required" AND supplier ≠ True → K.O. (VNA required but supplier cannot do VNA)
- tender="not_required" AND supplier = True → K.O. (VNA machine unsuitable for standard-aisle tender)
- tender=None → no K.O.
**Null supplier behavior:** None is treated as not True, so tender="required" + supplier=None → K.O. (LL-10 exception to LL-06 for VNA).

#### KO_SUBSET

**Semantics:** K.O. if no overlap between tender list and supplier list (substring matching).  
**Use cases:** navigation_type, load_type, special_fork_option.  
**Empty list behavior:** empty on either side → no K.O. (no constraint).  
**Substring matching:** "SLAM" matches "Natural Feature (SLAM)"; "Laser" matches "Laser Reflector".  
**Example:** tender `required_navigation=["Laser Reflector"]`, supplier `navigation_type=["Natural Feature"]` → K.O.

### 7.3 Null Rule (LL-06)

**Rule:** None on either side of a KO_IF_LT, KO_IF_GT, KO_IF_NEQ, KO_BOOL_REQUIRED, or KO_SUBSET comparison → no K.O.

**Exception (LL-10):** KO_BOOL_EXCLUSIVE with tender="required" + supplier=None → K.O. None is treated as not-capable for the VNA gate.

**Null penalty:** When a tender specifies a numeric KO requirement (level=KO, operator KO_IF_LT or KO_IF_GT) but the supplier has None for that field, a -15 pt penalty is applied instead of disqualification. This ranks confirmed suppliers above unverified ones without excluding them entirely.

```python
NULL_KO_PENALTY = 15  # points deducted
# Applied after KO phase, before scoring
for field, meta in _field_levels.items():
    if meta.get("level") != "KO" or meta.get("operator") not in {"KO_IF_LT", "KO_IF_GT"}:
        continue
    if req.get(field) is not None and _supplier_val(ext, prod, field) is None:
        add_score(-NULL_KO_PENALTY, f"{field}_null_penalty", None)
```

### 7.4 Scoring

The `Matcher` class uses `config/scoring_weights.json` organized into buckets:

| Bucket key | Applied to |
|---|---|
| `default` | All vehicle types (common fields: reference_count, lead_time_weeks, vda5050_compatible, etc.) |
| `forklift_specific` | Forklift AGV additional fields (drop_accuracy_lat_mm, stacking_capability, etc.) |
| `tugger_specific` | Tugger AGV additional fields |
| `amr_specific` | Mobile AMR additional fields |

The `scoring_bucket_map` in `vehicle_types.json` maps canonical type names to bucket keys. Weights for fields in `default` are always evaluated; the type-specific bucket is added on top.

**Scoring rules:**

| Rule | Behavior |
|---|---|
| `bool` | Full pts if supplier value is True |
| `bool_cond` | Full pts if True AND tender marks field as "required"; otherwise `max(0, pts-2)` |
| `proportional` | Scales linearly from 0 to pts based on `val / t1` (capped at t1) |
| `threshold_lower` | Full pts if val ≤ t1 |
| `threshold_upper` | Full pts if val ≥ t1; half pts otherwise |
| `tiered_lower` | Full pts if val ≤ t1; half pts if val ≤ t2; 0 otherwise |
| `tiered_upper` | Full pts if val ≥ t1; half pts if val ≥ t2; 0 otherwise |
| `nonempty` | Full pts if value is truthy (non-None, non-empty) |

### 7.5 Vehicle Type Logic

**Layer 1 — vt_map normalization (from vehicle_types.json):**

The LLM may return strings like "vna", "reach truck", "agv", or "autonomous mobile robot". All are mapped to exactly one canonical type:

| LLM output (case-insensitive) | Canonical |
|---|---|
| "forklift agv", "forklift", "counterbalanced", "reach truck", "vna", "very narrow aisle", "agv" | Forklift AGV |
| "tugger agv", "tugger" | Tugger AGV |
| "mobile amr", "amr", "underride amr", "underride", "autonomous mobile robot" | Mobile AMR |

If the LLM output does not match any vt_map key, `agv_type_keyword_fallback()` scans the first 5,000 chars of the document.

**Layer 2 — text_overrides regex scan (from vehicle_types.json):**

Two patterns currently active:
- `\bVNA\b` → forces canonical_agv_type="Forklift AGV" and is_vna_subtype=True
- `(?i)schmalgangstapler` → same

The text_overrides are checked against the full document text and can override the LLM's Pass 4a result.

**VNA logic post-normalization:**

After both layers, the VNA flag is set:
- `is_vna_subtype=True`: `required_vna = "required"`
- canonical_agv_type in `vna_applicable_types` ("Forklift AGV") but not VNA: `required_vna = "not_required"`
- All other types: `required_vna = None`

### 7.6 Match Result Structure

`Matcher.match()` returns two lists: `(qualified[:top_n] + disqualified[:top_n], all_results)`.

`to_dict()` on a MatchResult returns:

```python
{
    "product":         str,
    "company":         str,
    "score":           int,
    "max_score":       int,
    "rank":            int,
    "disqualified":    bool,
    "disqualified_by": list[str],   # KO failure messages
    "score_details":   list[{"field": str, "points": int, "value": Any}],
    "agv_type":        str,
    "reasons":         list[str],   # "+N pts" summaries for positive scores
    "knockouts":       list[str],
    "website":         str,
    "origin":          str,
    "description":     str,
    "navigation":      str,         # pipe-joined navigation types
    "max_payload_kg":  float | None,
    "lifting_height_mm": int | None,
    "min_aisle_width_mm": int | None,
    "max_speed_ms":    float | None,
    "vda5050":         bool | None,
    "battery_runtime_h": float | None,
    "autonomous_charging": bool | None,
    "reference_count": int | None,
    "lead_time_weeks": int | None,
    "service_coverage": list[str],
}
```

---

## 8. API & Frontend Integration

### 8.1 FastAPI Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Serves `templates/index.html` (Jinja2) |
| POST | `/analyze` | Main analysis endpoint; accepts `multipart/form-data` with `file` field; returns SSE stream |
| POST | `/match` | Direct matching API; accepts JSON body with tender requirements; returns top + all results |
| GET | `/db-status` | Reports whether SQLite is loaded and how many suppliers are active |
| GET | `/api/field-meta` | Returns AP0 field metadata (label, tender_key, level, data_type, operator) for all fields |
| GET | `/health` | Reports Ollama reachability and model availability |

### 8.2 SSE Streaming

The `/analyze` endpoint uses `StreamingResponse(stream(), media_type="text/event-stream")`. Events are emitted progressively throughout processing:

```
event: step
data: {"id": "upload", "status": "done", "message": "'doc.pdf' empfangen"}

event: step
data: {"id": "extract", "status": "running", "message": "Text wird extrahiert…"}

event: log
data: {"message": "PDF-Größe: 245 KB"}

event: step
data: {"id": "agv", "status": "running", "message": "Pass 4c: 8 numerische Felder einzeln…"}

event: result
data: { "buyer": "...", "agv_criteria": {...}, "matches": [...], "matches_all": [...] }
```

| Event type | Description | Frontend visibility |
|---|---|---|
| `step` | Progress update (id, status: running/done/error, message) | Shown as progress indicator |
| `log` | Diagnostic detail including AP0 filter warnings and source-span guard nullings | Hidden by default |
| `result` | Full final payload | Rendered as match results |
| `error` | Fatal error, processing stops | Shown as error state |
| `warning` | Non-fatal field-level warning (e.g. AP0 violation after 3 retries) | Shown inline |

---

## 9. Test Strategy

### 9.1 Existing Tests

**`tests/unit/test_matching_logic.py`** — 28 tests (U-M-01 to U-M-28)

Covers: KO_IF_LT payload check; null payload not disqualified; wrong AGV type; navigation no match; COND_KO outdoor not-required; COND_KO outdoor required + False; COND_KO outdoor required + None; forks_free_floating required; scoring reference_count ranking; null reference_count; VDA5050 preferred no filter; empty tender returns all; VNA KO_BOOL_EXCLUSIVE (both directions, pass, null); special_fork_option (null tender, mismatch, match); null KO penalty fires; null KO penalty absent when tender null; VDA5050 not double-counted; no hardcoded preferred-bonus labels; service_coverage KO_SUBSET DACH vs EU-only (U-M-14 — uses correct tender_key `required_service_coverage`).

**`tests/unit/test_extraction_nulls.py`** — 7 tests (U-E-01 to U-E-07)

Covers: Dragonfly.pdf golden values (lift height must be null, aisle width 1.9m, payload 1000kg, VNA required); null lift height survives validate_agv_criteria; `source_confirms_value()` boundary conditions (direct match, thousands separator, mm/m scale, false positive guard, zero); `_NUMERIC_KO_TENDER_KEYS` non-empty and contains expected keys.

**`tests/unit/test_source_span_enforcement.py`** — 11 tests (U-SS-01 to U-SS-11). Imports `enforce_source_spans()` from `src/json_repair.py` directly.

Covers: Layer 1 (source None; source empty string); Layer 0 (fabricated CompanyX lift-height value with self-consistent but document-absent quote nulled; genuine CompanyX weight with paraphrased quote preserved; German decimal comma grounded; PDF private-use-area glyph does not merge temperature numbers); Layer 2 (digit-free but grounded quote + 4c abstained → nulled; same quote without abstention → preserved); None value skipped entirely; documented gradient/10 residual regression.

Note: this file previously contained a hand-maintained inline copy of the enforcement loop. It now imports the real production function — ensuring tests cannot drift from the code that actually runs.

**`tests/unit/test_source_is_grounded.py`** — 12 tests (U-SG-01 to U-SG-12). All cases use real value/quote/document triples from the tender corpus.

Covers: genuine verbatim quote (Dragonfly); genuine paraphrased quote (CompanyX); German decimal comma (Nordlicht "3,4 m"); unit-scale mismatch meter/mm (Dragonfly); PDF glyph artifact in temperature range (Mama); bullet-glyph noise near weight value (Mama); all 7 CompanyX fabrications rejected as a batch (U-SG-07); temp_max=40 anchor-present-but-colocation-fails case (U-SG-08, the anchor-only false-positive trap); lift-height=4.8 anchor-absent case (U-SG-09); zero always grounded; empty/None source; non-numeric value passthrough.

**`tests/unit/test_source_confirms_value.py`** / **`test_source_confirms_value_german.py`** — `source_confirms_value()` boundary tests (function is in `src/json_repair.py`).

Covers: direct numeric match; thousands-separator comma; mm/m unit scale (×1000, ÷1000); false positive guard (different number); German decimal comma (`3,4` interpreted as `3.4`); negative temperatures.

**`tests/unit/test_validate_tender_values.py`** — AP0 allowed-values filter tests.

Covers: valid Dropdown values pass; invalid values nulled; Multi-Select intersection filtering; case-insensitive substring matching.

**`tests/unit/test_4c_direction_constants.py`** — Pass 4c direction constant tests.

Covers: `_4C_EXTRACTION_DIRECTION` non-empty; KO_IF_LT fields map to "MAXIMUM"; KO_IF_GT fields map to "MINIMUM"; no unknown direction values.

**`tests/unit/test_find_invalid_ap0_fields.py`** — AP0 constraint violation detection tests.

**`tests/unit/test_json_repair_parser.py`** — 10 tests (U-J-01 to U-J-10)

Covers: clean JSON; markdown fences; prose before JSON; string "null"; string booleans; truncated JSON; unescaped newlines; completely unparseable (raises ValueError); stray brace in trailing prose (Stage 0 brace-balance); nested braces.

Tests import from `src.json_repair` — the single canonical implementation used by app.py, llm_client.py, and tests.

**`tests/unit/test_agv_keyword_fallback.py`** — 8 tests (U-K-01 to U-K-08)

Covers: VNA, Schmalgangstapler, Routenzug, milk run, AMR, goods-to-person, no keywords (returns None), 5,000-char boundary (keyword beyond 5,000 chars not detected).

**`tests/unit/test_data_loader.py`** — 14 tests (U-D-01 to U-D-16, some IDs skipped)

Covers: pipe-separated multiselect; empty string → []; None → []; bool parsing (int, string, None); int/float parsing; empty string → None; UUID format; embedded comma in multiselect; whitespace trimming; NaN → None.

**`tests/unit/test_golden_extraction.py`** — Parametrized golden-run regression test.

Loads all `tests/tenders/tender_XXX.json` fixtures that have `golden_extraction` or `expected_out_of_scope=true` and compares against the corresponding `golden_run_tender_XXX.json` output files. As of 2026-06-17, covers 5 fixtures (tender_001 Nordlicht, tender_002 Dragonfly, tender_003 OeA-199-25 out-of-scope, tender_004 Mama, tender_005 CompanyX). Includes a floor guard asserting at least 5 fixtures are always collected. Covers all 8 numeric KO fields per tender (not just a subset). CompanyX (tender_005) is the key regression case: all 7 fabricated fields must be null in the golden run.

**`tests/integration/test_llm_preflight.py`** — 2 tests (I-S-01, I-S-02)

Session-scoped fixture checks Ollama is reachable and the model is in the manifest before any test runs. On failure, `pytest.exit()` aborts the entire integration suite.

- I-S-01: model in Ollama manifest
- I-S-02: model responds to a minimal prompt with parseable JSON

Requires a running Ollama instance with qwen2.5:7b. Run separately: `pytest tests/integration/ -v`.

### 9.2 Coverage Assessment

**Well covered:**
- All six matching operators across KO and COND_KO scenarios
- Null rule (LL-06) in both directions
- VNA KO_BOOL_EXCLUSIVE bidirectional gate
- Null KO penalty mechanism
- JSON repair and parse edge cases (including Stage 0 brace-balance)
- Data loader type coercions
- Keyword fallback boundary behavior
- `source_confirms_value()` boundary conditions (including German decimal comma, unit scale)
- `_NUMERIC_KO_TENDER_KEYS` completeness guard
- All three source-span guard layers (L1, L0, L2) — including corpus-grounded real CompanyX cases
- `source_is_grounded()` — anchor-only false-positive trap, PDF glyph artifacts, paraphrase vs. verbatim
- Golden extraction regression for 5 tenders including out-of-scope case

**Identified gaps:**

| Gap | Risk | Recommended test |
|---|---|---|
| No live extraction tests | High — hallucinations only caught on live runs | Run `scripts/capture_pipeline_run.py` for new tenders; commit golden run files |
| No end-to-end SSE test | Medium — streaming pipeline not integration-tested | Test with TestClient + httpx streaming |
| mm→m conversion in validate_agv_criteria | Medium | Test: value 1900 + mm_to_m field → stored as 1.9 |
| Field text fallbacks | Medium | Test: regex matches → tender_key overridden |
| _build_correction_prompt format | Low | Test: output contains field name, bad value, allowed list |

### 9.3 Recommended Additional Tests

**U-E-next: validate_agv_criteria mm→m conversion**
```python
criteria = {"required_min_aisle_width_m": 1900}  # mm value for an m field
cleaned, _ = validate_agv_criteria(criteria)
assert cleaned["required_min_aisle_width_m"] == pytest.approx(1.9)
```

**U-M-29: COND_KO + CONTEXT field does not trigger KO**
Ensure a field with level=CONTEXT and no operator is never evaluated as a KO rule.

Note: U-E-08 (Layer 1 guard), U-E-09/U-E-10 (Layer 2 guard), and U-J-09 (Stage 0 brace-balance) from prior versions of this document are now fully covered by `test_source_span_enforcement.py` and `test_json_repair_parser.py`.

---

## 10. Configuration Reference

### config/field_levels.json

**Generated by:** `generate_all.py` → `read_field_levels()`  
**Read by:** `src/matching.py` (all matching logic); `app.py` (_NUMERIC_KO_TENDER_KEYS, _AP0_CONSTRAINED_FIELDS, _4C_EXTRACTION_DIRECTION)

Schema per entry:
```json
"<db_field_name>": {
    "level": "KO" | "COND_KO" | "SCORING" | "CONTEXT",
    "data_type": "Float" | "Integer" | "Boolean" | "Dropdown" | "Multi-Select" | "Text",
    "operator": "KO_IF_LT" | "KO_IF_GT" | "KO_IF_NEQ" | "KO_BOOL_REQUIRED" | "KO_BOOL_EXCLUSIVE" | "KO_SUBSET",
    "tender_key": "required_...",
    "allowed_values": ["...", "..."]   // only for Dropdown and Multi-Select
}
```

### config/vehicle_types.json

**Generated by:** `generate_all.py` → `read_vehicle_types()` + runtime additions  
**Read by:** `app.py` (multiple constants); `src/matching.py` (_SCORING_BUCKET_MAP); `src/context_builder.py` (AGV_KEYWORDS)

Key top-level keys:
- `vt_map`: dict mapping LLM output strings (lowercase) to canonical types
- `vna_subtypes`: list of LLM output strings that imply VNA
- `text_overrides`: list of {regex, canonical, vna} — regex patterns that force a type/VNA flag
- `keyword_map`: dict mapping canonical type → list of fallback keywords
- `llm_guide`: list of {name, description, key_indicators} for Pass 4a prompt
- `agv_detection_keywords`: flat list of all keywords for is_agv_amr fallback detection
- `scoring_bucket_map`: canonical type → scoring_weights bucket name
- `vna_applicable_types`: list of types where VNA gate applies (currently ["Forklift AGV"])
- `shared_sheet_name`: string name of the SHARED sheet — loaded as `_SHARED_SHEET` in app.py
- `vt_prompt_map`: canonical type → template filename for Pass 4b
- `4a_fields`: list of fields determined in Pass 4a (excluded from 4b validation)
- `vna_context_hint`: string injected as `{vna_context}` placeholder for VNA tenders
- `field_text_fallbacks`: list of {tender_key, regex, value, only_if_null}

### config/scoring_weights.json

**Generated by:** `generate_all.py` → `read_scoring_weights()`  
**Read by:** `src/matching.py` (Matcher)

Structure: `{bucket_name → {field_name → {weight, rule, t1?, t2?}}}`. Buckets: `default`, `forklift_specific`, `tugger_specific`, `amr_specific`.

### config/nace_codes.json

**Generated by:** `generate_all.py` → `read_platform()`  
**Read by:** `app.py` (CATEGORY_LIST for Pass 3 nace_template)

Keys: `codes` (list of "CODE: Name | hint" strings), `scope_in`, `scope_out`, `basic_schema`.

### config/plausibility.json

**Generated by:** `generate_all.py` → `build_plausibility_config()`  
**Read by:** `app.py` (AGV_PLAUSIBILITY, _MM_TO_M_FIELDS)

Per key: `{min, max, unit, label, mm_to_m}`. 7 fields currently. PLAUSIBILITY_RANGES source is still hardcoded in generate_all.py — not read from AP0 xlsx.

### config/sqlite_schema.json

**Generated by:** `generate_all.py` → `read_sqlite_schema()`  
**Read by:** `sync_airtable.py` (_SQLITE_SCHEMA, _EXT_COLUMNS)

Keys: `companies`, `products`, `base_models`, `base_model_extensions` (CREATE TABLE SQL strings); `bool_fields`, `int_fields`, `float_fields` (lists of field names for type coercion); `extensions_columns` (ordered column list for INSERT).

### config/extraction_hints.json

**Generated by:** `generate_all.py` (end of `generate()` function)  
**Read by:** `app.py` (_extraction_hints, _NUMERIC_KO_FIELD_HINTS)

Maps all 51 extraction fields: `{tender_key: {"hint": str, "sheet": str}}`. The `sheet` value is the AP0 sheet name (e.g. "SHARED – All AGV Types", "Forklift AGV"). This is used by Pass 4c to scope per-field calls to the correct vehicle type.

### config/industry_readme.md

**Source:** `Spec/haystacked_industry_readme.md`  
**Synced by:** `generate_all.py` (file copy, only when Spec version is newer)  
**Read by:** `src/context_builder.py` (build_system_context)

Contains AGV/AMR domain knowledge: vehicle classification rules, VNA logic, G2P workflows, battery types, VDA 5050 overview, OEM rebadging, the Blank ≠ Zero principle, and additional fleet/integration context. This is the primary domain knowledge source for the LLM — edit `Spec/haystacked_industry_readme.md`, then run `generate_all.py` to sync.

### config/prompts/*.txt

All generated by `generate_all.py`. Never edit. See Section 6.1 for the full inventory.

---

## 11. Operational Guide

### 11.1 start.sh

```bash
REQUIRED_MODEL="qwen2.5:7b"

# Start Ollama if not already running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    ollama serve &> /tmp/ollama.log &
    sleep 2
fi

# Check manifest — not just blob existence
if ! ollama show "$REQUIRED_MODEL" > /dev/null 2>&1; then
    ollama pull "$REQUIRED_MODEL"
fi

# Start FastAPI with JSON hot-reload
cd "$(dirname "$0")"
python3 -m uvicorn app:app --reload --reload-include "*.json" --host 0.0.0.0 --port 8000
```

Uvicorn is started with `--reload-include "*.json"` so changes to config files trigger a server restart without needing to restart manually.

### 11.2 Environment Variables

Required only for live Airtable sync (`sync_airtable.py` without `--local`):

| Variable | Value |
|---|---|
| `AIRTABLE_TOKEN` | `pat...` — Airtable Personal Access Token |
| `AIRTABLE_BASE_ID` | `app...` — Airtable base ID |

Set in `.env` at the project root. `sync_airtable.py` loads it via `python-dotenv`. The file is listed in `.gitignore`.

Ollama must be running at `http://localhost:11434` with `qwen2.5:7b` pulled. `start.sh` handles this automatically.

### 11.3 How to Add a New Matching Rule

1. Open `Spec/haystacked_AP0_field_spec_v0_10.xlsx`
2. Find the field row on the appropriate sheet (SHARED if it applies to all vehicle types, otherwise type-specific)
3. Set the Level column to "K.O." or "Cond. K.O."
4. Set the Matching Operator column to the appropriate operator name (e.g. `KO_IF_LT`)
5. Set the Tender JSON Key column to the extraction field name (e.g. `required_my_field`)
6. If Dropdown or Multi-Select, set the Allowed Values / Unit column to a pipe-separated list
7. Run `python3 scripts/generate_all.py`
8. Verify no CONSISTENCY WARNINGS for this field
9. Run `pytest tests/`

For a new numeric KO field, the source-span companion (`<field>_source`) is generated automatically. The field will automatically appear in `_NUMERIC_KO_TENDER_KEYS` and be included in Pass 4c.

### 11.4 How to Add a New Supplier Field

1. Add the field to the appropriate AP0 sheet with the correct Data Type
2. Add it to the Entity Model sheet under the appropriate layer (L3 for technical specs)
3. Run `python3 scripts/generate_all.py` — this regenerates `sqlite_schema.json`
4. Run `python3 sync_airtable.py` — this recreates the database with the new column
5. Add the field to `src/data_loader.py` — find the `Extension(...)` or `Product(...)` constructor and add the new field with the appropriate parse helper
6. Add the field to `src/models.py` — add to the `Extension` or `Product` dataclass with `Optional[type] = None`

### 11.5 How to Update LLM Extraction Hints

1. Find the field's row in the AP0 xlsx Description column (the "Description — what it is · where to find it · what it implies" column)
2. Update the text. Rules:
   - Describe patterns verbally: "looks like X" not "the value is typically 1000"
   - Never include numeric example values — they will be copied as hallucinations
   - Use "NULL RULE — READ FIRST:" prefix for fields with strong null-bias risk
   - Use "CONSERVATIVE EXTRACTION:" prefix for fields where worst-case extraction matters
   - For multi-value fields, specify which value to take (MAXIMUM or MINIMUM)
3. Run `python3 scripts/generate_all.py`
4. The updated hint appears in `config/extraction_hints.json` and in the generated Pass 4b templates

To strengthen a null rule without adding domain logic, add a NULL RULE clause to the Description cell. This text is stripped from Pass 4c prompts (reducing null-bias) but retained in 4b templates.

---

## 12. Known Gaps and TODOs

### Critical

**C-1: PLAUSIBILITY_RANGES still hardcoded in generate_all.py**

The seven plausibility ranges (min/max/unit per field) are defined in a module-level dict in `generate_all.py`, not in the AP0 xlsx. A new tender field with a numeric KO operator will not get plausibility validation until someone edits generate_all.py. Should be moved to a dedicated AP0 sheet (e.g. "Plausibility Ranges") and read like all other config. Workaround: edit PLAUSIBILITY_RANGES in generate_all.py.

~~**C-2: src/llm_client.py `repair_and_parse` divergence**~~

**Resolved (2026-06-04).** Canonical `repair_and_parse` extracted to `src/json_repair.py` (includes brace-balanced Stage 0, generic Stage 5 regex — no field names). Both `app.py` and `src/llm_client.py` now import from `src.json_repair`. Tests updated to import the same. AP0 boundary violation (hardcoded field list in Stage 5) also removed.

### Safeguards Applied (2026-06-15)

After the 2026-06-15 architecture audit, three safeguards were applied:

**S-1: `_SHARED_SHEET` startup assertion**

Changed from `_vehicle_cfg.get("shared_sheet_name", "SHARED – All AGV Types")` (silent fallback) to an empty-string default with `assert _SHARED_SHEET`. If `vehicle_types.json` is missing the key (e.g. after a failed `generate_all.py` run), the app now fails loudly at startup instead of silently using a stale hardcoded string.

**S-2: `is not None` in lift/aisle mm→m conversion**

`app.py` lines converting `required_max_lift_height_m` and `required_min_aisle_width_m` to mm used `if raw_val else None` — falsely treating zero as absent. Changed to `if raw_val is not None else None`. Zero lift height is nonsensical in practice but the code should not have a latent bug.

**S-3: `test_U_M_14` vacuous assertion** — see H-1 above.

### Benchmark Baseline (2026-06-16)

File: `tests/benchmark_results/benchmark_qwen2_5_7b_20260616_140000.json`  
Model: `qwen2.5:7b` — AP0 checksum `2b38100e`  
Result: **5/5 tenders, 139 tests pass** (with Layer 0 source-grounding guard active)

| Tender | Vehicle | Key fields after source-span guard | Top match |
|---|---|---|---|
| Nordlicht | Forklift AGV | weight=1200 kg, lift=10 m, aisle=3.4 m | REACHY |
| Dragonfly | Forklift AGV (VNA) | weight=1000 kg, aisle=2.0 m, lift=null (L2) | VEENY |
| Mama | Forklift AGV | weight=2000 kg, temp 10–30 °C | AMADEUS Classic |
| CompanyX | Forklift AGV | weight=1000 kg; lift/aisle/temp/humidity/gradient all null (L0 nulled 6, weight correct) | FM-X iGo |
| OeA-199-25 | Out of scope | is_agv_amr=False | — |

The CompanyX result is the regression case for Layer 0: all 7 fields the model previously hallucinated are now null. The one genuinely-specified field (weight=1000 kg) correctly survives.

### Test Gaps

**T-1: No live extraction tests**

`test_golden_extraction.py` compares against pre-captured golden run files but does not call Ollama itself. A fresh golden run must be generated manually when the model or prompts change. Need: a CI fixture that runs the actual LLM pipeline and asserts against golden extractions (requires live Ollama in CI).

**T-2: No SSE end-to-end test**

The `/analyze` endpoint has no integration test. A streaming response test with FastAPI TestClient + event parsing would catch pipeline regressions.

~~**T-3: Source-span guard not unit-tested**~~

**Resolved (2026-06-16).** All three layers covered by `test_source_span_enforcement.py` (U-SS-01 to U-SS-11) and `test_source_is_grounded.py` (U-SG-01 to U-SG-12) using real corpus-grounded triples.

**T-4: validate_agv_criteria mm→m conversion not tested**

**T-5: Field text fallbacks not tested**

### Architecture Improvements

**A-1: `enforce_source_spans()` is now in `src/json_repair.py` — docstring in `app.py` should cross-reference**

The call site in `app.py` should reference `enforce_source_spans()` in `src/json_repair.py` with a comment explaining the three-layer contract and the layer order (L1 → L0 → L2).

**A-2: Extraction direction dictionary could be generated as a config file**

`_4C_EXTRACTION_DIRECTION` is built in app.py from field_levels.json. It could be written to a generated config file (e.g. `config/extraction_directions.json`) by generate_all.py, making it inspectable without running the app.

**A-3: Pass 4c prompt language inconsistency**

Pass 4c user prompts are in English. App-facing SSE messages are in German. This inconsistency is harmless for the model but may confuse maintainers reading logs.

**A-4: Supplier database data gaps**

Based on prior audits:
- `route_type`: 0 of 21 Forklift suppliers have a value — this field cannot meaningfully gate any tender
- `workflow_capability`: 0 of 21 Mobile AMR suppliers have a value
- `vna_capable`: only 4 of 21 Forklift suppliers have a value — reduces VNA gate effectiveness

### Housekeeping

~~**H-1: test_U_M_14 service_coverage test is vacuous**~~

**Resolved (2026-06-15).** Fixed wrong tender_key (`service_coverage_required` → `required_service_coverage` per AP0) and replaced `isinstance(top[0].disqualified, bool)` with `assert top[0].disqualified`.

**H-2: `docs/sync_anleitung.md` may be outdated**

The Airtable sync guide predates the `--local` mode addition and the versioned CSV workflow.

**H-3: nace_categories.json in root**

The file `/nace_categories.json` in the project root appears to be a legacy file superseded by `config/nace_codes.json`. It is not read by any current module. Should be removed or documented.
