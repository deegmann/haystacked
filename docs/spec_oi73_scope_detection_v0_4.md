# OI-73 Sub-Spec: Scope Detection Generalisation — v0.4

**Status:** DRAFT v0.4 — all review findings incorporated; ready for final approval  
**Pre-condition:** UFR Steps 1–6 complete ✅ (231 tests green, 2026-07-13)

---

## Changelog

| Version | Source | Findings | Key fixes |
|---|---|---|---|
| v0.1 | Initial draft | — | — |
| v0.2 | SA round 1 (CONDITIONAL PASS) | vt_map≠legacy_map; golden replay invalid for Pass 4a; matching.py guardian gutted; vna_applicable/scoring_bucket unwired; second prose file | variant_map added; static diff verification; guardian rebuilt; vna/scoring columns added |
| v0.3 | Tech Lead code inventory | _VNA_CFG retirement broken; vt_prompt_map dropped; guardian vacuously true; 3 consumers missing from §5.2; vna_context_hint unwired; _load_agv_keywords() unaddressed | vna_subtypes kept; vt_prompt_map re-added; guardian fixed; mapping table completed |
| v0.4 | SA round 2 Fable (FAIL) | Keywords column conflates 3 consumers with incompatible semantics (variant_map / keyword_fallback / is_agv_amr); extraction_system.txt is generated (line 1615) so rollout step 11.2 manual edit gets reverted; field_text_fallbacks and 4a_skip missing from §5.2; llm_guide in build_extraction_template() at line 938 unaddressed; variant_map superset assertion missing | Split into Variants + Keywords columns; rules 8-9 update moved into generate_all.py:1615; §5.2 completed; build_extraction_template() added to §5.1; superset assertion added |

---

## 1. Problem Statement

After Steps 1–6, the AP0 ③ Scope Registry is the authoritative source for which scopes exist and how they nest. But the *classification logic* — how to detect which scope a tender belongs to — is still hardcoded in three places:

| Location | Hardcoded Content | Should Come From |
|---|---|---|
| `config/prompts/vehicle_type_template.txt` | LLM classification guide + tiebreaker rules | ③ Scope Registry "Classification Guide" column → generated `scope_classification_template.txt` |
| `config/vehicle_types.json` | `vt_map`, `keyword_map`, `vna_applicable_types`, `scoring_bucket_map`, `vt_prompt_map`, `llm_guide`, `agv_detection_keywords` | `scope_registry.json` (generated from AP0 ③) |
| `src/context_builder.py` | Rules 5–9 hardcoded in `build_system_context()` | Rules 5–7 → `Spec/haystacked_industry_readme.md`; rules 8–9 → `generate_all.py:1615` (which generates `extraction_system.txt`) |

Additionally:
- SA-10: `legacy_map` built by fragile last-segment heuristic → replace with explicit "Canonical Name" column in ③ Scope Registry
- `generate_all.py:938`: `build_extraction_template()` also reads `llm_guide` to inject classification guide into the combined fallback extraction template

---

## 2. Scope

### In Scope (Step 7)
- Add **Canonical Name**, **Classification Guide**, **Variants**, **Keywords**, **VNA Applicable**, **Scoring Bucket**, **VNA Hint** columns to ③ Scope Registry AP0 tab (7 new columns)
- `generate_all.py`: read new columns; emit to `scope_registry.json`; generate `scope_classification_template.txt`; update `build_extraction_template()` to read classification_guide from scope nodes; update `extraction_system.txt` generation string (rules 8-9 complete form)
- `app.py`: migrate 8 variables from `vehicle_types.json` → `scope_registry.json`; 2 variables confirmed no-change (already AP0-driven)
- `src/matching.py`: rebuild guardian assertion (non-vacuous)
- `src/context_builder.py`: `_load_agv_keywords()` → reads `scope_registry.json`; `build_system_context()` appends `extraction_system.txt`; remove inline rules 5–9
- `vehicle_types.json`: retire 7 fields; keep 4 residual fields

### Out of Scope (defer)
- Scope-based data_loader filtering (agv_type KO_IF_NEQ stays; OI-52 Phase 2)
- New industry verticals; partial-classification UI; `_FALLBACK_README` migration; OI-52 Phase 2

---

## 3. AP0 Changes — ③ Scope Registry Tab

Add **seven** columns:

| Column | Type | Purpose |
|---|---|---|
| `canonical_name` | Text | Human-readable canonical name (e.g. "Forklift AGV") — replaces legacy_map heuristic (SA-10) |
| `classification_guide` | Text | Full LLM guide text for this leaf scope — used in scope_classification_template.txt AND in the combined fallback extraction_template.txt |
| `variants` | Text (comma-separated) | Exact strings the LLM may output as `required_agv_type` — drives `variant_map` ONLY |
| `keywords` | Text (comma-separated) | Broader detection keywords — drives `agv_detection_keywords` and `agv_type_keyword_fallback()` ONLY. Must NOT include generic words ("pallet", "lift", "racking", "fork") — only terms that reliably signal this specific vehicle category |
| `vna_applicable` | Boolean | True only on Forklift AGV leaf — drives `_VNA_APPLICABLE` |
| `scoring_bucket` | Text | Scoring bucket id — drives `scoring_bucket_map` |
| `vna_hint` | Text | VNA context string for 4b prompt — replaces `vna_context_hint` hardcode in generate_all.py:1583 |

**Why two separate columns (Variants vs Keywords):**
- `variant_map` is an LLM output normaliser — keys are strings the LLM might actually output for `required_agv_type` (e.g. "counterbalanced", "very narrow aisle", "mobile amr")
- `agv_detection_keywords` and `agv_type_keyword_fallback()` are text-presence detectors — terms searched in raw document text. Conflating the two would pollute `agv_detection_keywords` with generic words ("lift", "pallet") that trigger false is_agv_amr positives

### Row values

**`*` (Global root):** all new columns empty.

**`Logistics:AGV` (parent node, not a leaf):**
- `canonical_name`: *(empty)*
- `classification_guide`: *(empty)*
- `variants`: *(empty — parent; agv handled via Forklift default)*
- `keywords`: *(empty — agv_detection_keywords = union of leaf keywords only)*
- `vna_applicable`: *(empty)*  `scoring_bucket`: *(empty)*  `vna_hint`: *(empty)*

**`Logistics:AGV:Forklift`:**
- `canonical_name`: `Forklift AGV`
- `classification_guide`: *(must reproduce the FULL text for VNA, Reach Truck, Counterbalanced, Forklift entries from current `vehicle_type_template.txt` — see §10 verification)*
- `variants`: `vna, very narrow aisle, reach truck, counterbalanced, forklift, forklift agv, agv`
- `keywords`: `vna, very narrow aisle, reach truck, schmalgangstapler, counterbalanced, forklift, stapler, gabelstapler, forklift agv, agv`
- `vna_applicable`: true  `scoring_bucket`: `forklift_specific`  `vna_hint`: `VNA (very narrow aisle) operation is required.`

**`Logistics:AGV:Tugger`:**
- `canonical_name`: `Tugger AGV`
- `classification_guide`: *(full Tugger entry from current template)*
- `variants`: `tugger, tugger agv`
- `keywords`: `tugger, schlepper, routenzug, milk run, towing, anhaenger, tugger agv`
- `vna_applicable`: *(empty)*  `scoring_bucket`: `tugger_specific`  `vna_hint`: *(empty)*

**`Logistics:AGV:AMR`:**
- `canonical_name`: `Mobile AMR`
- `classification_guide`: *(full Mobile AMR + Underride AMR entries from current template)*
- `variants`: `amr, mobile amr, underride, underride amr, autonomous mobile robot`
- `keywords`: `amr, mobile robot, fahrroboter, autonomer, goods-to-person, goods to person, underride amr, unterfahrfahrzeug, underride, autonomous mobile robot`
- `vna_applicable`: *(empty)*  `scoring_bucket`: `amr_specific`  `vna_hint`: *(empty)*

**Critical: German terms** in `keywords` must include ALL currently in `vehicle_types.json["keyword_map"]`: `schmalgangstapler`, `gabelstapler`, `schlepper`, `routenzug`, `fahrroboter`, `unterfahrfahrzeug`, `anhaenger`, `autonomer`. Verified at generation time by keyword-superset assertion (§5.1).

**Critical: `variants` superset** must cover all 14 entries in current `vehicle_types.json["vt_map"]` — verified at generation time by variant-superset assertion (§5.1).

---

## 4. Generated Artifacts

### 4.1 `scope_registry.json` — new top-level and per-node fields

```json
{
  "scopes": {
    "Logistics:AGV:Forklift": {
      "scope_id": "Logistics:AGV:Forklift",
      "parent": "Logistics:AGV",
      "tab_name": "AGV_Forklift",
      "canonical_name": "Forklift AGV",
      "classification_guide": "AGV that lifts/lowers loads using forks...",
      "scope_variants": ["vna", "very narrow aisle", "reach truck", ...],
      "scope_keywords": ["vna", "very narrow aisle", "schmalgangstapler", ...],
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
    "agv": "Forklift AGV",
    "tugger": "Tugger AGV",
    "tugger agv": "Tugger AGV",
    "amr": "Mobile AMR",
    "mobile amr": "Mobile AMR",
    "underride": "Mobile AMR",
    "underride amr": "Mobile AMR",
    "autonomous mobile robot": "Mobile AMR"
  },
  "legacy_map": { "Forklift AGV": "Logistics:AGV:Forklift", ... },
  "agv_detection_keywords": ["vna", "very narrow aisle", "schmalgangstapler", ...]
}
```

**`variant_map`** — built from leaf nodes' `scope_variants` column × `canonical_name`. DISTINCT from `legacy_map`. Superset assertion at generation time vs. pre-Step-7 `vt_map` keys.

**`agv_detection_keywords`** — union of `scope_keywords` across all non-root nodes. Superset assertion vs. pre-Step-7 `agv_detection_keywords`.

**`legacy_map`** — built from `canonical_name` (explicit column), not heuristic. Startup assertion: all nodes with `canonical_name` appear in `legacy_map`.

### 4.2 `config/prompts/scope_classification_template.txt` — **generated**

Generated from ③ Scope Registry leaf nodes' `classification_guide` values. Added to "always generated" list in CLAUDE.md; never manually edited.

Template structure:
```
Classify the required AGV/AMR vehicle type from this tender document.
Output ONLY the JSON object shown below — nothing else.

Vehicle type classification guide:
{for each leaf scope in declaration order:}
  * "{canonical_name}" → {classification_guide}

  Key: PAYLOAD AND LOAD TYPE determine the vehicle — not the environment alone.

  THINK STEP BY STEP:
  [fixed snippet — hardcoded in generate_all.py; same text as current vehicle_type_template.txt tiebreaker block]

Fields:
- required_agv_type: MANDATORY — exactly one of: 'Forklift AGV', 'Tugger AGV', 'Mobile AMR'.
- required_vna_capable: true ONLY if VNA is explicitly required for the AGVs being procured.

DOCUMENT:
{text}

JSON:
{"required_agv_type":null,"required_vna_capable":null}
```

**Assertions at generation time:**
- File non-empty; contains all 3 canonical names; byte-length within ±10% of current `vehicle_type_template.txt`

### 4.3 `config/prompts/extraction_system.txt` — **generated (update to hardcoded string)**

Currently generated at `generate_all.py:1615-1622` with abbreviated anti-hallucination rule only. After Step 7, the generation string is updated to contain the complete rules 8-9:

```
You are a warehouse automation specialist. Extract technical AGV/AMR requirements from tender documents. Output ONLY valid JSON. No markdown, no explanation.

## Critical extraction rules
8. CONSERVATIVE VALUE EXTRACTION (critical): When a document lists multiple values for the same parameter, always extract the most demanding value. For minimum-capability fields (payload, lift height, operating hours, fleet size, maximum ambient temperature): extract the MAXIMUM value found. For maximum-constraint fields (aisle width, minimum ambient temperature): extract the MINIMUM value found. Never average or omit ambiguous values — always pick the worst case for the supplier.
9. ANTI-HALLUCINATION (critical): Before outputting any non-null value you must be able to identify the exact sentence in the document that states it. Do NOT infer specifications from warehouse type or AGV type — a VNA warehouse does NOT imply IP65, cold-storage temperature, high humidity, ramp gradient, or VDA 5050 unless these are written in the document. Do NOT read numbers from dates, filenames, revision codes, version strings, or project metadata as specification values — '25th May 2022' is a date, NOT a temperature; 'v1.3' is a version, NOT a floor flatness value. If a field's value is not directly stated in the document text, output null — never apply typical industry values.
```

This change happens in **generate_all.py** (step 11.3), NOT as a manual file edit. The file is generated; it is not manually maintained.

---

## 5. Code Changes

### 5.1 `generate_all.py`

**New / changed functions:**
- `read_scope_registry(wb)`: read 7 new columns from ③ Scope Registry
- `_write_scope_registry(...)`: write new per-node fields; derive `variant_map` (from `scope_variants` × `canonical_name`), `agv_detection_keywords` (union of `scope_keywords`), `legacy_map` (from `canonical_name`); assert `variant_map` ⊇ pre-Step-7 `vt_map` keys; assert `agv_detection_keywords` ⊇ pre-Step-7 baseline
- `build_scope_classification_template(scope_nodes)`: new function replacing `build_vehicle_type_template(vehicle_types)` — reads `classification_guide` + `canonical_name` from scope nodes; emits fixed THINK STEP BY STEP snippet; writes `scope_classification_template.txt`
- `build_extraction_template(...)` at **line 938**: update to read `classification_guide` from scope nodes passed as parameter (replacing `vehicle_types.get("llm_guide", [])`). The combined fallback template (`extraction_template.txt`) includes the classification guide — its source must move from `llm_guide` (Vehicle Types tab) to `classification_guide` (③ Scope Registry tab)
- `generate_all.py:1615-1622`: update the hardcoded `extraction_system.txt` string to complete rules 8-9 (see §4.3)
- `generate_all.py:1583`: `vehicle_types["vna_context_hint"] = "..."` hardcode is REMOVED; replaced by `scope_registry` Forklift node `vna_hint` value
- Add `scope_classification_template.txt` to generated file list in CLAUDE.md

**Three assertions added to `_write_scope_registry`:**

Parent-conformance assertion (new, from post-approval review):
```python
# Assert hierarchy integrity: every non-root parent is a declared scope_id; exactly one root
_declared = set(scopes.keys())
_roots = [sid for sid, node in scopes.items() if node.get("parent") is None]
assert len(_roots) == 1, f"Expected exactly one root scope, got: {_roots}"
for sid, node in scopes.items():
    p = node.get("parent")
    if p is not None:
        assert p in _declared, f"scope {sid!r} declares parent {p!r} which is not a declared scope_id"
        # parent must equal nearest declared strict path-prefix (or "*")
        prefix = sid.rsplit(":", 1)[0] if ":" in sid else None
        expected_parent = prefix if prefix in _declared else "*"
        assert p == expected_parent, \
            f"scope {sid!r}: declared parent {p!r} != derived parent {expected_parent!r}"
```

Superset assertions:
```python
_PRE_STEP7_VT_MAP_KEYS = frozenset([
    "vna", "very narrow aisle", "reach truck", "counterbalanced", "forklift",
    "forklift agv", "agv", "tugger", "tugger agv", "mobile amr", "amr",
    "underride amr", "underride", "autonomous mobile robot"
])
assert _PRE_STEP7_VT_MAP_KEYS <= set(variant_map.keys()), \
    f"variant_map missing pre-Step-7 vt_map entries: {_PRE_STEP7_VT_MAP_KEYS - set(variant_map.keys())}"

_PRE_STEP7_DETECT_KWS = frozenset([
    "vna", "very narrow aisle", "reach truck", "schmalgangstapler", "counterbalanced",
    "forklift", "stapler", "gabelstapler", "forklift agv", "agv", "tugger", "schlepper",
    "routenzug", "milk run", "towing", "anhaenger", "tugger agv", "amr", "mobile robot",
    "fahrroboter", "autonomer", "goods-to-person", "goods to person", "underride amr",
    "unterfahrfahrzeug", "underride", "autonomous mobile robot"
])
assert _PRE_STEP7_DETECT_KWS <= set(agv_detection_keywords), \
    f"agv_detection_keywords missing pre-Step-7 entries: {_PRE_STEP7_DETECT_KWS - set(agv_detection_keywords)}"
```

### 5.2 `app.py` — complete variable inventory

**Migrating from `vehicle_types.json` → `scope_registry.json`:**

| Variable | Line(s) | Old source | New source | Action |
|---|---|---|---|---|
| `_VT_MAP_CFG` | 248, 466, 693, 697, 927, 931 | `vehicle_types.json["vt_map"]` | `scope_registry.json["variant_map"]` | Migrate |
| `_VNA_CFG` | 249, 700 | `vehicle_types.json["vna_subtypes"]` | *(unchanged — kept in residual)* | No change |
| `_VNA_APPLICABLE` | 251, 962 | `vehicle_types.json["vna_applicable_types"]` | `{n["canonical_name"] for n in scopes.values() if n.get("vna_applicable")}` | Migrate |
| `_AGV_DETECT_KWS` | 252, 557 | `vehicle_types.json["agv_detection_keywords"]` | `scope_registry.json["agv_detection_keywords"]` | Migrate |
| `_FIELD_TEXT_FALLBACKS` | 254, 908 | `vehicle_types.json["field_text_fallbacks"]` | *(already AP0-driven via generate_all.py:1471; no change)* | No change |
| `_VALID_VTS` | 268, 1066, 1070 | `vehicle_types.json["scoring_bucket_map"].keys()` | `{n["canonical_name"] for n in scopes.values() if n.get("scoring_bucket")}` | Migrate |
| `_AGV_TYPE_TEMPLATES` | 304–307 | `vehicle_types.json["vt_prompt_map"]` | `{n["canonical_name"]: _load_prompt(f"extraction_template_{n['tab_name'].lower().replace(' ', '_')}.txt") for n in scopes.values() if n.get("canonical_name")}` | Migrate |
| `_4A_SKIP` | 310 | `vehicle_types.json["4a_fields"]` | *(already generated from `_4A_FIELDS` constant in generate_all.py:1582; no change)* | No change |
| `vna_context` | 740 | `vehicle_types.json["vna_context_hint"]` | `_VNA_CONTEXT_HINT = next((n.get("vna_hint","") for n in scopes.values() if n.get("vna_applicable")), "")` — evaluated once at startup | Migrate |
| `scoring_bucket_map` | 1109–1110, 1158 | `vehicle_types.json["scoring_bucket_map"]` | `{n["canonical_name"]: n["scoring_bucket"] for n in scopes.values() if n.get("scoring_bucket")}` (from `_scope_reg`, not re-loaded `vt_cfg`) | Migrate |

**Prompt:**
- `VEHICLE_TYPE_TEMPLATE` → renamed `SCOPE_CLASSIFICATION_TEMPLATE`, loaded from `scope_classification_template.txt`

**New startup assertion:** all values in `_VT_MAP_CFG.values()` appear as keys in `_LEGACY_MAP`.

### 5.3 `src/matching.py`

Guardian at lines 69–73 rebuilt (non-vacuous):

```python
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

`_canon_names` is derived from `scopes[].canonical_name` (AP0 column), NOT from `legacy_map.keys()`.

### 5.4 `src/context_builder.py`

**A. `_load_agv_keywords()` — migrate data source**

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

`AGV_KEYWORDS` dict structure unchanged — `agv_type_keyword_fallback()` works without modification. `VEHICLE_TYPES` constant removed.

**B. Rules migration**

Rules 5–7: verify present in `Spec/haystacked_industry_readme.md` before code changes (step 11.1). Industry README is already loaded by `build_system_context()` → present at runtime.

Rules 8–9: `build_system_context()` appends `_load_prompt("extraction_system.txt")` (which generate_all.py now generates with complete rules 8-9). Remove inline rules 8–9 from `build_system_context()`.

Rules 5–7 inline in `build_system_context()` removed after verifying they are in industry_readme.md.

`_FALLBACK_README` unchanged.

---

## 6. Partial-Classification Handling

Unchanged. `_AGV_DETECT_KWS` reads from `scope_registry.json["agv_detection_keywords"]` after migration.

---

## 7. vehicle_types.json — Retirement Plan

| Field | Disposition | Replacement / Note |
|---|---|---|
| `vt_map` | ✅ Retire — after `variant_map` superset assertion passes | `scope_registry.json["variant_map"]` |
| `keyword_map` | ✅ Retire — after `_load_agv_keywords()` migrated | `scope_registry.json["scopes"][id]["scope_keywords"]` |
| `llm_guide` | ✅ Retire — after `build_extraction_template()` migrated to scope nodes | `scope_registry.json["scopes"][id]["classification_guide"]` |
| `agv_detection_keywords` | ✅ Retire — after superset assertion passes | `scope_registry.json["agv_detection_keywords"]` |
| `vna_applicable_types` | ✅ Retire — after `_VNA_APPLICABLE` wired | `scope_registry.json["scopes"][id]["vna_applicable"]` |
| `scoring_bucket_map` | ✅ Retire — after `_VALID_VTS` + `scoring_bucket` wired | `scope_registry.json["scopes"][id]["scoring_bucket"]` |
| `vt_prompt_map` | ✅ Retire — after `_AGV_TYPE_TEMPLATES` wired | Derived from `canonical_name` + `tab_name` in scope_registry.json |
| `vna_context_hint` | ✅ Retire — moved to scope_registry.json Forklift `vna_hint`; hardcode at generate_all.py:1583 removed | `scope_registry.json["scopes"]["Logistics:AGV:Forklift"]["vna_hint"]` |
| `field_text_fallbacks` | ⚠ Keep — already AP0-driven (generate_all.py:1471 reads from AP0 `Vehicle Types` sheet) | No change |
| `vna_subtypes` | ⚠ Keep — `_VNA_CFG` catches raw LLM outputs ("VNA", "Very Narrow Aisle") when `required_vna_capable=null`; not replaceable by `vna_applicable` alone | No change |
| `text_overrides` | ⚠ Keep — regex not expressible in AP0 | No change |
| `4a_fields` | ⚠ Keep — generated from `_4A_FIELDS` constant in generate_all.py:1582 | No change |

**Target state:** `vehicle_types.json` contains `field_text_fallbacks`, `vna_subtypes`, `text_overrides`, `4a_fields` (plus any derived fields generate_all.py still writes).

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
| U_CL_04 | `scope_registry.json["legacy_map"]` keys match `scopes[].canonical_name` values (not heuristic) | Static |
| U_CL_05 | `scope_registry.json["variant_map"]` values ⊆ `legacy_map` keys | Static |
| U_CL_06 | `agv_type_keyword_fallback()` returns expected canonical type from AGV keyword text | Unit |
| U_CL_07 | composed `AGV_SYSTEM` contains CONSERVATIVE VALUE EXTRACTION phrase | Static |
| U_CL_08 | composed `AGV_SYSTEM` contains ANTI-HALLUCINATION phrase | Static |

---

## 10. Behavior-Neutrality Guarantee

**Pass 4a prompt:** Verified by static content comparison — golden replay does NOT exercise Pass 4a (replay branch loads cached `vehicle_type`; see `app.py:446-470`). Diff `scope_classification_template.txt` against `vehicle_type_template.txt` after generation; assert ALL sub-variant guidance texts present; byte-length assertion (±10%) at generation time.

**`extraction_template.txt`** (combined fallback): `build_extraction_template()` now reads `classification_guide` from scope nodes instead of `llm_guide` from vehicle_types. Same content — static diff required after generation.

**`AGV_SYSTEM`:** after `build_system_context()` migration, U_CL_07/08 verify complete rules 8–9 present. Rules 5–7 verified in industry_readme.md (step 11.1).

**Matching engine:** all 5 golden tenders produce identical match results.

---

## 11. Rollout Order

| Step | Action | Assertion |
|---|---|---|
| 11.1 | Verify rules 5–7 present in `Spec/haystacked_industry_readme.md`; add if missing | Manual review |
| 11.2 | Add 7 columns to ③ AP0 Scope Registry; fill Variants and Keywords columns per §3 (NOT generic words) | Manual (xlsx) |
| 11.3 | Update `generate_all.py`: read 7 new columns; emit to `scope_registry.json`; generate `scope_classification_template.txt`; update `build_extraction_template()` at line 938; update `extraction_system.txt` generation string (lines 1615-1622) to complete rules 8-9; remove `vna_context_hint` hardcode at line 1583; add both superset assertions | pytest passes; `scope_classification_template.txt` generated; static diff of both generated templates reviewed; superset assertions pass |
| 11.4 | Update `src/context_builder.py`: `_load_agv_keywords()` → scope_registry.json; `build_system_context()` appends `extraction_system.txt`; remove inline rules 5–9 | pytest passes; U_CL_07/08 green |
| 11.5 | Update `app.py`: migrate 8 variables per §5.2 table; rename `VEHICLE_TYPE_TEMPLATE` → `SCOPE_CLASSIFICATION_TEMPLATE`; add startup assertion | pytest passes; golden tenders identical |
| 11.6 | Update `src/matching.py`: rebuild guardian per §5.3 | pytest passes |
| 11.7 | Remove retired fields from `vehicle_types.json`; remove dead `_vehicle_cfg` reads in app.py | pytest passes; no `vt_map`/`keyword_map`/`scoring_bucket_map`/`vt_prompt_map` references |
| 11.8 | Add U_CL_01–U_CL_08 tests | All 8 green |
| 11.9 | Golden refresh (should be no-op; verify both classification template and extraction template static diffs) | Identical to pre-Step-7 |

---

## 12. Open Questions (Deferred)

1. **`llm_guide` in Vehicle Types AP0 tab**: After migrating to `classification_guide` in ③ Scope Registry, the Vehicle Types tab `llm_guide` column becomes a duplicate. Can be removed in a future AP0 cleanup session.
2. **`vehicle_types.json` rename** → `agv_classification_overrides.json`: deferred.
3. **`4a_fields` as AP0 column**: deferred.
4. **Tiebreaker rules column** in ③ Scope Registry: deferred.
