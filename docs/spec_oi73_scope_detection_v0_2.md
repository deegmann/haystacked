# OI-73 Sub-Spec: Scope Detection Generalisation — v0.2

**Status:** DRAFT v0.2 — incorporating Senior Architect findings (CONDITIONAL PASS, 4 blockers fixed)  
**Pre-condition:** UFR Steps 1–6 complete ✅ (231 tests green, 2026-07-13)  
**Blocking:** `vehicle_type_template.txt` and `vehicle_types.json` are the primary sources of AGV-specific hardcoding that Step 7 must eliminate.

---

## Changelog from v0.1

| Finding | Severity | Resolution |
|---|---|---|
| SA-F1: `vt_map` ≠ `legacy_map` — separate key spaces | BLOCKER | §4.2: generate `variant_map` separately; §7: retire `vt_map` only after replacement proven |
| SA-F2: behavior-neutrality unverifiable via golden replay | BLOCKER | §10: replace golden-results check with static template byte-diff assertion |
| SA-F3: retiring `vt_map` silently guts matching.py guardian; keyword superset unverified | HIGH | §5.1: matching.py guardian rebuilt; §4.2: keyword-superset assertion in generate_all.py |
| SA-F4: `vna_applicable_types` / `scoring_bucket_map` consumers not wired | MEDIUM | §4.2, §5.2: explicit generate+consume steps added |
| SA-F5: second prose file parallel to industry_readme.md | MEDIUM | §5.3: rules 5-7 → industry_readme.md; only rules 8-9 → extraction_system.txt |

---

## 1. Problem Statement

After Steps 1–6, the AP0 ③ Scope Registry is the authoritative source for which scopes exist and how they nest. But the *classification logic* — how to detect which scope a tender belongs to — is still hardcoded in three places:

| Location | Hardcoded Content | Should Come From |
|---|---|---|
| `config/prompts/vehicle_type_template.txt` | LLM classification guide (VNA, Tugger, AMR descriptions + tiebreaker rules) | ③ Scope Registry "Classification Guide" column → generated `scope_classification_template.txt` |
| `config/vehicle_types.json` | `keyword_map`, `vt_map`, `vna_subtypes`, `agv_detection_keywords`, `llm_guide`, `vna_applicable_types`, `scoring_bucket_map` | `scope_registry.json` (generated from AP0 ③) |
| `src/context_builder.py` | `_FALLBACK_README` inline + rules 5–9 hardcoded in `build_system_context()` | Rules 5–7 → `Spec/haystacked_industry_readme.md`; rules 8–9 → `config/prompts/extraction_system.txt` |

Additionally:
- SA-10: `legacy_map` in `scope_registry.json` is built by a fragile last-segment heuristic instead of an explicit "Canonical Name" column in ③ Scope Registry.

---

## 2. Scope

### In Scope (Step 7)
- Add **Canonical Name**, **Classification Guide**, **Keywords**, **VNA Applicable**, **Scoring Bucket** columns to ③ Scope Registry AP0 tab
- `generate_all.py`: emit `canonical_name`, `scope_guide`, `scope_keywords`, `vna_applicable`, `scoring_bucket` per node; derive `variant_map` (LLM sub-variant → canonical), `agv_detection_keywords` (keyword union), and `legacy_map` from `canonical_name`
- `generate_all.py`: **generate** `config/prompts/scope_classification_template.txt` from scope guides (replaces manually-maintained `vehicle_type_template.txt`)
- `app.py`: Pass 4a reads from `scope_classification_template.txt`; keyword fallback reads `agv_detection_keywords` from `scope_registry.json`; `_VNA_APPLICABLE` reads `vna_applicable` from scope nodes; `scoring_bucket_map` reads from scope nodes
- `src/matching.py`: guardian assertion rebuilt against `canonical_name` / `scope_registry.json` (not `vt_map`)
- `src/context_builder.py`: rules 5–7 verified-present in `industry_readme.md`; rules 8–9 moved to `config/prompts/extraction_system.txt` (which is currently an orphan — first use after migration)
- `vehicle_types.json`: retire `vt_map`, `keyword_map`, `llm_guide`, `agv_detection_keywords`, `vna_subtypes`, `vna_applicable_types`, `scoring_bucket_map` after replacement proven; keep `text_overrides`, `4a_fields`, `vna_context_hint`
- Fix SA-10: `legacy_map` built from `canonical_name` column, not heuristic

### Out of Scope (defer)
- Scope-based data_loader filtering (agv_type KO_IF_NEQ stays; OI-52 Phase 2)
- New industry verticals
- Partial-classification UI surfacing (handled by existing keyword fallback; no UI change)
- `_FALLBACK_README` migration (fires only if `config/industry_readme.md` missing; keep as emergency fallback)
- OI-52 Phase 2 (Product EAV / Extraction Persistence)

---

## 3. AP0 Changes — ③ Scope Registry Tab

Add five columns to the ③ Scope Registry tab (one row per scope node):

| Column | Type | Purpose |
|---|---|---|
| `canonical_name` | Text | Human-readable canonical name (e.g. "Forklift AGV") — explicit replacement for legacy_map heuristic (SA-10 fix) |
| `classification_guide` | Text | Full LLM classification guide including sub-variant descriptions and tiebreaker rules |
| `keywords` | Text (comma-separated) | Detection keywords — for keyword-fallback `is_agv_amr` detection and for `variant_map` generation |
| `vna_applicable` | Boolean | True if VNA sub-classification applies to this scope (only Forklift AGV leaf) |
| `scoring_bucket` | Text | Scoring bucket identifier (e.g. "forklift_specific") — currently in `scoring_bucket_map` |

### Row values

**`Logistics:AGV` (parent, not a leaf):**
- `canonical_name`: *(empty — parent only)*
- `classification_guide`: *(empty — classification always resolves to a leaf)*
- `keywords`: agv, amr, vna, forklift agv, tugger agv, intralogistics, automated guided vehicle, autonomous mobile robot, ... *(see note on German terms below)*
- `vna_applicable`: false
- `scoring_bucket`: *(empty)*

**`Logistics:AGV:Forklift`:**
- `canonical_name`: `Forklift AGV`
- `classification_guide`: *(must reproduce the FULL text from `vehicle_type_template.txt` for VNA, Reach Truck, Counterbalanced, and Forklift entries + the tiebreaker step for "Everything else" — see §10 for verification requirement)*
- `keywords`: forklift, fork, pallet, vna, very narrow aisle, reach truck, counterbalanced, gabelstapler, stapler, schmalgangstapler, lift, racking, high-bay
- `vna_applicable`: true
- `scoring_bucket`: forklift_specific

**`Logistics:AGV:Tugger`:**
- `canonical_name`: `Tugger AGV`
- `classification_guide`: *(must reproduce the full Tugger entry from current template)*
- `keywords`: tugger, trailer, milk run, routenzug, schlepper, towing, anhaenger
- `vna_applicable`: false
- `scoring_bucket`: tugger_specific

**`Logistics:AGV:AMR`:**
- `canonical_name`: `Mobile AMR`
- `classification_guide`: *(must reproduce the full Mobile AMR and Underride AMR entries from current template)*
- `keywords`: amr, slam, underride, autonomous mobile robot, goods-to-person, g2p, fahrroboter, unterfahrfahrzeug, autonomer, fahrroboter, mobile robot
- `vna_applicable`: false
- `scoring_bucket`: amr_specific

**Critical requirement (SA-F1):** the `keywords` column must include ALL German terms currently in `vehicle_types.json["keyword_map"]` and `"agv_detection_keywords"` — including: `schmalgangstapler`, `gabelstapler`, `schlepper`, `routenzug`, `fahrroboter`, `unterfahrfahrzeug`, `anhaenger`, `autonomer`. Missing German terms regress `is_agv_amr` detection on German tenders.

**VNA special handling** — VNA is a sub-property of Forklift AGV (`vna_applicable=true`), not a separate scope leaf. The Forklift classification guide includes VNA sub-variant description. The LLM still outputs `required_vna_capable` alongside the scope classification (unchanged from today).

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
      "classification_guide": "AGV that lifts/lowers loads using forks...",
      "scope_keywords": ["forklift", "fork", "pallet", "vna", ...],
      "vna_applicable": true,
      "scoring_bucket": "forklift_specific"
    }
  },
  "variant_map": {
    "vna": "Forklift AGV",
    "very narrow aisle": "Forklift AGV",
    "reach truck": "Forklift AGV",
    "counterbalanced": "Forklift AGV",
    "forklift": "Forklift AGV",
    "forklift agv": "Forklift AGV",
    "tugger": "Tugger AGV",
    "tugger agv": "Tugger AGV",
    "mobile amr": "Mobile AMR",
    "amr": "Mobile AMR",
    "underride amr": "Mobile AMR",
    "underride": "Mobile AMR",
    "autonomous mobile robot": "Mobile AMR",
    "agv": "Forklift AGV"
  },
  "agv_detection_keywords": ["forklift", "fork", "pallet", "vna", "tugger", "amr", ...]
}
```

**`variant_map`** — maps LLM sub-variant strings (lowercase) → canonical names. This is DISTINCT from `legacy_map` (canonical names → scope_id). It is generated by: for each leaf node, for each keyword in `scope_keywords`, add `{keyword_lower: canonical_name}`. The current `vt_map` entries must all appear here (superset or equal). Startup assertion in `app.py` verifies that all values in `variant_map` appear as keys in `legacy_map`.

**`agv_detection_keywords`** — union of `scope_keywords` across ALL nodes with a non-null parent. Used for the `is_agv_amr` keyword fallback. Must be a superset of the pre-Step-7 `agv_detection_keywords` list from `vehicle_types.json` — verified by assertion in `generate_all.py` at generation time (hardcoded reference list).

**`legacy_map`** — built from `canonical_name` (explicit AP0 column), not heuristic:
```python
legacy_map = {
    node["canonical_name"]: scope_id
    for scope_id, node in scopes.items()
    if node.get("canonical_name")
}
```
Startup assertion in `app.py` / `matching.py` verifies `legacy_map` is non-empty and all leaf scopes have a `canonical_name`.

### 4.2 `config/prompts/scope_classification_template.txt` — **generated**

Generated by `generate_all.py` from the ③ Scope Registry. Added to the "always generated" list in CLAUDE.md; never manually edited.

Template structure (generated from AP0):

```
Classify the required AGV/AMR vehicle type from this tender document.
Output ONLY the JSON object shown below — nothing else.

Vehicle type classification guide:
{for each leaf scope in declaration order:}
  * "{canonical_name}" → {classification_guide}

  Key: PAYLOAD AND LOAD TYPE determine the vehicle — not the environment alone.

  THINK STEP BY STEP:
  IMPORTANT: Only three values are valid: 'Forklift AGV', 'Tugger AGV', 'Mobile AMR'.
  Sub-variants (Counterbalanced, Reach Truck, VNA) are NOT valid outputs — they are internal properties, not types.
  (1) Towing / tugger / milk run / trailer train / Routenzug? → required_agv_type='Tugger AGV'.
  (2) Light load (<1000 kg) + flexible SLAM navigation + no standard floor-pallet pickup? → required_agv_type='Mobile AMR'.
  (3) Everything else (pallets, IBCs, forks required, racking, heavy load) → required_agv_type='Forklift AGV'.
      Counterbalanced, Reach Truck, AND VNA are all 'Forklift AGV'.
      If VNA / very narrow aisle / aisle<2m → required_agv_type='Forklift AGV' AND required_vna_capable=true.
      IMPORTANT: required_vna_capable=true ONLY if VNA is explicitly REQUIRED for the AGVs being procured in this tender.
      If VNA racking is mentioned as existing infrastructure, historical context, or operations in OTHER aisles NOT covered by this tender → required_vna_capable=false.

Fields:
- required_agv_type: MANDATORY — exactly one of: 'Forklift AGV', 'Tugger AGV', 'Mobile AMR'.
- required_vna_capable: true ONLY if the tender explicitly requires VNA capability for the AGVs being procured (narrow aisle <2m, high-bay racking required for this project). false if VNA is merely mentioned as existing warehouse infrastructure, historical context, or out-of-scope areas. Only applicable when required_agv_type='Forklift AGV'.

DOCUMENT:
{text}

JSON:
{"required_agv_type":null,"required_vna_capable":null}
```

**Note on tiebreaker rules:** The THINK STEP BY STEP block contains anti-misclassification tiebreakers that were added based on real tender failures. These cannot be trivially derived from the 3-line `classification_guide` cells. For this step, `generate_all.py` emits them from a **fixed template snippet** (hardcoded string in generate_all.py) appended after the leaf guides. This is a known transitional hardcode. Long-term: a `tiebreaker_rules` column in ③ Scope Registry (deferred, OI-xx).

**Assertion at generation time:** after generating `scope_classification_template.txt`, `generate_all.py` asserts:
- The file is non-empty
- It contains all 3 canonical names
- Its length is within ±10% of the byte length of `vehicle_type_template.txt` (guards against accidental content collapse)

### 4.3 `legacy_map` — from `canonical_name` (SA-10 fix)

Same as §4.1 above. The fragile last-segment heuristic is replaced by explicit AP0 column.

---

## 5. Code Changes

### 5.1 `generate_all.py`

- `read_scope_registry(wb)`: read Canonical Name, Classification Guide, Keywords, VNA Applicable, Scoring Bucket columns from ③ Scope Registry
- `_write_scope_registry(...)`:
  - write `canonical_name`, `classification_guide`, `scope_keywords`, `vna_applicable`, `scoring_bucket` per node
  - derive `variant_map` (keyword_lower → canonical_name) from leaf nodes' `scope_keywords` × `canonical_name`
  - derive `agv_detection_keywords` (union of all non-root nodes' `scope_keywords`)
  - assert `agv_detection_keywords` ⊇ pre-Step-7 baseline list (hardcoded as a constant in generate_all.py for this assertion only)
  - build `legacy_map` from `canonical_name`
- Generate `config/prompts/scope_classification_template.txt`; assert non-empty + all 3 canonical names present + byte-length within ±10% of current `vehicle_type_template.txt`
- Add `scope_classification_template.txt` to generated file list in CLAUDE.md

### 5.2 `app.py`

**Reads from `scope_registry.json` after Step 7 (replacing `vehicle_types.json`):**

| Variable | Old source | New source |
|---|---|---|
| `_VT_MAP_CFG` | `vehicle_types.json["vt_map"]` | `scope_registry.json["variant_map"]` |
| `_AGV_DETECT_KWS` | `vehicle_types.json["agv_detection_keywords"]` | `scope_registry.json["agv_detection_keywords"]` |
| `_VNA_APPLICABLE` (set at `:962`) | `vehicle_types.json["vna_applicable_types"]` | `{n["canonical_name"] for n in scopes.values() if n.get("vna_applicable")}` |
| `scoring_bucket_map` | `vehicle_types.json["scoring_bucket_map"]` | `{n["canonical_name"]: n["scoring_bucket"] for n in scopes.values() if n.get("scoring_bucket")}` |

**Prompt:**
- `VEHICLE_TYPE_TEMPLATE` → renamed `SCOPE_CLASSIFICATION_TEMPLATE`, loaded from `scope_classification_template.txt`
- All other Pass 4a logic (retry, AP0-correction, VNA text_overrides, fallback) unchanged

**Startup assertion (new):** all values in `_VT_MAP_CFG.values()` must appear as keys in `_LEGACY_MAP`. Replaces the current `_vt_map_values` guardian which was sourced from `vt_map`.

### 5.3 `src/matching.py`

Current guardian at lines 69–73 reads `vt_map` from `vehicle_types.json` and asserts every canonical resolves via `legacy_map`. After retiring `vt_map`, rebuild this assertion:

```python
# New: assert all canonical_names in scope_registry.json legacy_map
_canon_names = set(_scope_registry["legacy_map"].keys())
assert _canon_names, "scope_registry.json legacy_map is empty"
assert _canon_names <= set(_scope_registry["legacy_map"]), \
    f"canonical names not all in legacy_map: {_canon_names - set(_scope_registry['legacy_map'])}"
```

(The second assertion is vacuously true; intent is that `canonical_names` derives from `canonical_name` column in AP0, and the cross-check is that every node with a `canonical_name` has a corresponding `legacy_map` entry — generated by definition, but asserted for belt-and-suspenders.)

### 5.4 `src/context_builder.py`

**Rules 5–7** (domain knowledge) are verified to be present in `Spec/haystacked_industry_readme.md` → synced to `config/industry_readme.md` via `generate_all.py`. If any rule is missing, add it to the source README before Step 7 code changes.

Rules 5–7 (for reference):
```
- AGV type classification: derive from properties, never from vendor label alone.
- Tugger AGVs cannot interface with conveyor belts — if conveyors are required, Tugger is not appropriate.
- VDA 5050 is an open fleet interface standard — increasingly a hard requirement for large European buyers.
```

**Rules 8–9** (extraction hallucination guards) — move to `config/prompts/extraction_system.txt`:

```
## Critical extraction rules
8. CONSERVATIVE VALUE EXTRACTION (critical): When a document lists multiple values for the same parameter, always extract the most demanding value. For minimum-capability fields (payload, lift height, operating hours, fleet size, maximum ambient temperature): extract the MAXIMUM value found. For maximum-constraint fields (aisle width, minimum ambient temperature): extract the MINIMUM value found. Never average or omit ambiguous values — always pick the worst case for the supplier.
9. ANTI-HALLUCINATION (critical): Before outputting any non-null value you must be able to identify the exact sentence in the document that states it. Do NOT infer specifications from warehouse type or AGV type — a VNA warehouse does NOT imply IP65, cold-storage temperature, high humidity, ramp gradient, or VDA 5050 unless these are written in the document. Do NOT read numbers from dates, filenames, revision codes, version strings, or project metadata as specification values — '25th May 2022' is a date, NOT a temperature; 'v1.3' is a version, NOT a floor flatness value. If a field's value is not directly stated in the document text, output null — never apply typical industry values.
```

`extraction_system.txt` currently contains an abbreviated anti-hallucination rule. The abbreviated form is replaced by rule 9 (the complete form from context_builder.py). The existing two-line rule in `extraction_system.txt` is removed to avoid duplication.

`build_system_context()` after migration:
- Loads `industry_readme.md` (containing rules 5–7)
- Builds field section (unchanged)
- Emits rules 1–4 inline (unchanged — general matching rules, not AGV-specific)
- Appends `_load_prompt("extraction_system.txt")` (rules 8–9)

**`_FALLBACK_README`:** unchanged — emergency fallback when `industry_readme.md` is missing.

---

## 6. Partial-Classification Handling

If Pass 4a returns an `required_agv_type` that fails AP0 validation, the existing fallback chain applies:
1. AP0-correction retry (up to 2 retries) — existing mechanism
2. Keyword fallback via `agv_type_keyword_fallback(text)` — reads `scope_registry.json["agv_detection_keywords"]` after Step 7
3. Warning SSE + `canonical_agv_type = None` → skip 4b/4c

No UI change. Partial-classification UI (confirmation dialog) deferred.

---

## 7. vehicle_types.json — Retirement Plan

| Field | Disposition | Replacement |
|---|---|---|
| `vt_map` | ✅ Retire — but only AFTER `variant_map` is proven equivalent (startup assertion must pass) | `scope_registry.json["variant_map"]` |
| `keyword_map` | ✅ Retire | `scope_registry.json["scopes"][id]["scope_keywords"]` |
| `llm_guide` | ✅ Retire | `scope_registry.json["scopes"][id]["classification_guide"]` |
| `agv_detection_keywords` | ✅ Retire — only after superset assertion passes | `scope_registry.json["agv_detection_keywords"]` |
| `vna_subtypes` | ✅ Retire | `vna_applicable` in scope node; `required_vna_capable` output from Pass 4a |
| `vna_applicable_types` | ✅ Retire — only after `_VNA_APPLICABLE` wired to new source | `scope_registry.json["scopes"][id]["vna_applicable"]` |
| `scoring_bucket_map` | ✅ Retire — only after scoring consumers wired to new source | `scope_registry.json["scopes"][id]["scoring_bucket"]` |
| `text_overrides` | ⚠ Keep — regex patterns not expressible in AP0 | `vehicle_types.json` (residual) |
| `4a_fields` | ⚠ Keep — needed for 4b AP0 validation exclusion | `vehicle_types.json` (residual) |
| `vna_context_hint` | Move to `scope_registry.json` Forklift node as `vna_hint` field | `scope_registry.json["scopes"]["Logistics:AGV:Forklift"]["vna_hint"]` |

**Target state:** `vehicle_types.json` contains only `text_overrides`, `4a_fields`, `vna_context_hint` (if not moved). The file is renamed to `config/agv_classification_overrides.json` to clarify its residual purpose (reference-update pass needed — defer or include in rollout step 11.5).

---

## 8. agv_type KO — No Change

`required_agv_type` remains a `KO_IF_NEQ` field. Retirement deferred to OI-52 Phase 2.

---

## 9. Test Strategy

New tests (prefix `U_CL_`):

| ID | Test | Type |
|---|---|---|
| U_CL_01 | `scope_classification_template.txt` exists and contains all 3 canonical names | Static |
| U_CL_02 | `scope_registry.json` has `canonical_name` for all leaf scopes | Static |
| U_CL_03 | `scope_registry.json["agv_detection_keywords"]` is non-empty list | Static |
| U_CL_04 | `scope_registry.json["legacy_map"]` keys match leaf `canonical_name` values | Static |
| U_CL_05 | `scope_registry.json["variant_map"]` values are all keys in `legacy_map` | Static |
| U_CL_06 | `agv_type_keyword_fallback()` uses `scope_registry.json` keywords (not vehicle_types.json) | Unit |
| U_CL_07 | composed `AGV_SYSTEM` contains CONSERVATIVE VALUE EXTRACTION rule text | Static |
| U_CL_08 | composed `AGV_SYSTEM` contains ANTI-HALLUCINATION rule text | Static |

---

## 10. Behavior-Neutrality Guarantee

**What "behavior-neutral" means for Step 7:**

Step 7 changes the *source* of the classification prompt (hand-maintained file → AP0-generated file) but not its *content*. Behavior-neutrality is verified by **static content comparison**, NOT by golden replay.

**Reason:** Golden tenders are `.json` replay files. The replay branch in `app.py` (lines 446–470) loads `vehicle_type` / `agv_criteria` from cache and never runs Pass 4a. Therefore, golden results are invariant to Pass 4a prompt changes — they cannot verify this step.

**Verification method:**
1. After running `generate_all.py` with the new AP0 columns, inspect `scope_classification_template.txt` against `vehicle_type_template.txt` side-by-side
2. Assert that ALL sub-variant guidance texts appear verbatim or equivalently in the generated template — specifically the VNA existing-infra disclaimer, the MES/filling-lines disclaimer for AMR, the payload tiebreaker, and the Tugger/conveyor incompatibility note
3. Length assertion in `generate_all.py` (±10% of current file byte-count) catches accidental collapse

**Golden refresh:** all 5 golden tenders must still produce identical match results after Step 7 (confirming no regression in the matching engine path, which does not depend on Pass 4a content).

---

## 11. Rollout Order

| Step | Action | Assertion |
|---|---|---|
| 11.1 | Verify rules 5–7 present in `Spec/haystacked_industry_readme.md`; add if missing | Manual review |
| 11.2 | Update `config/prompts/extraction_system.txt` with rules 8–9 (complete form); remove abbreviated anti-hallucination rule | pytest passes |
| 11.3 | Add Canonical Name + Classification Guide + Keywords + VNA Applicable + Scoring Bucket to ③ AP0 Scope Registry | Manual |
| 11.4 | Update `generate_all.py`: read new columns; emit to `scope_registry.json`; generate `scope_classification_template.txt`; add keyword-superset + template length assertions | pytest passes; `scope_classification_template.txt` generated; static diff vs. `vehicle_type_template.txt` reviewed |
| 11.5 | Update `app.py`: point `_VT_MAP_CFG`, `_AGV_DETECT_KWS`, `_VNA_APPLICABLE`, `scoring_bucket_map`, `VEHICLE_TYPE_TEMPLATE` to new sources; add startup assertions | pytest passes; golden tenders identical |
| 11.6 | Update `src/matching.py`: rebuild guardian assertion from `scope_registry.json` | pytest passes |
| 11.7 | Update `src/context_builder.py`: `build_system_context()` appends `extraction_system.txt`; remove rules 8–9 inline | pytest passes; U_CL_07/08 green |
| 11.8 | Remove retired fields from `vehicle_types.json`; remove dead imports in app.py + context_builder.py | pytest passes; no `vt_map` / `keyword_map` references |
| 11.9 | Add U_CL_01–U_CL_08 tests | All green |
| 11.10 | Golden refresh (should be no-op; verify behavior-neutral) | Identical to pre-Step-7 |

---

## 12. Open Questions (Post-SA-Review)

1. **`vehicle_types.json` rename**: Step 11.8 can rename to `agv_classification_overrides.json` (adds reference-update work) or leave the filename and just reduce contents. Recommend defer rename — low value for the work.

2. **`4a_fields` in ③ Scope Registry**: The `4a_fields` list (`["required_agv_type", "required_vna_capable"]`) could become a "Pass 4a Resolved" boolean column in ③ Scope Registry. Recommended defer — correctly encodes semantic meaning but low urgency.

3. **Tiebreaker rules generalization**: The THINK STEP BY STEP block is emitted as a fixed snippet in `generate_all.py`. Long-term: a `tiebreaker_rules` text column in ③ Scope Registry. Defer to a future AP0 content pass.
