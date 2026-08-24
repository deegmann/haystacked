# Variant-Split Migration Plan — 2026-08-24

## Background

`scripts/import_datasheet_project_20260822.py`'s live run (2026-08-24) correctly
handled 3 explicitly-named variant-split cases (Linde L-MATIC AC/AC k, K-MATIC)
but missed a broader, structurally-identical problem: several DB rows are
**blends of multiple genuinely distinct real products** that all fuzzy-matched
onto one existing row. Where the colliding field was already non-null in the
DB, this surfaced as a flagged CONFLICT (sometimes correctly triaged
`VARIANT-SPLIT-NEEDED` and left alone). Where the colliding field was blank,
it went through the ENRICH FILLS path instead — each colliding dataset entry
individually looked like a harmless null-fill, so nothing flagged it, and the
import script wrote candidate values for each variant into the same row/field
sequentially with **no collision check**: last write silently won. Verified
directly against `docs/import_datasheet_project_20260822_audit.jsonl` and the
live DB — e.g. `VisionNav VNP15.min_aisle_width` received three different
ENRICH FILLS writes (3150 → 3100 → 3350) with no record of which is correct.

## Scope: 17 DB rows / 40 real variants confirmed to need splitting

Determined by cross-referencing `docs/datasheet_db_status_final.json`'s
`db_product_rows` overlap (which dataset entries share one DB row) against
each entry's `conflicts[].triage_verdict` and, where absent, direct
inspection of the underlying per-field source citations in the company's
`docs/research_findings_{datasheet,opus}_*.json` files.

**Decision rule per row:**
- **ANCHOR**: exactly one variant's `product_name` is byte-identical to the
  current DB row name → that DB row/product_id/base_model_id is KEPT (do not
  deactivate), its extension/product fields are PATCHED with that variant's
  resolved field values (correcting the blended junk currently there). New
  rows are created only for the OTHER variant(s) in the group.
- **FULL-RETIRE**: no variant name exactly matches the DB row name (the row
  name is itself a generic/combined label, e.g. `"LOWY / LOWY HD"`, or none
  of the suffix-variants match a bare name) → deactivate the existing row
  entirely (same mechanism as the Linde splits — `_pop_matching()` to retract
  any already-queued patches, then a `active=0` patch) and create N new rows,
  one per real variant.

| Company | DB row | Real variants | Decision |
|---|---|---|---|
| AGILOX Services GmbH | AGILOX ONE | AGILOX ONE, AGILOX ONE (Doppelscherenhub) | ANCHOR → AGILOX ONE |
| AGILOX Services GmbH | AGILOX ODM 600/800 | AGILOX ODM 600, AGILOX ODM 800 | FULL-RETIRE |
| Balyo | LOWY / LOWY HD | LOWY, LOWY HD | FULL-RETIRE |
| Linde Material Handling | Linde C-MATIC | Linde C-MATIC, Linde C-MATIC 10 | ANCHOR → Linde C-MATIC |
| SAFELOG GmbH | SAFELOG AGV L2 | SAFELOG L2 lift, SAFELOG L2 core | FULL-RETIRE |
| SAFELOG GmbH | SAFELOG AGV M4 | SAFELOG M4 core, SAFELOG M4 lift, SAFELOG M4 tow | FULL-RETIRE |
| SAFELOG GmbH | SAFELOG AGV S3 | SAFELOG S3 tow, SAFELOG S3 core | FULL-RETIRE |
| SAFELOG GmbH | SAFELOG AGV X1 | SAFELOG X1 lift 1200, SAFELOG X1 spin, SAFELOG X1 core | FULL-RETIRE |
| Toyota Material Handling Europe | Toyota Staxio SAE160 Autopilot | ...(Triplex Hi-Lo), ...(Duplex Tele) | FULL-RETIRE |
| VisionNav Robotics | VisionNav VNSL14 | VNSL14, VNSL14(V)-07, VNSL14(VL)-07 | ANCHOR → VNSL14 |
| VisionNav Robotics | VisionNav VNP15 | VNP15, VNP15(V)-07, VNP15(VL)-07 | ANCHOR → VNP15 |
| VisionNav Robotics | VisionNav VNQ50 | VNQ50, VNQ50(VL)-01 | ANCHOR → VNQ50 |
| VisionNav Robotics | VisionNav VNE40 | VNE40, VNE40(VL)-07 | ANCHOR → VNE40 |
| VisionNav Robotics | VisionNav VNE20 | VNE20, VNE20(VL)-07 | ANCHOR → VNE20 |
| VisionNav Robotics | VisionNav VNST20 | VNST20, VNST20(VL)-66 | ANCHOR → VNST20 |
| VisionNav Robotics | VisionNav VNR16 | VNR16(V)-01, VNR16(V)-07 (Manual Handheld), VNR16(V)-07 (Manual Seated), VNR16(VL)-01 | FULL-RETIRE |
| VisionNav Robotics | VisionNav VNP20 | VNP20(V)-07, VNP20(VL)-07 | FULL-RETIRE |

Note `VisionNav VNP15A(V)-07` was already correctly created as a standalone
new row by the original import (it never collided) — do not touch it.

## EXCLUDED — do NOT split (confirmed false positives, already correctly resolved)

These 4 groups also show up under the naive "multiple dataset entries share a
DB row" heuristic but are NOT real distinct products — verified by reading
their triage reasoning directly:

- **DS Automotion GmbH | OSCAR Spin 360** and **OSCAR Omni** — the
  colliding "extra" entry is a combined catalog-summary read
  (`"OSCAR spin 180 / OSCAR spin 360 / OSCAR omni"`) whose per-field values
  were already manually triaged and correctly attributed to the right
  existing row (e.g. `"OSCAR Spin 360 = 1620mm (datasheet correct)"`).
  Nothing is broken; both rows already exist correctly and separately.
- **ek robotics | ek robotics COMPACT MOVE CB 25** — explicit triage
  reasoning: *"Mapping artefact, not a data conflict: a series-level read
  was fanned onto both DB rows... DB is correct."* Not two products.
- **Grenzebach Maschinenbau GmbH | Grenzebach L1200S** — explicit triage
  reasoning: *"the 'L1200S-Li' merged entry and the 'L1200S' merged entry
  hold byte-identical field values... they are the same product read twice,
  not two products."*

If your own re-derivation of the collision list produces these 4 groups,
do not act on them — this exclusion is deliberate, not an oversight.

## Data source per variant (in priority order)

1. If a `conflicts[]` entry in `docs/datasheet_db_status_final.json` for this
   exact (company, db_row, field) already carries a `triage_verdict` of
   `RESOLVED` with a `triage_correct_value` — use that resolved value, not
   the raw datasheet value (it reflects prior Tech Lead review and may say
   "keep DB", a union, a corrected number, or similar).
2. Otherwise, pull the field from the variant's entry in
   `docs/research_findings_opus_20260808_*.json` (match on `product_name`
   under `products[]`, read from its `fields` dict). Opus is the
   session's established stronger/more-reliable source for this corpus.
3. If a field is absent from the opus entry, fall back to the matching
   entry (by `product_name`, allowing for the `SAFELOG AGV X1 lift 1200`
   vs `SAFELOG X1 lift 1200` "AGV"-prefix naming difference between the
   sonnet/opus source files and the merged dataset's canonical names) in
   `docs/research_findings_datasheet_20260806_*.json`.
4. Never invent a value. If a field is in neither source, leave it null.

## Implementation requirements

Follow the exact same conventions already proven in
`scripts/import_datasheet_project_20260822.py` — do not reinvent:
- `--dry-run` / `--run` flags; dry-run is the default and must be run first.
- Persistent audit log (new file, e.g.
  `docs/variant_split_full_20260824_audit.jsonl`), one line per patch/create.
- Airtable schema pre-validation via the Meta API before every write
  (`_filter_known_fields()` pattern) — a field that exists in AP0/fields.json
  but not as a real Airtable column must be dropped and logged, not crash
  the run (this exact failure mode crashed the original live run on
  `tugger_min_aisle_width`).
- `_write_with_retry()` pattern: catch `UNKNOWN_FIELD_NAME` specifically,
  strip the field, retry once.
- Idempotent/resumable: before creating a Product/Base Model/Extension,
  check Airtable for an existing record with that `product_id` /
  `base_model_id` first (live lookup, not just the local DB) so a re-run
  after a crash does not duplicate.
- For FULL-RETIRE rows: deactivate using the `active` field — **use the
  fixed `sync_airtable.py` semantics** (send an explicit `false`/unchecked
  value via the Airtable API's Checkbox convention; this migration writes
  to Airtable directly via the API, not through sync_airtable.py, so this
  note is about matching the semantics, not calling that script).
- Every new Product/Base Model/Extension row must carry a `source_notes`
  or equivalent provenance note citing which document/page the data came
  from (reuse the source citations already present in the research_findings
  `field_sources` where available).

## Definition of Done

1. `--dry-run` output reviewed by Tech Lead (me) and explicitly approved
   before any `--run` execution — do not run live without that approval,
   even though the user has pre-authorized this migration in principle.
2. After `--run`: `python3 sync_airtable.py` (live fetch, not `--local`,
   since this migration writes directly to Airtable) completes cleanly.
3. Re-run the collision scan (group audit-log/DB fields by
   (company, db_row, field), flag any field that still shows a mismatch
   between multiple real variants' expected values) — must show zero
   remaining collisions among these 17 rows.
4. `pytest tests/` fully green.
5. Spot-check at least 5 of the 40 new/patched rows against their cited
   source page — value must match the citation exactly.
