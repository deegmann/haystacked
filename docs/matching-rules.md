# Haystacked Matching Rules

**Version:** based on AP0 v0.10  
**Last updated:** 2026-06-01

This document explains how the haystacked matching engine decides which suppliers qualify for a tender and how they are ranked. It is written for the project team — no programming knowledge required, but some familiarity with the AGV/AMR domain helps.

---

## The three levels: K.O., Cond. K.O., Scoring

Every field in the AP0 specification is assigned one of four levels. Two of them directly affect whether a supplier is shown as qualified.

### K.O. — Hard knockout

A supplier failing a K.O. criterion is **completely excluded** from the results. There is no score, no ranking, no second chance.

K.O. criteria represent requirements that are physically non-negotiable: if the tender requires a 2,000 kg payload capacity and the supplier's machine handles 1,500 kg, the machine simply cannot do the job.

Current K.O. fields (as of AP0 v0.10):
- `max_payload_kg` — maximum load per trip
- `load_type` — pallet type supported (EUR, ISO, Tote, etc.)
- `agv_type` — Forklift AGV vs. Tugger AGV vs. Mobile AMR
- `fleet_management_system` — fleet controller architecture
- `lifting_height_mm` — maximum fork lift height (Forklift AGV only)
- `min_aisle_width_mm` — minimum working aisle width (Forklift AGV only)
- `towing_capacity_kg` — total towed load (Tugger AGV only)
- `vna_capable` — VNA capable (via KO_BOOL_EXCLUSIVE, see below)

### Cond. K.O. — Conditional knockout

A Cond. K.O. criterion only becomes a hard filter when the tender **explicitly requires** it. Otherwise it scores positively (the supplier gets points for having the capability) but does not exclude.

This handles requirements that many buyers do not care about (e.g. outdoor capability, VDA 5050 compliance) but some buyers treat as absolute. The buyer signals "I need this" through the tender document, and the LLM picks it up and sets the requirement field. The matching engine then activates the hard filter.

**Example:** Outdoor capability. Most warehouse deployments are indoor-only. If a tender says nothing about outdoor use, `required_outdoor` will be `None` and outdoor capability does not filter. If the tender explicitly states outdoor operation is required, `required_outdoor="required"` and any supplier without `outdoor_capable=True` is excluded.

### Scoring — Points only

Scoring fields do not filter. They award points to help rank qualified suppliers. Examples:
- battery runtime (longer = more points)
- reference count (more installations = more points)
- autonomous charging capability
- VDA 5050 compatibility
- stop accuracy

### Context — Display only

Context fields (e.g. vehicle dimensions) are stored in the database and displayed in the results, but they never affect filtering or scoring.

---

## The six matching operators

Each K.O. or Cond. K.O. field has one operator assigned in the AP0 xlsx. The operator defines the comparison logic.

### KO_IF_LT — Knock out if supplier value is too low

Used for capabilities where higher is better and there is a minimum threshold.

**Fires when:** supplier value < tender requirement  
**Does not fire when:** either value is `None` (see null rule below)

**Examples:**
- `max_payload_kg`: supplier offers 1,500 kg, tender requires 2,000 kg → K.O.
- `lifting_height_mm`: supplier lifts to 8,000 mm, tender requires 12,000 mm → K.O.
- `towing_capacity_kg`: supplier tows 3,000 kg, tender requires 5,000 kg → K.O.

### KO_IF_GT — Knock out if supplier value is too high (machine is too large)

Used for physical constraints where the machine must fit within a limit.

**Fires when:** supplier value > tender requirement  
**Does not fire when:** either value is `None`

**Examples:**
- `min_aisle_width_mm`: the supplier's machine needs 2,200 mm aisle width, but the warehouse only has 1,800 mm available → K.O.
- `operating_temp_min_c`: the supplier's machine requires minimum ambient temperature of 5 °C, but the cold store runs at -20 °C → K.O.

### KO_IF_NEQ — Knock out if values do not match exactly

Used for categorical fields where only one specific value is acceptable.

**Fires when:** supplier value ≠ tender value (case-insensitive)  
**Does not fire when:** either value is `None`

**Example:**
- `agv_type`: tender requires `"Forklift AGV"`, supplier is a `"Tugger AGV"` → K.O. (a tugger cannot replace a forklift)

### KO_BOOL_REQUIRED — Knock out only if supplier explicitly says "no"

A one-directional boolean filter. Used when the tender requires a capability and an explicit `False` from the supplier is a deal-breaker, but `None` (unknown) is acceptable.

**Fires when:** tender = `"required"` AND supplier = `False`  
**Does not fire when:** supplier is `None` (unknown — benefit of the doubt)

**Example:**
- `outdoor_capable`: tender requires outdoor operation, supplier has `outdoor_capable=False` explicitly → K.O. A supplier with `outdoor_capable=None` (not yet filled in) is not excluded.

### KO_BOOL_EXCLUSIVE — Bidirectional boolean gate

The strictest boolean operator. Used for VNA (Very Narrow Aisle), where the machine type must match in both directions. A VNA turret truck cannot operate in a normal warehouse (it needs guide rails or very narrow aisles), and a standard forklift cannot operate in a VNA aisle.

**Fires when (required direction):** tender = `"required"` AND supplier is not `True` → K.O.  
**Fires when (not_required direction):** tender = `"not_required"` AND supplier = `True` → K.O.  
**Does not fire when:** tender is `None` or `"preferred"`

This operator is only used for `vna_capable`.

### KO_SUBSET — Knock out if no overlap between two lists

Used for Multi-Select fields. The tender specifies a list of required values; the supplier has a list of supported values. If there is no overlap at all, it is a K.O.

Uses substring matching for flexibility: `"SLAM"` will match `"Natural Feature (SLAM)"`.

**Fires when:** no item in the tender list is contained in (or contains) any item in the supplier list  
**Does not fire when:** either list is empty

**Examples:**
- `load_type`: tender requires `["Pallet EUR", "Pallet ISO"]`, supplier only handles `["Tote"]` → K.O. (no overlap)
- `navigation_type` (Cond. K.O.): tender requires `["Natural Feature (SLAM)"]`, supplier supports `["Laser Reflector", "Magnetic Tape"]` → K.O. if navigation is required, scoring penalty if not
- `fleet_management_system`: tender requires `["VDA 5050 compatible"]`, supplier only offers `["Proprietary"]` → K.O.

---

## The null rule — when does "not filled in" matter?

**Core rule (LL-06): `None` on either side never triggers a hard K.O. for numeric and categorical operators.**

This is the single most important rule for understanding matching results. It exists because the supplier database is not complete — many fields have not been filled in yet. The system must not exclude a supplier just because a field has not been entered.

- Tender requires 2,000 kg payload, supplier has `max_payload_kg=None` → **no K.O.**
- Tender requires 12,000 mm lift height, supplier has `lifting_height_mm=None` → **no K.O.**
- Tender requires outdoor capability, supplier has `outdoor_capable=None` → **no K.O.** (KO_BOOL_REQUIRED does not fire on `None`)

The only exception: `KO_BOOL_EXCLUSIVE` (`vna_capable`) treats `None` the same as `False` when the tender requires VNA. If the tender explicitly needs VNA and the supplier's VNA capability is unknown, the supplier is excluded. This is an intentional asymmetry — VNA is too specialised to allow unknowns into the qualified pool.

### The null penalty (-15 points)

For numeric K.O. fields (those using `KO_IF_LT` or `KO_IF_GT`), when the tender has a value but the supplier has `None`, the supplier avoids disqualification but receives a **-15 point penalty per missing field**.

This ranks fully-documented suppliers above undocumented ones without excluding the undocumented ones entirely. A supplier with null payload data will score lower than a comparable supplier with confirmed payload data.

---

## How drive_type matching works

`drive_type` is a **Cond. K.O.** field (as of AP0 v0.10, after the 2026-06-01 fix).

**Key design decision:** the extraction prompt explicitly instructs the LLM: "ONLY extract if tender explicitly names drive type — do NOT infer from task description." Floor-level pallet transport does not imply Counterbalanced; only extract if the buyer specifies it.

**Why this matters:** A Reach Truck AGV can transport floor pallets just as well as a Counterbalanced AGV. If the tender says "transport pallets from receiving to storage" without specifying the machine type, the LLM must return `null` for `required_drive_type` — not `"Counterbalanced"`. Extracting `"Counterbalanced"` and applying a K.O. would wrongly exclude Reach Truck suppliers who are equally capable.

**When drive_type does filter:** if a tender document explicitly states the drive type (e.g. "Gegengewichtsstapler", "counterbalanced forklift", "Schubmaststapler"), the Cond. K.O. fires.

**VNA special case:** when VNA is detected (via LLM output or text override), `app.py` sets `required_drive_type = "VNA Turret"` regardless of what the LLM extracted. This value comes from `config/vehicle_types.json → vna_drive_type`, which is resolved by `generate_all.py` from the AP0 allowed values — no hardcoded string in Python.

---

## How VNA matching works

VNA (Very Narrow Aisle) uses `KO_BOOL_EXCLUSIVE`, which is bidirectional — it protects against mismatches in both directions.

### A VNA tender (required_vna = "required")

- Suppliers with `vna_capable=True` → pass (proceed to scoring)
- Suppliers with `vna_capable=False` → K.O. (standard forklift cannot operate in narrow aisles)
- Suppliers with `vna_capable=None` → K.O. (by exception to the null rule — see above)

### A standard-aisle tender (required_vna = "not_required")

- Suppliers with `vna_capable=True` → K.O. (VNA turret trucks need guide rail infrastructure not present in a standard warehouse)
- Suppliers with `vna_capable=False` or `None` → pass

### How VNA is detected

VNA detection happens in two layers before matching:

1. **LLM output:** if the LLM returns `required_vehicle_type = "VNA"` or `"Very Narrow Aisle"`, the vna_subtypes list in `vehicle_types.json` flags it as a VNA subtype.
2. **Text override (Layer 2):** the document text is scanned for regex patterns from `vehicle_types.json → text_overrides`. Currently:
   - `\bVNA\b` — the abbreviation anywhere in the document
   - `(?i)schmalgangstapler` — the German term (case-insensitive)

   If either pattern matches, `is_vna_subtype=True` and `required_vna="required"` is forced, regardless of what the LLM returned for the vehicle type field.

Text overrides exist because LLM vehicle type classification can be unreliable when the tender uses domain-specific terminology. The regex fallback is deterministic and does not depend on the LLM.

---

## Scoring rules

Once a supplier has passed all K.O. and Cond. K.O. filters, scoring determines their rank. All weights and rules come from `config/scoring_weights.json`, which is generated from the AP0 xlsx.

Scoring is separated into buckets by AGV type: `default` (applies to all), `forklift_specific`, `tugger_specific`, `amr_specific`. Each bucket can have different weights for the same field, or fields that only apply to that type.

**Scoring rules in use:**

| Rule name | What it does |
|---|---|
| `bool` | Full points if supplier has `True` |
| `bool_cond` | Full points if supplier has `True` AND tender requires this field; slightly reduced otherwise |
| `nonempty` | Full points if field is not empty (e.g. safety_standard has at least one entry) |
| `proportional` | Points scale with value up to a ceiling (e.g. reference_count: max 15 pts, 20 references = ceiling) |
| `threshold_upper` | Full points above threshold, half points below (e.g. battery runtime ≥ 8h = full) |
| `threshold_lower` | Full points below threshold (e.g. stop accuracy ≤ 10 mm = full) |
| `tiered_lower` | Tiered: full points ≤ t1, half points ≤ t2, zero otherwise |
| `tiered_upper` | Tiered: full points ≥ t1, half points ≥ t2, zero otherwise |

**Key scoring fields (default bucket, applies to all AGV types):**

| Field | Points | Rule |
|---|---|---|
| reference_count | 15 | proportional (ceiling: 20 references) |
| lead_time_weeks | 10 | tiered_lower (full ≤ 26 weeks, half ≤ 52 weeks) |
| vda5050_compatible | 8 | bool_cond |
| battery_runtime_h | 7 | threshold_upper (≥ 8h = full) |
| autonomous_charging | 6 | bool |
| stop_accuracy_mm | 5 | tiered_lower |
| safety_standard | 5 | nonempty |

---

## Match result structure

Each result entry contains:
- `product` — product name
- `company` — company name
- `score` — total points scored
- `max_score` — maximum possible points
- `rank` — position (qualified suppliers ranked 1, 2, 3... then disqualified follow)
- `disqualified` — true/false
- `disqualified_by` — list of K.O. reasons (e.g. `["max_payload_kg: 1500.0 < required 2000.0"]`)
- `score_details` — per-field breakdown of points awarded

The top 5 qualified results are returned as `matches`. The full scored list (all active suppliers) is in `matches_all`, which the frontend uses to show how many suppliers were evaluated and how many qualified.
