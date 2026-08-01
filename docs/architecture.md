# haystacked Platform — Architecture

> Last updated: 2026-07-31 — multi-domain rollout (AGV + Industrial Refrigeration), OI-114 hallucination-guard fixes, 322 tests.
> Written for a reader with **no prior context on this codebase**. Terms are defined the first time they're used. For a compact, code-level reference (function signatures, config schemas, exact constants) see `docs/TECHNICAL_REFERENCE.md`.

---

## 1. What this system does

haystacked is a **B2B tender-matching platform**. A buyer (e.g. a warehouse operator who needs an AGV — an "Automated Guided Vehicle," a self-driving forklift or tow tractor — or a food & beverage plant that needs an industrial refrigeration system) uploads their tender document as a PDF. The system:

1. Reads the PDF and figures out, using a locally-run AI language model, what the buyer actually needs (payload capacity, aisle width, temperature range, certifications, etc.).
2. Compares those requirements against a database of real supplier products.
3. Ranks the suppliers and shows the buyer a shortlist, live, as the analysis runs.

The two live product domains today are **Logistics:AGV** (forklift AGVs, tugger/tow AGVs, mobile AMRs) and **FoodBev:Refrigeration** (industrial refrigeration systems). The architecture is built so a third domain can be added by editing a spreadsheet, not by writing new Python code — more on that in §3.

A few terms used throughout this document:

- **LLM** — Large Language Model. Here it's `qwen2.5:7b`, running locally via **Ollama** (no data leaves the machine). "7b" means 7 billion parameters — a small model by industry standards, chosen because it runs on a laptop, but this smallness is the root cause of most of the risks in §8.
- **Pass** — one LLM call with a specific, narrow job (e.g. "extract the buyer's contact info"). The pipeline chains 6-9 passes together per tender.
- **K.O.** ("Knock-Out") — a hard requirement. If a supplier fails a K.O. criterion, they are excluded entirely, no matter how well they score elsewhere.
- **AP0** — the master specification spreadsheet (`Spec/haystacked_AP0_field_spec_v0_10.xlsx`) that defines every field, rule, and prompt hint in the system. Explained in full in §3.
- **Hallucination** — an LLM stating something as fact that isn't actually in the source document. This is the central engineering problem of the whole pipeline, because a hallucinated requirement can wrongly disqualify a perfectly good supplier.

---

## 2. Pipeline stages — a walkthrough

This section follows one tender PDF from upload to ranked result, in the order the code actually executes it (verified against `app.py`'s `/analyze` endpoint, 2026-07-31). A simplified diagram first, then a stage-by-stage explanation.

```
PDF upload
  │
  ▼
pdfplumber text extraction  (up to 50,000 characters)
  │
  ▼
Pass 1 — basic extraction        (always)   buyer, project, contact, category, summary
  │
  ▼
Pass 2 — contact fallback        (only if contact info is still missing)
  │
  ▼
Pass 3 — NACE classification     (always)   is this even an in-scope industry?
  │
  ▼
Pass 4 — domain detection        (always)   "Logistics:AGV" or "FoodBev:Refrigeration"?
  │
  ├── not a recognized domain ──────────────────────────────► skip to result (no matching)
  │
  ▼  (domain recognized)
Pass 4a — leaf-type classification   (skipped for domains with only one product type)
  │        e.g. "is this a Forklift AGV, a Tugger AGV, or a Mobile AMR?"
  ▼
Pass 4b — batch field extraction     (always)   ~40 domain-specific fields in ONE LLM call
  │
  ▼
Pass 4c — per-field re-extraction    (one focused call per numeric K.O. field, ~8 calls for AGV)
  │
  ▼
Hallucination guard — enforce_source_spans()   (not an LLM call — pure Python, 3 layers)
  │
  ▼
AP0 allowed-values filter   (rejects values the LLM invented outside the spec's enum list)
  │
  ▼
Plausibility filter          (rejects values outside sane physical ranges; auto-converts units)
  │
  ▼
Regex fallback overrides     (last-resort text-pattern rules for fields the LLM keeps missing)
  │
  ▼
Matching engine — score every supplier in the database against the extracted requirements
  │
  ▼
Result streamed live to the browser (Server-Sent Events)
```

**Typical AGV tender: roughly 14-17 LLM calls, several minutes of wall-clock time** (the 7B model is not fast; this is the tradeoff for running fully locally with no cloud API cost or data-sharing).

> **Note on this diagram vs. `CLAUDE.md`:** `CLAUDE.md`'s "Data Flow" section (the repo's canonical architecture doc) still describes an older, AGV-only version of this flow, keyed off a boolean `is_agv_amr` flag. That flag has been superseded by the domain-detection pass described below, and a second domain (industrial refrigeration) now exists in production. This document reflects the current code (`app.py`, verified 2026-07-31); `CLAUDE.md`'s Data Flow section is a known-stale item worth refreshing separately (see §9).

### Stage by stage

**PDF text extraction.** `extract_text_from_pdf()` in `app.py` uses the `pdfplumber` library to pull raw text out of the PDF (no OCR — scanned image-only PDFs will fail here with an explicit error). Text is capped at 50,000 characters (roughly 14,000 "tokens," the unit the LLM actually reads in) because the model's context window is 32,768 tokens and needs headroom for the prompt itself.

**Pass 1 — basic extraction (always runs).** One LLM call extracts buyer name, project name, contact details, tender category, and a short summary. Uses `config/prompts/basic_system.txt` + `basic_template.txt`.

**Pass 2 — contact fallback (conditional).** If none of the contact fields came back from Pass 1, and the document is long enough (>6,000 characters) to plausibly have contact info buried at the end, a second focused call runs against just the last 4,000 characters. Contact information often sits in a footer or signature block that a full-document extraction can lose track of.

**Pass 3 — NACE classification (always runs).** NACE is the EU's standard industry-classification code system. This pass asks the LLM to classify the buyer's industry and decide `in_scope` (should this tender be shown at all?). If classification fails, the code defaults `in_scope=True` — a deliberate choice: a classification error should never silently hide a real result from the buyer.

**Pass 4 — domain detection (always runs).** This is the pass that decides *which* product domain the tender is about — "Logistics:AGV" or "FoodBev:Refrigeration" today, more can be added later. It's a dedicated LLM call (`config/prompts/domain_detection_template.txt`) with a keyword-based fallback if the LLM call fails or returns nothing usable (`_DOMAIN_KWS`, scanned against the first 5,000 characters). If the detected domain isn't one of the system's known extractable domains, the pipeline stops here — the buyer still gets their basic info and NACE classification, but no supplier matching runs.

**Pass 4a — leaf-type classification (conditional).** Within a domain, there can be multiple specific product types — e.g. within "Logistics:AGV" there's Forklift AGV, Tugger AGV, and Mobile AMR, each with somewhat different required fields (a tugger doesn't lift pallets, so "lifting height" doesn't apply to it). This pass asks the LLM which specific type the tender needs. **If a domain has only one product type** (industrial refrigeration currently has just one: "Industrial Refrigeration" — no sub-types), **this pass is skipped entirely** — there's nothing to classify, so an LLM call would just be wasted latency. This is a deliberate optimization (OI-107 in the project's internal tracking).

**Pass 4b — batch field extraction (always runs).** This is the single largest and most important LLM call: one prompt asks the model to extract roughly 40 domain-specific fields (payload capacity, aisle width, navigation type, temperature range, certifications, etc.) **all at once**, returning one JSON object. The prompt template is specific to the detected product type (`extraction_template_agv_forklift.txt`, `extraction_template_foodbev_refrigeration.txt`, etc.). If the LLM returns a value outside the spec's allowed list for a field, the code re-asks (up to 2 retries) with a targeted correction prompt showing exactly what was wrong and what values are allowed.

> **This single call matters architecturally more than its "one prompt edit" framing suggests — see §4, "the batch blast-radius property."**

**Pass 4c — per-field re-extraction (numeric K.O. fields only, ~8 calls for AGV).** For every field that is both numeric (a number, not a category) and a hard K.O. requirement (payload, aisle width, lifting height, etc.), a *second*, narrower LLM call re-asks for just that one field, with a shorter, more focused prompt. The idea: a smaller, less crowded prompt gives the model more "attention budget" for the one number that matters, catching cases where the big batch call in Pass 4b guessed wrong or invented a value. If Pass 4c disagrees with Pass 4b, Pass 4c's answer wins — *unless* the hallucination guard (next stage) has reason to distrust it.

**Hallucination guard (not an LLM call).** A pure-Python, three-layer check runs over every numeric K.O. field, deciding whether to keep or discard the LLM's answer. This is the most safety-critical part of the whole pipeline and gets its own section — **§4, Guards & Safety Nets**.

**AP0 allowed-values filter — `validate_tender_values()`.** Category-type fields (dropdowns, multi-select) get checked against the exact list of values the spec allows. Anything the LLM invented outside that list is discarded.

**Plausibility filter — `validate_domain_criteria()`.** Numeric fields get checked against sane physical ranges (e.g. a payload capacity of 50,000,000 kg is obviously wrong). This stage also auto-converts units where the spec defines a conversion rule (e.g. a lift-height value the LLM reported in millimeters gets converted to the spec's expected meters).

**Regex fallback overrides.** A last-resort layer: a small set of hand-written text-pattern rules that catch specific known-tricky phrasings the LLM tends to miss, filling in a value only if the field is still empty at this point.

**Matching engine.** Every supplier product in the database gets scored against the (now-cleaned) extracted requirements. See §6.

**Result streamed to the browser.** The whole pipeline runs as a `StreamingResponse` using **Server-Sent Events (SSE)** — the browser gets live progress updates ("Pass 4c (3/8)...") rather than waiting silently for the whole multi-minute process to finish, then a final `result` event with the full match list.

---

## 3. Where the data comes from

There are two entirely separate data sources feeding this system, and it's important not to confuse them:

### 3.1 Supplier data: Airtable → SQLite

The actual list of AGV/refrigeration suppliers and their product specs lives in an **Airtable base** (a spreadsheet-like collaborative database), maintained by hand/research. `sync_airtable.py` pulls it down and writes it into a local **SQLite** database at `data/haystacked.db`, which is what the matching engine actually reads at runtime — Airtable is never queried live during a tender analysis.

```bash
python3 sync_airtable.py            # live pull, needs .env with AIRTABLE_TOKEN / AIRTABLE_BASE_ID
python3 sync_airtable.py --local    # rebuild the SQLite DB from committed CSV snapshots, no credentials needed
```

The `--local` mode exists so anyone can get a working copy of the database (e.g. right after `git checkout`) without needing Airtable API access.

### 3.2 Business rules: the AP0 spreadsheet

Everything about *how the system behaves* — which fields exist, what counts as a hard requirement vs. a nice-to-have, how suppliers get scored, what text the AI is told when it's extracting a given field — comes from a single Excel file:

**`Spec/haystacked_AP0_field_spec_v0_10.xlsx`** — this is the platform's **single source of truth**. Nothing about business logic, matching rules, or field definitions is meant to live directly in Python code. A second spreadsheet, `Spec/haystacked_platform_config.xlsx`, holds cross-industry reference data (the NACE code list, unit-conversion rules).

**`scripts/generate_all.py`** reads both spreadsheets and writes out everything under `config/` — JSON files, Python dataclasses, and the actual `.txt` prompt files the LLM sees. **These generated files must never be hand-edited** — any edit gets silently overwritten the next time the generator runs. If you need to change a matching rule, a scoring weight, or the wording an AI extraction pass sees, you edit the spreadsheet and regenerate:

```bash
python3 scripts/generate_all.py            # regenerate everything
python3 scripts/generate_all.py --dry-run  # preview what would change, write nothing
```

The app also does this automatically: at startup, `app.py` computes a checksum of both spreadsheets and re-runs the generator if either file has changed since the last run. So in practice, editing the xlsx and restarting the app is enough — but running the script explicitly is useful to see warnings/errors before they surface as a runtime failure.

**How to make a rule change, step by step:**
1. Open `Spec/haystacked_AP0_field_spec_v0_10.xlsx`.
2. Find the field's row on its domain tab (e.g. `AGV_Forklift`) or the shared `Global` tab.
3. Edit the relevant column (Matching Operator, Scoring Weight, LLM Hint, etc. — see §3.4 below for what each column means).
4. Run `python3 scripts/generate_all.py` and check its output for `[FEHLER]` (hard error) or warning lines.
5. Run `pytest tests/` to confirm nothing broke.
6. Restart the app (or let the checksum auto-regen do it).

### 3.3 Generated config files (never edit directly)

| File | What it's for |
|---|---|
| `config/fields.json` | Every field's full definition, keyed by a unique ID (UUID) |
| `src/field_spec.py` | A Python class + loader functions that read `fields.json` |
| `config/vehicle_types.json` | Product-type name mapping, keyword detection, text-override rules |
| `config/scope_registry.json` | The domain/product-type hierarchy tree (see §3.5) |
| `config/nace_codes.json` | The NACE industry code list |
| `config/plausibility.json` | Sane-range definitions and unit-conversion rules per numeric field |
| `config/sqlite_schema.json` | The `CREATE TABLE` SQL and column lists for the supplier database |
| `config/prompts/*.txt` | Every prompt template the LLM actually reads |

One file is **manually maintained, not generated**: `config/unit_semantics.json` — a short list of units where zero is a meaningful value (like °C — "0 degrees" is a real temperature, not "no requirement"). Explained further in §6.3.

### 3.4 What's in the AP0 spreadsheet, field by field

Each row on a domain tab describes one field. The columns that matter most for understanding system behavior:

| Column | Meaning |
|---|---|
| **Field Name** | The internal name (e.g. `max_payload`) |
| **Level** | `K.O.` (hard exclusion), `Cond. K.O.` (hard exclusion only if the buyer marks it required), `Scoring` (contributes points but never disqualifies), or `Context` (informational only, never affects matching) |
| **Matching Operator** | The comparison rule — see §6.2 |
| **Data Type** | Boolean, Integer, Float, Dropdown, Multi-Select, Text |
| **Unit** | The physical unit this field is stored/compared in (mm, kg, °C, ...) |
| **Allowed Values** | For Dropdown/Multi-Select fields, the exact list of legal answers |
| **LLM Hint** | The instruction text sent to the AI when it's extracting this field. **This is the only column meant to reach the LLM as an instruction** — see the critical distinction in §4.1 |
| **UI Hint** | User-facing help text shown in the browser's "please fill in the missing details" dialog. **Not** meant for the LLM — again, see §4.1, because getting this wrong caused a real, confirmed hallucination this week |
| **Plausibility Min/Max** | The sane-range boundaries used in the post-extraction validation stage |
| **UUID** | A globally unique ID for this field — this is the real primary key everything downstream uses (see §3.5) |

### 3.5 UUID-keyed fields and the scope registry

Two structural details worth understanding if you're going to touch the code:

**Fields are keyed by UUID, not by name.** The reason: the same field name can legitimately appear on more than one domain tab with a different definition — e.g. `min_aisle_width` exists once for Forklift AGVs and once for Tugger AGVs, potentially with different plausibility ranges. `config/fields.json` is keyed by each field's UUID, and a separate `tender_key` (derived as `"required_" + field_name`) is what shows up in the extracted-requirements dictionary at runtime. Code that needs "all the specs matching this field name" uses `fields_by_field_name()`, which returns a list, because there can legitimately be more than one.

**The scope registry is the domain/product-type hierarchy.** `config/scope_registry.json` encodes a tree: a root (`*`, meaning "applies to everything"), domain nodes below it (`Logistics:AGV`, `FoodBev:Refrigeration`), and leaf product-type nodes below those (`Logistics:AGV:Forklift`, `Logistics:AGV:Tugger`, `Logistics:AGV:AMR`). `FoodBev:Refrigeration` currently has no children — it's a "single-leaf domain," which is exactly why Pass 4a (leaf-type classification) gets skipped for it, as mentioned in §2.

For a given product type, `resolution_order` gives the full chain from root to leaf — e.g. a Forklift AGV supplier is evaluated against fields on `*` (Global), `Logistics:AGV` (shared AGV fields), and `Logistics:AGV:Forklift` (forklift-only fields), but never against Tugger- or AMR-specific fields. This is what stops a forklift supplier from being penalized for not having a tugger-only capability.

```json
{
  "scopes": {
    "*":                       {"parent": null,           "tab_name": "Global"},
    "Logistics:AGV":           {"parent": "*",             "tab_name": "AGV_Shared"},
    "Logistics:AGV:Forklift":  {"parent": "Logistics:AGV", "tab_name": "AGV_Forklift", "canonical_name": "Forklift AGV"},
    "Logistics:AGV:Tugger":    {"parent": "Logistics:AGV", "tab_name": "AGV_Tugger",   "canonical_name": "Tugger AGV"},
    "Logistics:AGV:AMR":       {"parent": "Logistics:AGV", "tab_name": "AGV_AMR",      "canonical_name": "Mobile AMR"},
    "FoodBev:Refrigeration":   {"parent": "*",             "tab_name": "FoodBev_Refrigeration", "canonical_name": "Industrial Refrigeration"}
  },
  "resolution_order": {
    "Logistics:AGV:Forklift": ["*", "Logistics:AGV", "Logistics:AGV:Forklift"],
    "FoodBev:Refrigeration":  ["*", "FoodBev:Refrigeration"]
  }
}
```

Both `app.py` and the matching engine (`src/matching.py`) load this file at startup and assert it's well-formed (e.g. "every product-type name the AI can output has a corresponding scope entry") — if the spreadsheet and the registry ever drift out of sync, the app refuses to start rather than silently mis-scoring suppliers.

### 3.6 SQLite schema and the supplier data loader

`data/haystacked.db` has four tables: `companies`, `products`, `base_models`, and `base_model_extensions` (the last one holds all the actual K.O./scoring field values). The table structure itself is generated from the AP0 spreadsheet's structural tab, not hardcoded.

`src/data_loader.py` runs a 3-way join across `products`, `companies`, and `base_model_extensions`, and for every row builds a `SupplierRecord` — a Python object holding one supplier product's full set of field values. **Only rows with `active=1` are loaded** — inactive/discontinued products are excluded from matching entirely, not just hidden.

**A critical invariant here, worth calling out explicitly: `None` (unknown) is never the same as `0` or `False` (absent).** If a supplier's payload capacity field is empty in the database, that means *"we don't know this supplier's payload capacity,"* not *"this supplier has zero payload capacity."* The matching engine treats these very differently — see the Null Rule in §6.3.

---

## 4. Guards & Safety Nets

This is the part of the system that changed most in the last few days, and it's the part most worth understanding carefully, because it's the difference between "this AI extracted a real requirement" and "this AI invented a number that will wrongly disqualify good suppliers."

There isn't one guard — there are several, at different points in the pipeline. Read them in order:

### 4.1 Before the LLM ever sees a prompt: keeping bad instructions out

The single biggest lever against hallucination is never giving the model a reason to hallucinate in the first place. Two rules apply to how the AP0 spreadsheet's text reaches the LLM:

**Rule 1 — no example numbers in instruction text.** If the "LLM Hint" column for a field says something like *"e.g. -20°C for cold storage"* as a worked example, a 7-billion-parameter model will sometimes copy that literal number back out as if it had read it in the real document. This has been a known failure mode since early June and is a standing rule: write hints in words ("a maximum of X kg"), never with a plausible-looking sample number.

**Rule 2 — only one AP0 column is allowed to reach the LLM as an instruction.** The spreadsheet has two, easily-confused text columns per field:
  - **"LLM Hint"** — meant for the AI, feeds the extraction prompts.
  - **"UI Hint"** — meant for a *human*, shown in the browser's "please clarify this missing field" dialog. Internally this is called `user_description`.

Until 2026-07-30, `user_description` was **also** being included in the LLM's system prompt — a genuine bug, not a spec violation, in `src/context_builder.py::build_system_context()`. This mattered because the "UI Hint" for `lifting_height` contained an illustrative example — *"(mm; e.g. 10,000 mm = 10 m for high-bay storage)"* — and on a real test tender ("Dragonfly"), the model echoed that exact literal number back as a fabricated requirement, complete with a fabricated citation ("Lift height: 10,000 mm") that does not appear anywhere in the source document. Investigation traced the value on the same tender across multiple prior runs and found it had actually been failing silently for weeks — earlier runs produced different but equally fabricated citations for the same phantom 10-meter requirement, and the downstream guard (§4.2) had been catching it by luck each time, until one citation happened to be self-consistent enough to slip through.

This is now fixed (commit `685b492`, 2026-07-30): `build_system_context()` no longer includes `user_description` in any LLM-facing prompt at all — it is exclusively UI-facing now. Three cells in the *other* column (`LLM Hint`) that had also slipped past prior review with literal example numbers were cleaned up in the same commit.

> **This is an easy mistake to reintroduce.** Two AP0 columns sound almost identical ("LLM Hint" vs. "UI Hint") and serve very different audiences. If you're ever tempted to make the AI's prompt "friendlier" by pulling in more descriptive text from the spreadsheet, check first whether that text was ever meant for a human, not the model.

### 4.2 The batch blast-radius property — why "I only changed one field's text" is never a safe assumption

Pass 4b (§2) extracts roughly 40 fields with **one single LLM call**, not 40 separate calls. The model generates its entire JSON response token by token, left to right, and every token it writes depends on everything before it in the same response — including its answers for completely unrelated fields earlier in the same JSON blob.

This has been proven twice, empirically, this week, not just reasoned about:

- Deleting a single **duplicated sentence** from `max_payload`'s prompt text (a seemingly harmless cleanup) measurably changed the model's fabricated citation for the unrelated `lifting_height` field elsewhere in the same batch response — from an obviously-wrong citation the guard caught easily, to a suspiciously well-formed one that slipped through. This is the edit that ultimately let the incident in §4.1 happen.
- In an earlier, separate investigation, lengthening one shared instruction clause used by ~8 numeric fields (each getting a near-identical repeated parenthetical) caused the batch call's non-null field count to collapse from 16 fields down to 5 on the same test document — including the *source citations* for the fields that went null, which is the tell that the failure happens during the model's text generation itself, not in a downstream guard.

**The practical rule this implies: a prompt edit that is textually scoped to one field is not behaviorally scoped to one field.** Any change to the Pass 4b prompt template — even one field's hint text — can shift the model's output for every other field in the same batch call. "I only touched field X" is never, by itself, sufficient reasoning to call an edit safe. The only reliable way to check is to re-run the full extraction on real test tenders and diff every field's output, not just the one that was edited.

### 4.3 The source-span hallucination guard — three layers, after Pass 4c

This is the core defense, implemented in `enforce_source_spans()` in `src/json_repair.py`, and it runs on every numeric K.O. field after Pass 4c. For each field with a non-null extracted value, three checks run **in order** — the first one that fails nulls the value and stops (later layers don't run):

**Layer 1 — is there a citation at all?** For every numeric K.O. field, the prompt also asks the model to copy the exact sentence from the document that states the value (a `<field>_source` companion key). If that citation is missing or empty, the value is discarded outright. No citation means the model is guessing, not reading.

**Layer 0 — is the citation actually real?** Having *a* citation isn't enough — the model can invent a plausible-sounding quote that simply isn't in the document. `source_is_grounded()` checks two things, both against the real, actually-extracted PDF text (not the model's claim about it):
  1. **Anchor** — does the value's digit-string genuinely occur somewhere in the real document?
  2. **Co-location** — does at least one distinctive word from the model's quote appear near that number in the real document?

  Both must hold, or the value is discarded. This is what caught the Dragonfly incident described in §4.1 on every run except the one where the fabricated citation happened to be self-consistent.

  **Updated 2026-07-31 (commit `2724749`).** The anchor check used to also accept a "scale-converted" match completely unconditionally — meaning if the field's value was, say, 10 meters, the check would also accept a bare "10" occurring *anywhere* in the document as if it were "10,000" in millimeters (the ×1000/÷1000 tolerance exists to handle genuine unit confusion, e.g. a document stating millimeters where the field expects meters). The problem: a bare "10" is a very common substring to find by coincidence in any real document (dates, other quantities, list indices), which meant a *fabricated* round value like 10,000 could "anchor" against almost anything. This is now fixed: a scale-converted anchor only counts if a matching unit word (mm/cm/m/km/g/kg/t) sits immediately next to that number in the real document *and* it resolves to the same physical quantity. This closed a gap that had been known and explicitly flagged as an accepted risk since 2026-06-16 (test `test_U_SS_11`) — and a live verification run on 2026-07-31 confirmed the fix independently caught a *second*, previously-undetected fabrication on a different tender and field (see §5.1).

**Layer 2 — does the citation numerically match the value? (only checked when Pass 4c abstained)** If Pass 4c (the focused per-field re-check) explicitly returned "I don't know" for a field, but Pass 4b's batch call did produce a value, this layer checks whether Pass 4b's own citation actually contains a number matching its own claimed value. If not, the value is discarded — *unless* a rescue check fires first: if the value's digit-string genuinely appears in the real document with its expected unit word right next to it, the value is kept anyway. This handles a specific, observed failure mode where Pass 4b's citation field accidentally echoes the spreadsheet's own hint text (a broken citation *channel*, not necessarily a wrong *value*) for a number that is otherwise genuinely present in the document.

All three checking functions (`source_confirms_value()`, `source_is_grounded()`, `document_supports_value_with_unit()`) are deliberately **field-agnostic** — they contain no field names, no domain knowledge, just generic string/number matching. This is an explicit design rule: the guard must work identically for a payload-capacity field and a temperature field, so that adding a new field to the spec never requires touching the guard's code.

### 4.4 Downstream, non-LLM safety nets

Two more checks run after the guard, described in §2: the **AP0 allowed-values filter** (rejects category values the LLM invented outside the spec's enum) and the **plausibility filter** (rejects numbers outside sane physical ranges, with automatic unit conversion). These aren't specifically anti-hallucination guards — they're general data-quality nets that would catch bad values regardless of source — but they're the last line of defense before a value reaches the matching engine.

---

## 5. Known Risks

An honest list, current as of 2026-07-31. Several of these are *closed* risks that were open a few days ago — included here so the historical shape of the problem is clear, not just the current snapshot.

### 5.1 Open — exact-scale hallucination collisions are not caught

The fix described in §4.3 (Layer 0, 2026-07-31) closed the *scale-converted* anchor loophole (a value at ×1000/÷1000 scale from a coincidental document number). It did **not** close the more basic case: a fabricated value that happens to match a real, unrelated number **at the same scale**, with no conversion involved, elsewhere in the document. This is the exact case a test written 2026-06-16 (`test_U_SS_11`) flagged and has monitored ever since — still unresolved. In practice this means a fabricated "gradient = 1.5%" could still pass Layer 0 if the real document happens to state an unrelated "1.5" near vaguely similar words.

**Why it matters:** the fix's own verification run (2026-07-31) independently proved the *general vulnerability class* is real and still exploitable in its exact-scale form: on a different test tender ("Mama"), a fabricated 3,000mm aisle-width value with a citation containing no aisle-width number at all was correctly rejected by the *new* scale-converted gate — but the same run confirmed that under the *old* (still-present-for-exact-scale) logic, this class of fabrication reliably slips through and would have become a live, wrongly-disqualifying requirement.

### 5.2 Open — no comprehensive audit of "no numeric literals reaching the LLM"

The 2026-07-30 investigation (§4.1) found and fixed literal-number violations in both the `user_description` column (systemically, across all fields) and three specific cells in the `LLM Hint` column that earlier review passes had missed. There is **no automated, comprehensive check** that guarantees a future spreadsheet edit won't reintroduce this pattern — only ad hoc spot-checks and a couple of narrow generation-time assertions for specific known patterns. A new field added carelessly next month could reintroduce exactly the same class of bug.

### 5.3 Open — the 2026-07-30 fix itself cost real extraction accuracy on other fields

This is not in the original brief for this document and deserves to be — it's a concrete, verified example of the batch blast-radius property (§4.2) working against the system, not for it. Removing `user_description` from the shared prompt (the correct fix for §4.1's incident) left Pass 4b's big batch call with **zero descriptive guidance** for every field whose spreadsheet "LLM Hint" is weaker than its now-removed "UI Hint" was. Verified regressions on the same day as the fix, on real test tenders:

- **CompanyX's `max_payload`** — the one genuinely-stated numeric fact in that entire tender document ("The maximum loaded weight of the AGVs is up to 1,000 kg"), previously extracted correctly and stably across 15+ historical runs, went to `null` after the fix — not caught by any guard, a true extraction miss. This changed the tender's actual shortlist: qualified suppliers dropped from 67 to 46, and the top-ranked match changed entirely.
- **CompanyX's `min_aisle_width`** — lost for a related but distinct reason: Pass 4c (the per-field re-check) produced a *different*, fabricated value that Layer 0 correctly rejected, but there is no mechanism to fall back to Pass 4b's own value (which was correct and still had a genuinely-grounded citation attached) once Pass 4c's override gets rejected. This is a known, still-open design gap, independent of the 2026-07-30 fix.
- **`certifications_ik`** (a certifications list field) lost its only usable extraction guidance entirely and came back empty on a document that plainly lists two real certifications.

None of this is a regression in the sense of "the fix was wrong" — trading a systemic false-positive (invented requirements) for some false-negatives (missed real requirements) on individual fields was a judgment call made and accepted at the time. It's listed here because it's a real, currently-live tradeoff, not a hypothetical one, and it hasn't had a follow-up pass to strengthen the weaker "LLM Hint" text for the specific fields it affected.

### 5.4 Open — Pass 4c has a very high abstention rate on at least one important field

`max_payload` returns "I don't know" from Pass 4c on essentially every run, even on documents where the value is stated in plain prose and Pass 4b gets it right. The per-field re-check pass exists specifically to double-check numeric K.O. fields, so a field where it never contributes useful signal is a field where the pass is pure extra latency (roughly 15-20 seconds per field, per tender) for no benefit. This has not been investigated for other fields to see how widespread the pattern is. Root-cause analysis so far points to how heavily "return null if uncertain" language is repeated across the shared system prompt, the field's own hint text, and the pre-filled JSON template shown to the model — three separate nudges toward "null" with very little corresponding pressure to actually commit to a value.

### 5.5 Open — some fields are "bistable": they flip between correct and null across identical re-runs

`max_payload` and `min_aisle_width` on the CompanyX test tender have both been observed to flip between a correct value and null/wrong across repeated runs of the exact same pipeline against the exact same PDF, with no code changes in between. This is LLM sampling variance at the extraction stage itself (temperature is set to 0.0, which should be deterministic in principle, but empirically is not perfectly so on this hardware/model combination) — not a guard problem, and not yet systematically characterized across the full set of test tenders. It means a single successful test run is not strong evidence that a field extracts reliably.

### 5.6 Open — a confirmed sign-flip bug on temperature fields

`required_temperature_min` has been observed, on two different industrial-refrigeration test tenders, to be extracted as a negative number when the source document only ever states positive temperatures (e.g. a document stating "operating temperature +2°C to +6°C" produced an extracted minimum of -2°C — not +2). This is confirmed via direct text search of the real extracted document (no "-2" appears anywhere), and it has a real matching consequence: on one test tender, a purpose-built refrigeration product from a real, capable supplier was disqualified against the fabricated -2°C requirement, when the correct +2°C requirement is a temperature that product can actually meet. The correct sign passes the hallucination guard cleanly (the digit "2" is genuinely in the document and near the right words) — the guard's job is to check whether a citation is *grounded*, not whether its *sign* was transcribed correctly, so this bug currently sits outside what any existing layer checks for. Root cause is not yet identified; deliberately deprioritized against the higher-severity fixes in this document.

### 5.7 Open — a pre-existing wording mismatch between a field's LLM Hint and its own allowed values

Separately from anything above: the `cooling_medium` field's "LLM Hint" tells the model to extract *"glycol circuit, water, or direct expansion"* while its own spreadsheet-defined `allowed_values` list is `['glycol', 'water', 'direct']` — a wording mismatch within the same field's own definition. When the model (reasonably) copies the hint's exact wording ("glycol circuit") instead of the shorter allowed value ("glycol"), the AP0 allowed-values filter doesn't currently normalize the mismatch, and the resulting exact-string comparison in matching produces a false K.O. against a supplier whose own database value is the correctly-spelled "glycol". On one test tender this took the qualified-supplier count from 1 (the single genuinely correct match) to 0. This is a one-field spreadsheet fix, not an architectural one, but it's real and currently live.

### 5.8 Resolved (OI-115a/OI-115b) — the spreadsheet's declared Unit column now is what tells the LLM what unit to use

Previously, the AP0 spreadsheet's structured "Unit" column existed but the LLM extraction prompts never read it directly — the only way the model learned what unit was expected was if someone manually wrote it into the free-text "LLM Hint," which could silently drift out of sync with the structured Unit column. A concrete example: `lifting_height`/`min_aisle_width`/`tugger_min_aisle_width` were named with an `_mm` suffix (implying millimeters) but AP0-declared `Unit=m`, with hint text saying "in METERS" — genuinely contradictory guidance inside each field's own definition, bridged only by a matching-engine conversion step.

OI-115a (commit `f76a767`) made `build_extraction_template()` auto-render `(unit: X)` into every field's prompt line from the AP0 Unit column, and stripped redundant hand-typed unit text from hints/UI descriptions. OI-115b (commit `26d4195`) went further for these 3 specific fields: realigned AP0 `Unit` to `mm` (matching the real DB storage unit) and deleted the bridging conversion mechanism (`_to_match_units()`) entirely rather than leave it compensating for a mismatch that no longer exists. The Unit column is now the single, auto-rendered source of unit truth for both the LLM prompt and (as of OI-115a) buyer-facing labels — no remaining prompt-side inconsistency for these fields. A further, larger effort (OI-115c, commits `3b9f65d`/`e3ce309`) stripped the now-redundant unit suffix from 38 field names across AP0/generated config/the live DB (Airtable rename deferred separately, OI-115c Phase 3E) — verified value-neutral (zero extracted-value or stored-value changes, only key names) via independent DB, config, and E2E proofs.

### 5.9 Closed (fixed 2026-07-30 and 2026-07-31) — for reference

The `user_description` leak (§4.1) and the scale-converted anchor gap (§4.3, the ×1000/÷1000 half of the problem) are both fixed and verified as of 2026-07-31, including an independent live-run verification that found a genuine second case the fix caught beyond its original trigger tender. Both are included here only so the history is legible — see §4 for the current, fixed behavior.

---

## 6. Matching Engine (`src/matching.py`)

A pure rule engine: every rule, weight, and threshold comes from `config/fields.json` (generated from the AP0 spreadsheet). No domain knowledge — no field names, no "AGVs need X" logic — is hardcoded in the matching Python code itself.

### 6.1 Scope filtering

Before scoring a supplier, the engine resolves which fields are actually relevant to that supplier's product type using the `resolution_order` chain from §3.5 — a Forklift AGV supplier is never evaluated against Tugger- or AMR-only fields.

### 6.2 Operators

| Operator | Plain-language meaning | What happens if either side is unknown |
|---|---|---|
| `KO_IF_LT` | Supplier is disqualified if their value is *less than* what the tender needs (e.g. payload capacity) | No disqualification — unknown is never treated as failing |
| `KO_IF_GT` | Supplier is disqualified if their value is *more than* the tender's limit (e.g. aisle width — vehicle must fit) | Same as above |
| `KO_IF_NEQ` | Supplier is disqualified if their value doesn't exactly match the tender's required category | Same as above |
| `KO_BOOL_REQUIRED` | Supplier is disqualified only if the tender explicitly requires a capability and the supplier explicitly does *not* have it | Unknown supplier value → no disqualification |
| `KO_BOOL_EXCLUSIVE` | A two-way gate: required→must have it; explicitly not-wanted→must not have it (used for VNA — see §6.5) | Unknown supplier value → no disqualification |
| `KO_SUBSET` | Supplier is disqualified only if there's *no overlap at all* between what the tender needs and what the supplier offers (e.g. navigation type, service coverage) | Empty list on either side → no disqualification |

### 6.3 The Null Rule — the single most important invariant in the matching engine

**`None` (unknown) on either side of a comparison never triggers a hard disqualification, for any numeric or categorical operator.** The reasoning: not knowing whether a supplier has a capability is not the same as knowing they don't. Disqualifying suppliers for missing database fields (which happens constantly — research on real suppliers is never 100% complete) would systematically and silently favor suppliers with more complete paperwork over suppliers who are actually the better technical fit.

Instead: **when a tender has a real numeric requirement and the supplier's value is unknown, the supplier receives a 15-point scoring penalty instead of disqualification.** This ranks suppliers with confirmed, verified data above suppliers with unknown data, without unfairly excluding either.

A related nuance: for `KO_IF_LT` fields, a tender value of exactly `0` is treated as *"no real requirement stated"* — because "the tender needs at least 0 kg of payload" is not a meaningful constraint — **unless** the field's unit is one where zero is a genuinely meaningful value, like temperature (`°C`, `°F`). That's what `config/unit_semantics.json` (the one manually-maintained config file, §3.3) exists to declare — a minimum temperature requirement of "0°C" is a real constraint, not an absent one.

### 6.4 Scoring

Beyond K.O. checks, fields marked `Scoring` in the spreadsheet contribute points using one of several scoring functions (full/partial credit for a boolean capability, linearly scaled credit up to a cap, tiered thresholds, etc.) — weights and thresholds are entirely spreadsheet-driven.

### 6.5 VNA (Very Narrow Aisle) — an example of a two-layer detection rule

VNA is a specific AGV capability (operating in unusually narrow warehouse aisles) that's detected two ways and then enforced with `KO_BOOL_EXCLUSIVE`: (1) the LLM's Pass 4b extraction directly (`required_vna_capable` is a regular batch-extracted field, per OI-103), and (2) a text-pattern override that scans the raw PDF text for VNA-indicating keywords (e.g. the German term "Schmalgangstapler") regardless of what the LLM classified. If either signals VNA, the tender is treated as VNA-required — which means non-VNA suppliers are excluded, *and* VNA-capable suppliers are excluded from non-VNA tenders (a VNA machine is generally unsuitable for standard-width operation too).

---

## 7. Module Map

| Module | Responsibility |
|---|---|
| `app.py` | FastAPI web server; all pipeline orchestration (every pass described in §2); SSE streaming; `/analyze`, `/match`, `/rematch` endpoints |
| `src/matching.py` | The rule engine — operators, null rule, scoring, `validate_tender_values()` |
| `src/field_spec.py` | Generated; loads `fields.json` into Python objects |
| `src/data_loader.py` | Reads the SQLite database into `SupplierRecord` objects |
| `src/models.py` | Data classes: `Company`, `Product`, `FieldValue`, `SupplierRecord`, `TenderRun` |
| `src/json_repair.py` | Repairs malformed LLM JSON output; implements the 3-layer hallucination guard (§4.3) |
| `src/context_builder.py` | Assembles the LLM's system prompt (domain knowledge + field descriptions) |
| `src/tender_store.py` | Persists each analysis run for later replay/audit |
| `scripts/generate_all.py` | Reads both spreadsheets, writes everything under `config/` |
| `sync_airtable.py` | Pulls supplier data from Airtable into SQLite |

---

## 8. API & Frontend Integration

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Serves the frontend |
| `/analyze` | POST | Upload a PDF (or a JSON "replay" file for testing); returns a live SSE stream |
| `/match` | POST | Run matching directly against a pre-structured requirements JSON, skipping the LLM entirely |
| `/rematch` | POST | Re-run matching with user-edited overrides against a previously-cached extraction |
| `/db-status` | GET | Supplier count / database availability check |

**SSE event types**, all sent over the same `/analyze` stream: `step` (a named pipeline stage's progress), `log` (diagnostic detail, including every hallucination-guard message), `result` (the final, full result once everything finishes), `error` (a fatal failure), `warning` (a non-fatal data-quality issue, e.g. an AP0 spec violation that got auto-corrected).

---

## 9. Test Coverage

**322 tests, all unit-level** (plus a small integration smoke test), run via `pytest tests/`.

| Area | File(s) |
|---|---|
| Matching engine — operators, null rule, scoring, VNA | `test_matching_logic.py` (61 tests) |
| Hallucination guard — all 3 layers | `test_source_span_enforcement.py`, `test_source_span_l2_rescue.py`, `test_source_is_grounded.py` (21 tests), `test_source_confirms_value.py` / `_german.py` |
| AP0 spec consistency checks | `test_ap0_consistency.py` (28 tests) |
| Allowed-values validation | `test_validate_tender_values.py`, `test_find_invalid_ap0_fields.py` |
| Data loading | `test_data_loader.py` |
| Prompt/context construction | `test_context_builder.py`, `test_prompt_markers.py` |
| JSON repair | `test_json_repair_parser.py` |
| `/rematch` endpoint | `test_rematch_endpoint.py` |
| Persistence | `test_tender_store.py` |
| Golden-file regression against real captured tenders | `test_golden_extraction.py` |
| LLM preflight (Ollama reachability) | `tests/integration/test_llm_preflight.py` |

**Coverage gap worth naming explicitly:** none of these are true end-to-end tests that run the real LLM against real PDFs as part of the automated suite (that's what the ad hoc "backend-llm-tester" verification runs referenced throughout §5 are for — they're manual/agent-driven, not part of `pytest tests/`, and their findings currently live only in investigation notes, not in the committed test suite). This means the concrete regressions documented in §5.3, §5.5, and §5.6 have no automated regression test guarding against a recurrence — they were caught by manual live-corpus runs and could silently return.

---

## 10. Known Gaps & Technical Debt (non-hallucination-related)

| Area | Description |
|---|---|
| `CLAUDE.md` Data Flow section | Predates the multi-domain rollout described in §2 — still describes an AGV-only, `is_agv_amr`-flag-based pipeline. Worth a refresh; not done as part of this pass to avoid contradicting the repo's canonical doc without an explicit decision to update it. |
| Pass 4c arbitration | When Pass 4c's per-field re-check disagrees with Pass 4b and gets rejected by the guard, there's no fallback to Pass 4b's own (possibly correct) value — see §5.3's CompanyX aisle-width example. Tracked as an open design question, not yet resolved. |
| `/rematch` cache scoping | The last-analysis cache used by `/rematch` is a single, unscoped in-memory value — two concurrent uploads (different tabs, different users) can theoretically cross-contaminate each other's re-matched results. Rare in practice today but becomes a real risk as soon as the "edit requirements and re-match" feature sees routine use. |
| Sync script schema-driving | `sync_airtable.py` is not yet fully schema-driven end-to-end for every insert path. |

---

*For exact function signatures, JSON schemas, and module-level constants, see `docs/TECHNICAL_REFERENCE.md`.*
