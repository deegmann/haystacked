# OI-73 Sub-Spec: Scope Detection Generalisation — v0.1

**Status:** DRAFT — pending Senior Architect review  
**Pre-condition:** UFR Steps 1–6 complete ✅ (231 tests green, 2026-07-13)  
**Blocking:** `vehicle_type_template.txt` and `vehicle_types.json` are the primary sources of AGV-specific hardcoding that Step 7 must eliminate.

---

## 1. Problem Statement

After Steps 1–6, the AP0 ③ Scope Registry is the authoritative source for which scopes exist and how they nest. But the *classification logic* — how to detect which scope a tender belongs to — is still hardcoded in three places:

| Location | Hardcoded Content | Should Come From |
|---|---|---|
| `config/prompts/vehicle_type_template.txt` | LLM classification guide (VNA, Tugger, AMR descriptions) | ③ Scope Registry "Classification Guide" column |
| `config/vehicle_types.json` | keyword_map, vt_map, vna_subtypes, agv_detection_keywords, llm_guide | scope_registry.json (generated from AP0) |
| `src/context_builder.py` | `_FALLBACK_README` inline + 6 AGV-specific critical rules hardcoded in `build_system_context()` | `config/prompts/extraction_system.txt` (AP0-driven or manually maintained) |

Additionally:
- SA-10: `legacy_map` in `scope_registry.json` is built by a fragile heuristic (last path-segment) instead of an explicit "Canonical Name" column in ③ Scope Registry.

---

## 2. Scope

### In Scope (Step 7)
- Add **Canonical Name**, **Classification Guide**, and **Keywords** columns to ③ Scope Registry AP0 tab
- `generate_all.py`: emit `canonical_name`, `scope_guide`, `scope_keywords` per node into `scope_registry.json`
- `generate_all.py`: **generate** `config/prompts/scope_classification_template.txt` from scope guides (replaces manually-maintained `vehicle_type_template.txt`)
- `app.py`: Pass 4a reads from `scope_classification_template.txt` and maps output to `scope_id` via `scope_registry.json`
- `app.py`: keyword fallback for `is_agv_amr` reads from `scope_registry.json` (union of all leaf `scope_keywords`), replacing `vehicle_types.json` `agv_detection_keywords`
- `src/context_builder.py`: move the 6 inline AGV-specific critical matching rules from `build_system_context()` into `config/prompts/extraction_system.txt`; keep `_FALLBACK_README` as emergency fallback (no change)
- `vehicle_types.json`: reduce to non-AP0-expressible fields only (see §7)
- Fix SA-10: `legacy_map` built from `canonical_name` column, not heuristic

### Out of Scope (defer)
- Scope-based data_loader filtering (agv_type KO_IF_NEQ stays as-is; OI-52 Phase 2)
- New industry verticals
- Partial-classification UI surfacing (see §6 — handled by keyword fallback, no UI change)
- `_FALLBACK_README` migration (emergency fallback — only fires if `config/industry_readme.md` is missing)
- OI-52 Phase 2 (Product EAV / Extraction Persistence)

---

## 3. AP0 Changes — ③ Scope Registry Tab

Add three columns to the ③ Scope Registry tab (one row per scope node):

| Column | Type | Purpose |
|---|---|---|
| `canonical_name` | Text | Human-readable canonical name (e.g. "Forklift AGV") — replaces legacy_map heuristic (SA-10 fix) |
| `classification_guide` | Text | LLM classification guide for this scope level — what to look for in a tender document |
| `keywords` | Text (comma-separated) | Detection keywords — used for keyword-fallback is_agv_amr detection AND for context in classification guide |

Rows to fill:

| scope_id | canonical_name | classification_guide | keywords |
|---|---|---|---|
| `*` | Global | *(not used in classification — root is always entered)* | *(empty)* |
| `Logistics:AGV` | *(parent only)* | Tender requests Automated Guided Vehicles (AGV) or Autonomous Mobile Robots (AMR). Signals: AGV, AMR, VNA, intralogistics, automated warehouse transport, self-driving forklift, tugger train, underride robot | agv, amr, vna, forklift agv, tugger agv, intralogistics, ... |
| `Logistics:AGV:Forklift` | Forklift AGV | AGV that lifts/lowers loads using forks, masts, or telescoping arms. Includes VNA (very narrow aisle, <2m, >8m lift), reach trucks, counterbalanced forklifts. Choose this for any pallet-handling AGV. Signals: fork, mast, pallet, lift, racking, WMS, high-bay, aisle width constraint | forklift, fork, pallet, vna, reach truck, gabelstapler, schmalgangstapler, stapler, lift, racking |
| `Logistics:AGV:Tugger` | Tugger AGV | AGV that tows a train of trailers/trolleys without lifting. Does NOT interface with conveyor belts or racking. Signals: tugger, trailer train, milk run, Routenzug, towing | tugger, trailer, milk run, routenzug, schlepper, towing |
| `Logistics:AGV:AMR` | Mobile AMR | Autonomous mobile robot with free navigation (SLAM, contour). Typically lighter loads (<1000 kg). Includes goods-to-person (G2P), underride robots, shelf transport. Signals: AMR, SLAM, free navigation, underride, goods-to-person | amr, slam, underride, autonomous mobile robot, goods-to-person, g2p |

**VNA special handling** — VNA is a sub-property of Forklift AGV, not a separate scope leaf. The Forklift AGV classification guide describes VNA. The LLM still outputs `required_vna_capable` alongside the scope classification (see §4).

---

## 4. Generated Artifacts

### 4.1 `scope_registry.json` — new fields

`generate_all.py` adds per-node:
```json
{
  "scopes": {
    "Logistics:AGV:Forklift": {
      "scope_id": "Logistics:AGV:Forklift",
      "parent": "Logistics:AGV",
      "tab_name": "AGV_Forklift",
      "canonical_name": "Forklift AGV",
      "classification_guide": "AGV that lifts/lowers loads ...",
      "scope_keywords": ["forklift", "fork", "pallet", "vna", ...]
    }
  },
  "agv_detection_keywords": ["forklift", "fork", "pallet", "vna", "tugger", "amr", ...]
}
```

`agv_detection_keywords` = union of `scope_keywords` across all nodes with `parent != null` (i.e., all non-root nodes).

### 4.2 `config/prompts/scope_classification_template.txt` — **generated**

Generated by `generate_all.py` from the ③ Scope Registry. This file must be added to the "always generated" list in CLAUDE.md and is never manually edited.

Template structure (generated):
```
Classify the required AGV/AMR vehicle type from this tender document.
Output ONLY the JSON object shown below — nothing else.

Classification guide:
{for each leaf scope (is_leaf=true):}
  * "{canonical_name}" → {classification_guide}

THINK STEP BY STEP:
IMPORTANT: Only three values are valid: 'Forklift AGV', 'Tugger AGV', 'Mobile AMR'.
(1) Towing / trailer train? → required_agv_type='Tugger AGV'
(2) Light load + free navigation + no fork? → required_agv_type='Mobile AMR'
(3) Everything else (forks, pallets, racking) → required_agv_type='Forklift AGV'
    If VNA / narrow aisle / aisle<2m → required_vna_capable=true.

Fields:
- required_agv_type: MANDATORY — exactly one of: 'Forklift AGV', 'Tugger AGV', 'Mobile AMR'.
- required_vna_capable: true if VNA explicitly required; false/null otherwise.

DOCUMENT:
{text}

JSON:
{"required_agv_type":null,"required_vna_capable":null}
```

**Note:** The "THINK STEP BY STEP" tiebreaker rules are currently hardcoded in this generated template — they are part of the classification guide for the Logistics:AGV parent scope. These can be encoded as a `tiebreaker_rules` column in ③ Scope Registry in a future step. For now, generate_all.py emits them from a fixed snippet if the Logistics:AGV row's classification_guide contains certain markers. (Defer full generalisation — premature for 3 leaf types.)

### 4.3 `legacy_map` — built from `canonical_name`

Today:
```python
# Heuristic: last path-segment of scope_id → canonical name
```

After Step 7:
```python
legacy_map = {
    node["canonical_name"]: scope_id
    for scope_id, node in scopes.items()
    if node.get("canonical_name")
}
```

Assertion remains: all `_LEGACY_MAP` keys must be non-empty and all must appear in `scope_registry.json`.

---

## 5. Code Changes

### 5.1 `generate_all.py`

- `read_scope_registry(wb)`: read Canonical Name, Classification Guide, Keywords columns from ③ Scope Registry
- `_write_scope_registry(...)`: write `canonical_name`, `classification_guide`, `scope_keywords` per node; derive `agv_detection_keywords` (union of all non-root node keywords)
- `_legacy_map` built from `canonical_name` column, not heuristic
- Add generation of `config/prompts/scope_classification_template.txt` from leaf scope guides
- Add `scope_classification_template.txt` to generated file list; add assertion that template is non-empty

### 5.2 `app.py`

- `VEHICLE_TYPE_TEMPLATE` → renamed to `SCOPE_CLASSIFICATION_TEMPLATE`, loaded from `scope_classification_template.txt`
- `_AGV_DETECT_KWS`: read from `scope_registry.json["agv_detection_keywords"]` instead of `vehicle_types.json["agv_detection_keywords"]`
- `_VT_MAP_CFG`: built from `scope_registry.json["legacy_map"]` (already the case via `_LEGACY_MAP`; the separate `vehicle_types.json` vt_map can be retired)
- Pass 4a: no change to logic; only template source changes
- Pass 4a output field `required_agv_type` stays unchanged — still maps via `_VT_MAP_CFG` (now `_LEGACY_MAP`-derived) to `canonical_agv_type`
- Remove `vehicle_types.json` dependency for: `agv_detection_keywords`, `vt_map`, `keyword_map`

### 5.3 `src/context_builder.py`

**Current state (verified):** `config/prompts/extraction_system.txt` exists but is **not loaded** in `app.py`. `AGV_SYSTEM = build_system_context()` is the actual system prompt for all AGV passes (4a, 4b, 4c). `extraction_system.txt` is an orphaned file.

Move the 5 inline AGV-specific rules from `build_system_context()` into `config/prompts/extraction_system.txt`, and make `build_system_context()` include that file:

Rules to move:
```
5. AGV type classification: derive from properties, never from vendor label alone.
6. Tugger AGVs cannot interface with conveyor belts.
7. VDA 5050 is an open fleet interface standard.
8. CONSERVATIVE VALUE EXTRACTION (critical): ...
9. ANTI-HALLUCINATION (critical): ...
```

Rules 1–4 (general matching rules) stay inline in `build_system_context()` — they are not AGV-specific:
```
1. K.O. fields: a supplier failing even one K.O. criterion is fully excluded.
2. Cond. K.O. fields: score by default; hard filter ONLY when buyer marks them as "required".
3. Blank != zero: NULL means unknown, never absent.
4. OEM rebadging: same physical machine under multiple brand names shares specs.
```

Implementation: `build_system_context()` appends `_load_prompt("extraction_system.txt")` to the context string after rules 1–4. `extraction_system.txt` contains rules 5–9 as plain text. **Manually maintained** — domain knowledge, not AP0 data.

Note: `extraction_system.txt` already has an ANTI-HALLUCINATION rule (abbreviated form from an earlier state). The migration deduplicates vs. rule 9 in context_builder.py — keep the more complete form from context_builder.py, discard the shorter version in the file.

`_FALLBACK_README` stays unchanged — it only fires when `config/industry_readme.md` is missing.

---

## 6. Partial-Classification Handling

If Pass 4a returns an `required_agv_type` that fails AP0 validation (not one of the 3 canonical values), the existing fallback chain applies:
1. AP0-correction retry (up to 2 retries) — existing mechanism
2. Keyword fallback via `agv_type_keyword_fallback(text)` — existing mechanism; reads from `scope_registry.json["agv_detection_keywords"]` after this step
3. If still unresolved: warning SSE, `canonical_agv_type = None`, skip 4b/4c

No UI change. Partial-classification surfacing (UI confirmation dialog when LLM is unsure) is deferred — out of scope for Step 7.

---

## 7. vehicle_types.json — Retirement Plan

After Step 7, `vehicle_types.json` reduces to fields that cannot be expressed in AP0 or are not scope-registry-appropriate:

| Field | Disposition |
|---|---|
| `vt_map` | ✅ Retire — replaced by `legacy_map` from scope_registry.json |
| `keyword_map` | ✅ Retire — replaced by `scope_keywords` in scope_registry.json |
| `llm_guide` | ✅ Retire — replaced by `classification_guide` in scope_registry.json |
| `agv_detection_keywords` | ✅ Retire — replaced by `agv_detection_keywords` in scope_registry.json |
| `text_overrides` | ⚠ Keep — regex patterns cannot be expressed in AP0 columns; rename to `config/text_overrides.json` (deferred rename) |
| `4a_fields` | ⚠ Keep — needed to exclude these fields from 4b AP0 validation; consider moving to ③ Scope Registry "Classification Fields" column in future |
| `vna_subtypes` | ✅ Retire — VNA detection via `required_vna_capable` field output from Pass 4a (already in 4a JSON schema) |
| `vna_applicable_types` | ✅ Retire — move to scope_registry.json: Forklift node property `vna_applicable: true` |
| `vna_context_hint` | ⚠ Keep or move to scope_registry.json Forklift node — minor; decide at implementation |
| `vt_prompt_map` | ✅ Retire — derived from scope_id → `tab_name` mapping in scope_registry.json (already done in Steps 1–4) |
| `scoring_bucket_map` | ⚠ Keep or move to scope_registry.json — scoring-specific config |

**Target state:** `vehicle_types.json` contains only `text_overrides`, `4a_fields`, `vna_context_hint`, `scoring_bucket_map`. All content-classification data moved to AP0/scope_registry.json.

If `vehicle_types.json` shrinks to ≤4 fields, consider renaming to `config/agv_classification_overrides.json` to clarify its residual purpose.

---

## 8. agv_type KO — No Change

`required_agv_type` remains a `KO_IF_NEQ` field in AP0 / `fields.json`. The supplier's `agv_type` is still compared against the tender's `required_agv_type`. This KO is behavior-neutral in Step 7 — the canonical names and matching semantics are unchanged.

Retirement of `agv_type` as a KO field (replace with scope-based data_loader filtering) is deferred to OI-52 Phase 2 to avoid blast radius overlap.

---

## 9. Test Strategy

New tests to add (prefix `U_CL_`):

| ID | Test | Type |
|---|---|---|
| U_CL_01 | `scope_classification_template.txt` exists and contains all 3 leaf canonical names | Static |
| U_CL_02 | `scope_registry.json` contains `canonical_name` for all leaf scopes | Static |
| U_CL_03 | `scope_registry.json["agv_detection_keywords"]` is non-empty list | Static |
| U_CL_04 | `legacy_map` keys match `canonical_name` values (not heuristic) | Static |
| U_CL_05 | `agv_type_keyword_fallback()` reads from scope_registry.json (not vehicle_types.json) | Unit |
| U_CL_06 | `extraction_system.txt` contains CONSERVATIVE VALUE EXTRACTION rule | Static |

Golden files: all 5 tenders must produce **identical** match results (behavior-neutral).

---

## 10. Behavior-Neutrality Guarantee

Step 7 is **behavior-neutral**: the classification guide content moves from `vehicle_type_template.txt` → AP0-generated `scope_classification_template.txt`, but the content is identical. The LLM sees the same guidance as before.

The one exception: inline rules 5–9 moving from `context_builder.py` to `extraction_system.txt` — these must be verified to appear verbatim in `extraction_system.txt` after migration. If `extraction_system.txt` already contains equivalent rules, no new content is added.

---

## 11. Rollout Order

| Step | Action | Assertion |
|---|---|---|
| 11.1 | Add Canonical Name + Classification Guide + Keywords to ③ AP0 Scope Registry | Manual |
| 11.2 | Update `generate_all.py`: read new columns, emit to scope_registry.json, build legacy_map from canonical_name | pytest passes; scope_classification_template.txt generated |
| 11.3 | Update `app.py`: `_AGV_DETECT_KWS` from scope_registry.json; `VEHICLE_TYPE_TEMPLATE` → `scope_classification_template.txt` | pytest passes; golden tenders identical |
| 11.4 | Migrate context_builder.py inline rules 5–9 → extraction_system.txt | pytest passes; golden tenders identical |
| 11.5 | Retire vehicle_types.json fields per §7 table; remove dead imports in app.py + context_builder.py | pytest passes |
| 11.6 | Add U_CL_01–U_CL_06 tests | All green |
| 11.7 | Golden refresh (should be no-op; verify) | Identical to pre-Step-7 |

---

## 12. Open Questions for Review

1. **`text_overrides` home**: Keep in `vehicle_types.json` or rename file? Renaming is cleaner but adds a reference-update burden. Recommend defer rename to a housekeeping pass.

2. **`extraction_system.txt` ownership**: Should the migration of rules 5–9 be in this step, or is it a separate housekeeping item? The rules are already functionally present — this is a structural cleanup, not a behavior change. Recommend include in Step 7.

3. **`vna_context_hint`**: Used in `app.py` line ~720 to compose the VNA context string for 4b prompts. Could stay in vehicle_types.json or move to scope_registry.json Forklift node. Recommend move to scope_registry.json for completeness.

4. **`4a_fields` long-term**: Encodes which fields are resolved in Pass 4a and should not be re-validated in 4b. Could become a ③ Scope Registry "Pass 4a Resolved" column (boolean). Recommend defer — minor, correct as-is.
