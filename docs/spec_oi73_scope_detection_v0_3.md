# OI-73 Sub-Spec: Scope Detection Generalisation — v0.3

**Status:** DRAFT v0.3 — pending final Senior Architect (Fable) review  
**Pre-condition:** UFR Steps 1–6 complete ✅ (231 tests green, 2026-07-13)

---

## Changelog

| Version | Round | Findings | Resolution |
|---|---|---|---|
| v0.1 | Initial draft | — | — |
| v0.2 | SA CONDITIONAL PASS | F1: vt_map ≠ legacy_map (BLOCKER); F2: behavior-neutrality via golden replay invalid (BLOCKER); F3: vt_map retirement guts matching.py guardian (HIGH); F4: vna_applicable/scoring_bucket consumers unwired (MEDIUM); F5: second prose file (MEDIUM) | variant_map added; static diff verification; guardian rebuilt; vna_applicable+scoring_bucket columns added; rules 5-7 → industry_readme.md |
| v0.3 | Tech Lead code inventory | G1: vna_subtypes/`_VNA_CFG` retirement broken; G2: vt_prompt_map dropped from table; G3: matching.py guardian vacuously true; G4: 3 consumers missing from §5.2 table; G5: vna_context_hint consumer unwired; G6: `_load_agv_keywords()` in context_builder.py unaddressed | See fixes below |

**v0.3 fixes:**
- **G1:** `vna_subtypes` → ⚠ Keep in vehicle_types.json residual (same character as `text_overrides`)
- **G2:** `vt_prompt_map` → ✅ Retire, derived from `scope_registry.json` tab_names + canonical_names
- **G3:** matching.py guardian code fixed — `_canon_names` now built from `scopes[].canonical_name`, not from `legacy_map.keys()` (which was vacuously true)
- **G4/G5:** `_VNA_CFG`, `vna_context_hint`, `vt_prompt_map`/`_AGV_TYPE_TEMPLATES`, `_VALID_VTS` added to §5.2 mapping table
- **G6:** `_load_agv_keywords()` / `AGV_KEYWORDS` update added to §5.4

---

## 1. Problem Statement

After Steps 1–6, the AP0 ③ Scope Registry is the authoritative source for which scopes exist and how they nest. But the *classification logic* — how to detect which scope a tender belongs to — is still hardcoded in three places:

| Location | Hardcoded Content | Should Come From |
|---|---|---|
| `config/prompts/vehicle_type_template.txt` | LLM classification guide (VNA, Tugger, AMR descriptions + tiebreaker rules) | ③ Scope Registry "Classification Guide" column → generated `scope_classification_template.txt` |
| `config/vehicle_types.json` | `keyword_map`, `vt_map`, `vna_applicable_types`, `scoring_bucket_map`, `vt_prompt_map`, `llm_guide`, `agv_detection_keywords` | `scope_registry.json` (generated from AP0 ③) |
| `src/context_builder.py` | `_FALLBACK_README` inline + rules 5–9 hardcoded in `build_system_context()` | Rules 5–7 → `Spec/haystacked_industry_readme.md`; rules 8–9 → `config/prompts/extraction_system.txt` |

Additionally:
- SA-10: `legacy_map` built by fragile last-segment heuristic → replace with explicit "Canonical Name" column in ③ Scope Registry

---

## 2. Scope

### In Scope (Step 7)
- Add **Canonical Name**, **Classification Guide**, **Keywords**, **VNA Applicable**, **Scoring Bucket**, **VNA Hint** columns to ③ Scope Registry AP0 tab
- `generate_all.py`: emit `canonical_name`, `scope_guide`, `scope_keywords`, `vna_applicable`, `scoring_bucket`, `vna_hint` per node; derive `variant_map`, `agv_detection_keywords`, `legacy_map`
- `generate_all.py`: **generate** `config/prompts/scope_classification_template.txt`
- `app.py`: migrate 8 variables from `vehicle_types.json` → `scope_registry.json` (full list in §5.2)
- `src/matching.py`: rebuild guardian assertion (non-vacuous)
- `src/context_builder.py`: `_load_agv_keywords()` → reads `scope_registry.json`; `build_system_context()` appends `extraction_system.txt`; rules 8–9 removed inline
- `vehicle_types.json`: retire 7 fields; keep 4 residual fields

### Out of Scope (defer)
- Scope-based data_loader filtering (agv_type KO_IF_NEQ stays; OI-52 Phase 2)
- New industry verticals
- Partial-classification UI
- `_FALLBACK_README` migration
- OI-52 Phase 2

---

## 3. AP0 Changes — ③ Scope Registry Tab

Add six columns (one row per scope node):

| Column | Type | Purpose |
|---|---|---|
| `canonical_name` | Text | Human-readable canonical name (e.g. "Forklift AGV") — replaces legacy_map heuristic (SA-10) |
| `classification_guide` | Text | Full LLM classification guide — sub-variant descriptions for this leaf |
| `keywords` | Text (comma-separated) | Detection keywords — drives `variant_map` + `agv_detection_keywords` |
| `vna_applicable` | Boolean | True only on Forklift AGV leaf — drives `_VNA_APPLICABLE` |
| `scoring_bucket` | Text | Scoring bucket id (e.g. "forklift_specific") — replaces `scoring_bucket_map` |
| `vna_hint` | Text | VNA context string appended to 4b prompt (currently `vna_context_hint` in vehicle_types.json) |

### Row values

**`*` (Global root):** all new columns empty.

**`Logistics:AGV` (parent, not a leaf):**
- `canonical_name`: *(empty)*
- `classification_guide`: *(empty — classification always resolves to a leaf)*
- `keywords`: agv, amr, vna, forklift agv, tugger agv, intralogistics, automated guided vehicle, autonomous mobile robot, agv amr, *(+ full union of leaf keywords — see Critical Requirement below)*
- `vna_applicable`: false / empty
- `scoring_bucket`: *(empty)*
- `vna_hint`: *(empty)*

**`Logistics:AGV:Forklift`:**
- `canonical_name`: `Forklift AGV`
- `classification_guide`: *(must reproduce the FULL text from `vehicle_type_template.txt` for VNA, Reach Truck, Counterbalanced, Forklift entries — see §10 verification)*
- `keywords`: forklift, fork, pallet, vna, very narrow aisle, reach truck, counterbalanced, gabelstapler, stapler, schmalgangstapler, lift, racking, high-bay, agv
- `vna_applicable`: true
- `scoring_bucket`: forklift_specific
- `vna_hint`: `VNA (very narrow aisle) operation is required.` *(current value from vehicle_types.json)*

**`Logistics:AGV:Tugger`:**
- `canonical_name`: `Tugger AGV`
- `classification_guide`: *(full Tugger entry from current template)*
- `keywords`: tugger, trailer, milk run, routenzug, schlepper, towing, anhaenger, tugger agv
- `vna_applicable`: false / empty
- `scoring_bucket`: tugger_specific
- `vna_hint`: *(empty)*

**`Logistics:AGV:AMR`:**
- `canonical_name`: `Mobile AMR`
- `classification_guide`: *(full Mobile AMR + Underride AMR entries from current template)*
- `keywords`: amr, slam, underride, autonomous mobile robot, goods-to-person, g2p, fahrroboter, unterfahrfahrzeug, autonomer, mobile robot, mobile amr, underride amr
- `vna_applicable`: false / empty
- `scoring_bucket`: amr_specific
- `vna_hint`: *(empty)*

**Critical requirement (SA-F1 + G1):** the `keywords` column must include ALL German terms currently in `vehicle_types.json["keyword_map"]` and `"agv_detection_keywords"`: `schmalgangstapler`, `gabelstapler`, `schlepper`, `routenzug`, `fahrroboter`, `unterfahrfahrzeug`, `anhaenger`, `autonomer`. Missing German terms regress `is_agv_amr` detection. Verified at generation time by keyword-superset assertion (§5.1).

**VNA special handling:** VNA is a sub-property of Forklift AGV (`vna_applicable=true`), not a separate scope leaf. `vna_subtypes` stays in `vehicle_types.json` residual (see §7, G1 fix).

---

## 4. Generated Artifacts

### 4.1 `scope_registry.json` — new fields

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
      "scoring_bucket": "forklift_specific",
      "vna_hint": "VNA (very narrow aisle) operation is required."
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
  "legacy_map": {
    "Forklift AGV": "Logistics:AGV:Forklift",
    "Tugger AGV": "Logistics:AGV:Tugger",
    "Mobile AMR": "Logistics:AGV:AMR"
  },
  "agv_detection_keywords": ["forklift", "fork", "pallet", "vna", "tugger", "amr", ...]
}
```

**`variant_map`** (NEW) — maps LLM sub-variant strings (lowercase) → canonical names. DISTINCT from `legacy_map` (canonical → scope_id). Generated from: for each leaf node, for each keyword in `scope_keywords`, emit `{keyword_lower: canonical_name}`. Replaces `vehicle_types.json["vt_map"]`. Startup assertion: all values in `variant_map` appear as keys in `legacy_map`.

**`agv_detection_keywords`** (NEW) — union of `scope_keywords` across all non-root nodes. Used for `is_agv_amr` keyword fallback. Superset assertion at generation time vs. pre-Step-7 baseline list.

**`legacy_map`** (CHANGED) — built from `canonical_name` AP0 column (explicit), not heuristic:
```python
legacy_map = {
    node["canonical_name"]: scope_id
    for scope_id, node in scopes.items()
    if node.get("canonical_name")
}
```

### 4.2 `config/prompts/scope_classification_template.txt` — **generated**

Generated by `generate_all.py` from ③ Scope Registry leaf nodes. Added to "always generated" list in CLAUDE.md; never manually edited.

Template structure:
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

**THINK STEP BY STEP block** is emitted from a fixed snippet in `generate_all.py`. Known transitional hardcode. Long-term: `tiebreaker_rules` column in ③ Scope Registry (deferred).

**Assertions at generation time:**
- File is non-empty
- Contains all 3 canonical names
- Byte-length within ±10% of current `vehicle_type_template.txt`

---

## 5. Code Changes

### 5.1 `generate_all.py`

- `read_scope_registry(wb)`: read Canonical Name, Classification Guide, Keywords, VNA Applicable, Scoring Bucket, VNA Hint columns from ③ Scope Registry
- `_write_scope_registry(...)`:
  - write new per-node fields to `scope_registry.json`
  - derive `variant_map` from leaf `scope_keywords × canonical_name`
  - derive `agv_detection_keywords` (union of non-root `scope_keywords`)
  - assert `agv_detection_keywords` ⊇ pre-Step-7 baseline (hardcoded constant in generate_all.py for this assertion only)
  - build `legacy_map` from `canonical_name` (not heuristic)
- Generate `scope_classification_template.txt`; assert non-empty + canonical names present + ±10% byte-length
- Add `scope_classification_template.txt` to CLAUDE.md generated file list

### 5.2 `app.py` — complete variable migration table

All reads from `_vehicle_cfg` (vehicle_types.json) that are being migrated:

| Variable | Line(s) | Old source | New source |
|---|---|---|---|
| `_VT_MAP_CFG` | 248, 466, 693, 697, 927, 931 | `vehicle_types.json["vt_map"]` | `scope_registry.json["variant_map"]` |
| `_VNA_CFG` | 249, 700 | `vehicle_types.json["vna_subtypes"]` | ⚠ **Keep** — see §7 G1; no source change |
| `_VNA_APPLICABLE` | 251, 962 | `vehicle_types.json["vna_applicable_types"]` | `{n["canonical_name"] for n in scopes.values() if n.get("vna_applicable")}` |
| `_AGV_DETECT_KWS` | 252, 557 | `vehicle_types.json["agv_detection_keywords"]` | `scope_registry.json["agv_detection_keywords"]` |
| `_VALID_VTS` | 268, 1066, 1070 | `vehicle_types.json["scoring_bucket_map"].keys()` | `{n["canonical_name"] for n in scopes.values() if n.get("scoring_bucket")}` |
| `_AGV_TYPE_TEMPLATES` | 304–307 | `vehicle_types.json["vt_prompt_map"]` | `{n["canonical_name"]: _load_prompt(f"extraction_template_{n['tab_name'].lower()}.txt") for n in scopes.values() if n.get("canonical_name")}` |
| `vna_context` | 740 | `vehicle_types.json["vna_context_hint"]` | `next((n.get("vna_hint","") for n in scopes.values() if n.get("vna_applicable")), "")` — evaluated once at startup as `_VNA_CONTEXT_HINT` |
| `scoring_bucket_map` | 1158 | `vehicle_types.json["scoring_bucket_map"]` | `{n["canonical_name"]: n["scoring_bucket"] for n in scopes.values() if n.get("scoring_bucket")}` |

**Prompt:**
- `VEHICLE_TYPE_TEMPLATE` → renamed `SCOPE_CLASSIFICATION_TEMPLATE`, loaded from `scope_classification_template.txt`

**Startup assertion (new):** all values in `_VT_MAP_CFG.values()` must appear as keys in `_LEGACY_MAP`.

**`AGV_KEYWORDS` import from context_builder:** after §5.4 change, `AGV_KEYWORDS` is read from `scope_registry.json` — import still works; no change to the import line.

### 5.3 `src/matching.py`

Current guardian at lines 69–73 reads `vt_map` from `vehicle_types.json`. After retiring `vt_map`, rebuild:

```python
# Guardian S2: every canonical_name in scope_registry must resolve via legacy_map
_canon_names = {
    node["canonical_name"]
    for node in _scope_registry["scopes"].values()
    if node.get("canonical_name")
}
assert _canon_names, "scope_registry.json has no nodes with canonical_name — run generate_all.py"
assert _canon_names <= set(_LEGACY_MAP), (
    f"canonical_names without legacy_map entry: {_canon_names - set(_LEGACY_MAP)}"
)
```

This is non-vacuous: `_canon_names` is derived from `scopes[].canonical_name` (AP0 column), not from `legacy_map.keys()`.

### 5.4 `src/context_builder.py`

**A. `_load_agv_keywords()` / `AGV_KEYWORDS` — migrate data source (G6 fix)**

Current: reads `vehicle_types.json["keyword_map"]` → `{"Forklift AGV": [...], "Tugger AGV": [...], "Mobile AMR": [...]}`.

After Step 7: reads `scope_registry.json` and builds same structure:

```python
_SCOPE_REGISTRY = Path(__file__).parent.parent / "config" / "scope_registry.json"

def _load_agv_keywords() -> dict:
    if _SCOPE_REGISTRY.exists():
        reg = json.loads(_SCOPE_REGISTRY.read_text())
        return {
            node["canonical_name"]: node.get("scope_keywords", [])
            for node in reg.get("scopes", {}).values()
            if node.get("canonical_name")
        }
    return {}
```

`AGV_KEYWORDS` structure is unchanged — `agv_type_keyword_fallback()` works without modification. `VEHICLE_TYPES` constant no longer needed in context_builder.py.

**B. Rules migration — context_builder.py → extraction_system.txt (SA-F5)**

**Rules 5–7** (domain knowledge): verified present in `Spec/haystacked_industry_readme.md` before Step 7 code changes. If any are missing, add to source README first.

Rules 5–7 for reference:
```
- AGV type classification: derive from properties, never from vendor label alone.
- Tugger AGVs cannot interface with conveyor belts — if conveyors are required, Tugger is not appropriate.
- VDA 5050 is an open fleet interface standard — increasingly a hard requirement for large European buyers.
```

**Rules 8–9**: move inline strings from `build_system_context()` to `config/prompts/extraction_system.txt`. The current abbreviated anti-hallucination rule in `extraction_system.txt` is replaced by the complete form of rule 9 from context_builder.py.

`build_system_context()` after migration:
1. Load `industry_readme.md` (contains rules 5–7 via Spec sync)
2. Build field section (unchanged)
3. Emit rules 1–4 inline (general matching rules — not AGV-specific; unchanged)
4. Append `_load_prompt("extraction_system.txt")` (rules 8–9)

`_FALLBACK_README`: unchanged (emergency fallback only).

**Test U_CL_07/08** verify the composed `AGV_SYSTEM` string contains key phrases from rules 8 and 9 verbatim.

---

## 6. Partial-Classification Handling

Unchanged from v0.2. Keyword fallback reads `scope_registry.json["agv_detection_keywords"]` (via `_AGV_DETECT_KWS` after migration). No UI change.

---

## 7. vehicle_types.json — Retirement Plan

| Field | Disposition | Replacement |
|---|---|---|
| `vt_map` | ✅ Retire — after `variant_map` startup assertion passes | `scope_registry.json["variant_map"]` |
| `keyword_map` | ✅ Retire — after `_load_agv_keywords()` migrated | `scope_registry.json["scopes"][id]["scope_keywords"]` |
| `llm_guide` | ✅ Retire | `scope_registry.json["scopes"][id]["classification_guide"]` |
| `agv_detection_keywords` | ✅ Retire — after keyword-superset assertion passes | `scope_registry.json["agv_detection_keywords"]` |
| `vna_applicable_types` | ✅ Retire — after `_VNA_APPLICABLE` wired | `scope_registry.json["scopes"][id]["vna_applicable"]` |
| `scoring_bucket_map` | ✅ Retire — after `_VALID_VTS` + `scoring_bucket` wired | `scope_registry.json["scopes"][id]["scoring_bucket"]` |
| `vt_prompt_map` | ✅ Retire — derived from scope tab_names + canonical_names | `{n["canonical_name"]: f"extraction_template_{n['tab_name'].lower()}.txt" for ...}` |
| `vna_subtypes` | ⚠ **Keep** (G1) — `_VNA_CFG` catches raw LLM outputs ("VNA", "Very Narrow Aisle") with `required_vna_capable=null`; can't be replaced by `vna_applicable` alone | `vehicle_types.json` (residual) |
| `text_overrides` | ⚠ Keep — regex not expressible in AP0 | `vehicle_types.json` (residual) |
| `4a_fields` | ⚠ Keep — needed for 4b AP0 validation exclusion | `vehicle_types.json` (residual) |
| `vna_context_hint` | ✅ Retire — moved to scope_registry.json Forklift node as `vna_hint` | `scope_registry.json["scopes"]["Logistics:AGV:Forklift"]["vna_hint"]` |

**Target state:** `vehicle_types.json` contains only `vna_subtypes`, `text_overrides`, `4a_fields`. File remains named `vehicle_types.json` (rename deferred — low value).

---

## 8. agv_type KO — No Change

`required_agv_type` remains a `KO_IF_NEQ` field. Retirement to OI-52 Phase 2.

---

## 9. Test Strategy

| ID | Test | Type |
|---|---|---|
| U_CL_01 | `scope_classification_template.txt` exists and contains all 3 canonical names | Static |
| U_CL_02 | `scope_registry.json` has `canonical_name` for all leaf scopes | Static |
| U_CL_03 | `scope_registry.json["agv_detection_keywords"]` is non-empty list | Static |
| U_CL_04 | `scope_registry.json["legacy_map"]` keys match `scopes[].canonical_name` values | Static |
| U_CL_05 | `scope_registry.json["variant_map"]` values ⊆ `legacy_map` keys | Static |
| U_CL_06 | `agv_type_keyword_fallback()` returns expected canonical type from AGV keyword text | Unit |
| U_CL_07 | composed `AGV_SYSTEM` contains CONSERVATIVE VALUE EXTRACTION phrase | Static |
| U_CL_08 | composed `AGV_SYSTEM` contains ANTI-HALLUCINATION phrase | Static |

---

## 10. Behavior-Neutrality Guarantee

**Pass 4a prompt:** Step 7 changes the *source* of the classification prompt (hand-maintained → AP0-generated) but not its *content*. Golden replay does NOT exercise Pass 4a (replay branch loads cached `vehicle_type`; never calls Pass 4a). Behavior-neutrality is verified by **static content comparison**:

1. After `generate_all.py` with new AP0 columns, diff `scope_classification_template.txt` against `vehicle_type_template.txt`
2. Assert ALL sub-variant guidance texts appear equivalently — specifically: VNA existing-infra disclaimer, MES/filling-lines/AMR payload disclaimer, Tugger/conveyor incompatibility
3. Generation assertion: byte-length within ±10% of current `vehicle_type_template.txt`

**`AGV_SYSTEM` (extraction rules):** after `build_system_context()` migration, the composed string must contain all rules 1–9. U_CL_07/08 verify rules 8–9. U_CL_06 verifies `agv_type_keyword_fallback()` behavior is unchanged.

**Matching engine:** all 5 golden tenders produce identical match results (replay branch — confirms no regression in matching path, which is independent of Pass 4a content).

---

## 11. Rollout Order

| Step | Action | Assertion |
|---|---|---|
| 11.1 | Verify rules 5–7 in `Spec/haystacked_industry_readme.md`; add if missing | Manual review |
| 11.2 | Update `config/prompts/extraction_system.txt`: replace abbreviated rule with complete rules 8–9 | pytest passes |
| 11.3 | Add 6 columns to ③ AP0 Scope Registry; fill all rows per §3 | Manual (xlsx) |
| 11.4 | Update `generate_all.py`: read new columns; emit to `scope_registry.json`; generate `scope_classification_template.txt`; add superset + length assertions | pytest passes; `scope_classification_template.txt` generated; static diff reviewed |
| 11.5 | Update `src/context_builder.py`: migrate `_load_agv_keywords()` to scope_registry.json; migrate `build_system_context()` to append `extraction_system.txt`; remove inline rules 8–9; remove `VEHICLE_TYPES` constant | pytest passes; U_CL_07/08 green |
| 11.6 | Update `app.py`: migrate all 8 variables per §5.2 table; rename `VEHICLE_TYPE_TEMPLATE` → `SCOPE_CLASSIFICATION_TEMPLATE`; add startup assertions | pytest passes; golden tenders identical |
| 11.7 | Update `src/matching.py`: rebuild guardian assertion per §5.3 | pytest passes |
| 11.8 | Remove retired fields from `vehicle_types.json`; remove dead `_vehicle_cfg` reads in app.py | pytest passes; no `vt_map`/`keyword_map`/`scoring_bucket_map`/`vt_prompt_map` references |
| 11.9 | Add U_CL_01–U_CL_08 tests | All 8 green |
| 11.10 | Golden refresh (should be no-op) | Identical to pre-Step-7 |

---

## 12. Open Questions (Deferred)

1. **`vehicle_types.json` rename** → `agv_classification_overrides.json`: deferred (low value).
2. **`4a_fields` as AP0 column**: deferred.
3. **Tiebreaker rules column** in ③ Scope Registry: deferred.
