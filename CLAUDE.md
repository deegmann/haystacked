# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Start the app (starts Ollama if not running, then FastAPI on port 8000)
./start.sh

# Sync supplier data from Airtable → data/haystacked.db
python3 sync_airtable.py

# Rebuild DB from committed CSVs without Airtable credentials (e.g. after git checkout)
python3 sync_airtable.py --local

# Regenerate all runtime config from AP0 xlsx (run after every AP0 change)
python3 scripts/generate_all.py

# Dry-run to preview what generate_all.py would write
python3 scripts/generate_all.py --dry-run

# Run all tests
pytest tests/

# Run a single test
pytest tests/unit/test_matching_logic.py::test_U_M_01_ko_payload_too_low -v
```

## Architecture

### AP0 xlsx = Single Source of Truth

`Spec/haystacked_AP0_field_spec_v0_10.xlsx` is the single authoritative source for:
- All supplier/tender field definitions, data types, and allowed values
- Matching operators (K.O., COND_KO, SCORING, CONTEXT)
- Scoring weights
- Vehicle type mappings and LLM classification guide
- LLM extraction hints (Description column → prompt text)

**`scripts/generate_all.py`** reads both AP0 xlsx and `Spec/haystacked_platform_config.xlsx` (NACE codes, scope) and writes all files under `config/`. **Never edit generated files directly** — changes will be overwritten. Files that are always generated (never edit manually):
- `config/field_levels.json` — operator rules consumed by `src/matching.py`
- `config/vehicle_types.json` — vehicle type map, VNA detection, keyword fallback
- `config/scoring_weights.json`
- `config/nace_codes.json`
- `config/plausibility.json`
- `config/sqlite_schema.json` — CREATE TABLE SQL consumed by `sync_airtable.py`
- `config/extraction_hints.json` — tender_key → {hint, sheet} map consumed by Pass 4c in `app.py`
- `config/prompts/*.txt` — all LLM prompt files, especially `extraction_template.txt`

At startup, `app.py` checksums the AP0 xlsx and auto-regenerates all config if it changed.

### Data Flow

```
PDF upload
  → pdfplumber text extraction
  → Ollama (qwen2.5:7b) — up to 16 LLM passes per AGV tender:
      1. basic_extraction: buyer, project, contact, is_agv_amr, summary
      2. contact_fallback: targeted pass on last 4000 chars (only if contact missing)
      3. nace_classification: NACE code + in_scope flag
      — AGV passes (only if is_agv_amr=true) —
      4a. vehicle_type: classify Forklift AGV / Tugger AGV / Mobile AMR + VNA flag
      4b. agv_extraction: batch extraction of all ~40 fields in one JSON blob
          └─ AP0 allowed-values correction (max 2 retry calls)
      4c. per_field_extraction: one focused call per numeric KO field (~8 calls)
      — source-span enforcement (not an LLM call) —
      Layer 1: null value if <field>_source is absent (no citation = inference)
      Layer 2: null value if 4c abstained AND _source_confirms_value() fails
  → validate_tender_values(): AP0 allowed_values filter (rejects LLM hallucinations)
  → validate_agv_criteria(): plausibility ranges + mm→m auto-conversion
  → field_text_fallbacks: regex-driven overrides (from vehicle_types.json)
  → match_suppliers_new(): rule engine against SQLite supplier records
  → SSE streaming result to frontend
```

**Typical: 13–16 LLM calls per AGV tender, ~330 s wall time.**

### Pass 4c and Source-Span Hallucination Guard

**Pass 4c** runs after 4b and before validation. It calls the LLM once per numeric KO field (KO_IF_LT or KO_IF_GT Float/Integer) scoped to the detected vehicle type. Typical: ~8 calls. Non-null 4c results override 4b values; null 4c results are recorded in `_4c_abstained`.

**Source-span guard** — two layers run after 4c:
- **Layer 1 (always):** if `<field>_source` is absent or null → null the value. No citation = inference.
- **Layer 2 (4c abstentions only):** if 4c returned null AND `_source_confirms_value()` returns False for the 4b source → null the 4b value.

`_source_confirms_value()` is a pure numeric function: strips thousands separators, tests direct match and ×1000/÷1000 unit scale. No field names, no domain logic.

Module-level constants built from config at startup:
- `_NUMERIC_KO_TENDER_KEYS` — frozenset of tender keys subject to source-span guard; asserted non-empty.
- `_NUMERIC_KO_FIELD_HINTS` — subset of extraction_hints for Pass 4c prompt construction.
- `_4C_EXTRACTION_DIRECTION` — maps tender_key → extraction direction string (from operator: KO_IF_LT → MAXIMUM, KO_IF_GT → MINIMUM).
- `_SHARED_SHEET` — AP0 shared sheet name from `vehicle_types.json`; never hardcoded in Python.

### Matching Engine (`src/matching.py`)

Pure rule engine — no domain knowledge hardcoded. Reads all rules from `config/field_levels.json`.

**Operators:** `KO_IF_LT`, `KO_IF_GT`, `KO_IF_NEQ`, `KO_BOOL_REQUIRED`, `KO_BOOL_EXCLUSIVE`, `KO_SUBSET`

**Null rule (LL-06):** `None` on either side never triggers a K.O. for numeric/categorical operators. Null supplier value on a numeric KO field → `-15 pt` penalty instead of disqualification.

**To add or change a matching rule:** edit the AP0 xlsx (Matching Operator column), then run `generate_all.py`. No Python changes needed.

**`TenderRequirements`** resolves `field_name → tender_key → raw_value` using AP0 metadata, with type coercion per AP0 data_type column.

### Data Layer

- **`data/haystacked.db`** — SQLite, populated by `sync_airtable.py`. Schema generated from AP0 Entity Model sheet.
- **`src/data_loader.py`** — 3-way JOIN: `products ⋈ companies ⋈ base_model_extensions`, returns `list[SupplierRecord]`. Loads only `active=1` records.
- **`src/models.py`** — Dataclasses: `Company`, `Product`, `Extension`, `SupplierRecord`. `None` (never `0` or `[]`) represents unknown values.
- Multi-select fields stored as pipe-separated strings in SQLite; `_parse_multiselect()` splits on `|`.

### Vehicle Type Logic

Vehicle types go through two normalization layers in `app.py`:
1. LLM output string → canonical type via `vehicle_types.json` vt_map (e.g. `"vna"` → `"Forklift AGV"`)
2. Text-override regexes from `vehicle_types.json` (e.g. pattern "schmalgangstapler" → force VNA)

VNA detection sets `required_vna = "required"` which triggers `KO_BOOL_EXCLUSIVE` — VNA suppliers pass only VNA tenders, and non-VNA tenders exclude VNA suppliers.

### Context Builder (`src/context_builder.py`)

Builds the LLM system prompt for AGV extraction by concatenating:
- `config/industry_readme.md` (domain knowledge — synced from `Spec/haystacked_industry_readme.md`)
- K.O. field descriptions from `config/field_levels.json`
- Critical matching rules

The industry README is the primary domain knowledge source. Edit `Spec/haystacked_industry_readme.md`; `generate_all.py` syncs it to `config/`.

### Prompts

All prompts live in `config/prompts/*.txt`. The `_fill()` function in `app.py` replaces `{key}` placeholders without touching JSON braces inside prompt templates.

### Environment

- Requires `.env` with `AIRTABLE_TOKEN=pat...` and `AIRTABLE_BASE_ID=app...` for `sync_airtable.py`
- Ollama must be running locally at `http://localhost:11434` with `qwen2.5:7b` pulled
- `start.sh` handles starting Ollama automatically

## Key Invariants

- **Blank ≠ Zero**: `None` means unknown, never absent capability. Never infer a supplier lacks a feature because the field is `None`.
- **No industry logic in Python**: all field definitions, operators, scoring, vehicle types, extraction hints, and extraction directions come from AP0 xlsx via `generate_all.py`.
- `extraction_template.txt` and `extraction_hints.json` are always generated — never manually edit them.
- After any AP0 xlsx change: run `python3 scripts/generate_all.py` before testing.
- **No numeric literals in AP0 Description cells**: a 7B model copies example numbers as hallucinations. Describe patterns verbally (e.g. "a maximum of X kg" not "a maximum of 1000 kg").
- **`_source_confirms_value()` is field-agnostic**: it contains no field names, no AP0 allowed-value lists, no domain knowledge. Never add field-specific logic to it.
- **Pass 4c abstention ≠ unconditional override**: a 4c null result does not null the 4b value unless Layer 2 also fires. Abstention is evidence, not proof.
