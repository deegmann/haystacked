# AP0 Change Guide

**Version:** based on AP0 v0.10 (v1.3)  
**Last updated:** 2026-06-01 (run 8)

This guide is for anyone who needs to change how the matching engine works, add a new supplier field, improve LLM extraction, or add a new vehicle type. All of these changes happen in the AP0 xlsx — not in Python code.

---

## What generate_all.py does

`scripts/generate_all.py` is the pipeline that turns the AP0 xlsx into runtime configuration. It reads two files:

- `Spec/haystacked_AP0_field_spec_v0_10.xlsx` — all industry-specific logic
- `Spec/haystacked_platform_config.xlsx` — cross-industry config (NACE codes, basic extraction schema, platform scope)

And writes all of these:

| Output file | What it controls | Who reads it |
|---|---|---|
| `config/field_levels.json` | Matching rules per field (level, operator, data type, tender_key, allowed_values) | `src/matching.py`, `app.py /api/field-meta` |
| `config/vehicle_types.json` | vt_map, VNA subtypes, text_overrides, keyword fallback, scoring_bucket_map | `app.py`, `src/matching.py`, `src/context_builder.py` |
| `config/scoring_weights.json` | Scoring weights and rules per field per AGV-type bucket | `src/matching.py` |
| `config/nace_codes.json` | NACE Prio-1 list for LLM classification | `app.py` |
| `config/plausibility.json` | Min/max ranges for LLM value validation | `app.py validate_agv_criteria()` |
| `config/sqlite_schema.json` | CREATE TABLE SQL for all four tables | `sync_airtable.py` |
| `config/prompts/extraction_template.txt` | AGV extraction prompt (field hints, vehicle type guide) | `app.py` |
| `config/prompts/extraction_retry_template.txt` | Retry prompt (shorter, simpler) | `app.py` |
| `config/prompts/basic_template.txt` | Basic extraction prompt | `app.py` |
| `config/prompts/nace_template.txt` | NACE classification prompt | `app.py` |
| `config/prompts/contact_template.txt` | Contact fallback prompt | `app.py` |
| `config/prompts/*_system.txt` | LLM system prompts (role definitions) | `app.py` |
| `config/industry_readme.md` | Domain knowledge synced from `Spec/haystacked_industry_readme.md` | `src/context_builder.py` |
| `config/ap0_checksum.txt` | MD5 of AP0 xlsx for startup auto-regen | `app.py` |

**After any AP0 xlsx change, run:**

```bash
python3 scripts/generate_all.py
```

To preview what would change without writing files:

```bash
python3 scripts/generate_all.py --dry-run
```

The app also auto-regenerates at startup if it detects a checksum mismatch — but it is better practice to run `generate_all.py` manually and check the output before restarting.

---

## Level naming convention — get these exactly right

`generate_all.py` uses a strict string match on the Level column. The AP0 xlsx must use exactly these strings:

| xlsx value | Internal code | Meaning |
|---|---|---|
| `K.O.` | `KO` | Hard knockout — one failure disqualifies |
| `Cond. K.O.` | `COND_KO` | Conditional knockout — activates only when tender requires |
| `Scoring` | `SCORING` | Points only, no filtering |
| `Context` | `CONTEXT` | Display only, no scoring |

**Common mistakes:**
- `COND_KO` (all caps) in the xlsx → will not be recognized. Must be `Cond. K.O.`
- `Cond.K.O.` (missing space) → will not be recognized
- `K.O` (missing final period) → will not be recognized
- Any level value not in the table above → field is silently skipped with no warning

If generate_all.py prints `[WARN] 'your_field_name' has operator but no Tender JSON Key`, the field has an operator but no tender_key — check both columns. If a KO or COND_KO field silently disappears from `field_levels.json`, check the Level string first.

---

## How to change a field's matching operator

**Use case:** `drive_type` needed to change from `KO` to `Cond. K.O.` after testing showed the hard KO was over-excluding capable suppliers.

**Steps:**

1. Open `Spec/haystacked_AP0_field_spec_v0_10.xlsx`
2. Navigate to the sheet that contains the field (SHARED, Forklift AGV, Tugger AGV, or Mobile AMR)
3. Find the row for the field
4. Change the **Level** column value (see exact strings above)
5. Optionally update the **Matching Operator** column if the operator also needs to change
6. Save the xlsx
7. Run `python3 scripts/generate_all.py`
8. Check the output — look for `[WARN]` lines and verify the field appears correctly in `config/field_levels.json`
9. Run the test suite: `pytest tests/`

**Valid operators:**

| Operator | Use for |
|---|---|
| `KO_IF_LT` | Numeric: K.O. when supplier < tender (payload, lift height, etc.) |
| `KO_IF_GT` | Numeric: K.O. when supplier > tender (aisle width, min temperature, etc.) |
| `KO_IF_NEQ` | Categorical: K.O. when supplier ≠ tender (exact match required) |
| `KO_BOOL_REQUIRED` | Boolean: K.O. only when tender=required AND supplier=False |
| `KO_BOOL_EXCLUSIVE` | Boolean: bidirectional (VNA only — K.O. in both directions) |
| `KO_SUBSET` | Multi-Select: K.O. when no overlap between tender list and supplier list |

**Do not mix operators and data types incorrectly.** A Multi-Select field using `KO_IF_LT` will silently never trigger (numeric comparison on a string list always fails). A Boolean field using `KO_SUBSET` will not work correctly. Match the operator to the data type:

| Data Type | Appropriate operators |
|---|---|
| Float, Integer | `KO_IF_LT`, `KO_IF_GT` |
| Dropdown | `KO_IF_NEQ`, `KO_SUBSET` |
| Multi-Select | `KO_SUBSET` |
| Boolean | `KO_BOOL_REQUIRED`, `KO_BOOL_EXCLUSIVE` |

This mismatch was the root cause of two bugs fixed on 2026-06-01: `fork_spread` had `KO_IF_LT` (numeric) on a Multi-Select string field, and `fleet_management_system` had `KO_BOOL_REQUIRED` (boolean) on a Dropdown field. Both were dead operators — they never triggered.

---

## How to add a new vehicle type mapping

**Use case:** the LLM returns a string like `"agv"` (generic) that is not yet in the vt_map, causing the canonical type to be null and disabling all K.O. filters.

**Steps:**

1. Open `Spec/haystacked_AP0_field_spec_v0_10.xlsx`, go to the **Vehicle Types** sheet
2. Add a new row with:
   - **LLM Output** column: the exact string the LLM might return (e.g. `"agv"`) — this is case-insensitive in the lookup, so lowercase is conventional
   - **Canonical Type** column: one of `"Forklift AGV"`, `"Tugger AGV"`, `"Mobile AMR"` (exact strings)
   - **VNA Subtype** column: `"yes"` if this output implies VNA, otherwise leave blank
   - **Fallback Keywords** column: pipe-separated keywords for the keyword fallback (e.g. `"agv|forklift"`) — optional but recommended
   - **Text Override Regex** column: a Python regex applied to the full document text — optional, use only when keyword matching is insufficient
   - **LLM Description** column: human-readable description used in the extraction prompt vehicle type guide
   - **LLM Key Indicators** column: brief list of signals the LLM should look for
3. Save the xlsx
4. Run `python3 scripts/generate_all.py`
5. Verify the new entry appears in `config/vehicle_types.json → vt_map`

**The fix that was applied on 2026-06-01** was exactly this: adding `"agv" → "Forklift AGV"` to the Vehicle Types sheet. Before this fix, any tender where the LLM returned the generic string `"AGV"` would produce a null canonical type, disabling the agv_type K.O. and showing all 52 suppliers as qualified.

---

## How to improve an LLM extraction hint

The **Description** column in the SHARED, Forklift AGV, Tugger AGV, and Mobile AMR sheets directly controls what the LLM is told about each field in the extraction prompt. Improving the hint is the primary way to fix extraction errors.

**Steps:**

1. Open the AP0 xlsx, go to the relevant sheet
2. Find the field (e.g. `max_payload_kg`)
3. Edit the **Description — what it is · where to find it · what it implies** column
4. Save the xlsx
5. Run `python3 scripts/generate_all.py`
6. Check `config/prompts/extraction_template.txt` — your hint should appear under the relevant field name
7. Test by processing a tender PDF that previously had the extraction error

**What makes a good extraction hint:**

- Tell the LLM exactly where to look: `"check ALL of the following: (1) explicit 'payload' fields, (2) pallet weight tables, (3) product weight sections"`
- Give the units explicitly: `"Output in kg"`, `"Output in METERS (not mm)"`
- Warn about common confusions: `"Do NOT confuse aisle width with rack height or lift height"`
- Specify the null condition: `"Output null if not explicitly stated — do NOT default to example values"`
- For Cond. K.O. fields, explain when the hard filter activates: `"Cond. K.O.: hard filter only when buyer cannot accept infrastructure modifications"`

**Example of a hint that was improved on 2026-06-01 (max_payload_kg):**

Before: "Maximum payload the AGV must carry per trip. Output in kg."

After: "Maximum payload the AGV must carry per trip. IMPORTANT: check ALL of the following: (1) explicit 'payload' or 'load capacity' fields, (2) pallet/load-unit weight tables (e.g. 'Gewicht pro Ladeeinheit: 1000 kg', 'max pallet weight X kg'), (3) product weight sections. Report the MAXIMUM weight per single load unit across all types. Output in kg. If not stated anywhere, output null."

The improved hint fixed extraction failures on two test tenders (Dragonfly and CompanyX) that stated payload in pallet weight tables rather than a dedicated "payload" field.

---

## How to add a new supplier field

Adding a new matchable field requires changes in two places: the AP0 xlsx (for matching rules and LLM hints) and Airtable (for the actual data).

**In the AP0 xlsx:**

1. Add a new row to the appropriate data sheet (SHARED or one of the AGV-type sheets)
2. Set the **Field Name** column — this must exactly match the Airtable column name (snake_case)
3. Set the **Level** column — one of the four exact strings above
4. Set the **Data Type** column — `Boolean`, `Float`, `Integer`, `Dropdown`, `Multi-Select`, or `Text`
5. Set the **Matching Operator** column (for KO and Cond. K.O. fields)
6. Set the **Tender JSON Key** column — the key the LLM will use in the extracted JSON (e.g. `required_my_new_field`)
7. Set the **Allowed Values / Unit** column for Dropdown and Multi-Select fields (pipe-separated list)
8. Set the **Description** column — the LLM extraction hint
9. Set the **Scoring Weight** and **Scoring Rule** columns if the field should score

**After adding to AP0:**

1. Run `python3 scripts/generate_all.py` — this updates all config files including the SQLite schema
2. Run `python3 sync_airtable.py` — this creates the new column in SQLite (the `_migrate_table` function in `sync_airtable.py` adds new columns non-destructively) and pulls the latest Airtable data. If you do not have Airtable credentials, use `python3 sync_airtable.py --local` to rebuild from the committed CSVs instead.
3. Verify the new field appears in `config/field_levels.json`
4. Verify the column exists in `data/haystacked.db` using a SQLite browser or the validate command

**In Airtable:**

Add the field to the appropriate Airtable table (base_model_extensions for most technical fields) and fill in data for existing supplier records as time allows. Fields with no data will be `None` in SQLite — per the null rule, this will not disqualify suppliers.

**In src/models.py:**

Add the new field to the `Extension` (or `Product`) dataclass with `Optional[...]` type annotation and `= None` default. Then add the corresponding parse call in `src/data_loader.py` in the `Extension` constructor call. These are the only Python files that need to change when adding a new field.

---

## How to add a new scoring rule

1. In the AP0 xlsx, set the **Scoring Weight**, **Scoring Rule**, **Threshold 1**, and **Threshold 2** columns for the field
2. Run `python3 scripts/generate_all.py`
3. The new rule appears in `config/scoring_weights.json`

**Available scoring rules:** `bool`, `bool_cond`, `nonempty`, `proportional`, `threshold_upper`, `threshold_lower`, `tiered_lower`, `tiered_upper`. See `matching-rules.md` for descriptions of each.

If you need a new scoring rule that is not in this list, that requires a Python change in `src/matching.py` in the `_score_one` method — add a new `elif rule == "your_rule_name":` branch. This is one of the rare cases where a Python change is justified.

---

## How to update domain knowledge for the LLM

The AGV extraction system prompt is assembled from two sources:

1. **Field hints** (Description column in AP0 xlsx) — field-specific extraction instructions, updated via the process above
2. **Industry README** (`Spec/haystacked_industry_readme.md`) — high-level domain knowledge about AGV/AMR types, VNA, G2P, OEM rebadging, battery types, VDA 5050, etc.

To update the industry domain knowledge: edit `Spec/haystacked_industry_readme.md` directly. When `generate_all.py` runs, it syncs this file to `config/industry_readme.md` (the runtime copy). `context_builder.py` reads `config/industry_readme.md` when building the system prompt.

Do not edit `config/industry_readme.md` directly — it will be overwritten.

---

## Common mistakes and how to avoid them

**Typo in Level column:** `"Cond. K.O."` is the correct value. Any variation (`"COND_KO"`, `"Cond.K.O."`, `"Conditional K.O."`) will cause the field to be silently dropped from `field_levels.json`.

**Wrong operator for data type:** Using `KO_IF_LT` on a Multi-Select field creates a dead operator (it never triggers). Use `KO_SUBSET` for Multi-Select fields.

**Missing Tender JSON Key:** If a KO or COND_KO field has an operator but no Tender JSON Key, `generate_all.py` prints a warning and the field will never trigger (the matching engine cannot find the tender value). Always set the Tender JSON Key for matchable fields.

**Editing generated files:** The most common mistake. Any change to `config/field_levels.json` or any file under `config/prompts/` is overwritten the next time `generate_all.py` runs. Always make changes in the AP0 xlsx.

**Running generate_all.py without re-syncing:** If you change the SQLite schema (add a new field), you must run `sync_airtable.py` after `generate_all.py` to actually add the new column to the database. The schema change in `config/sqlite_schema.json` does not automatically migrate the running database.

**Not running tests after a change:** Operator changes can silently break existing test cases. Always run `pytest tests/` after any AP0 change that affects matching operators.
