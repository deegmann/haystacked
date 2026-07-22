#!/usr/bin/env python3
"""
Apply bool field research results to Airtable.

Reads: docs/bool_research_batch_[1-6]_20260722.json
Patches: base_model_extensions table in Airtable

KO SS fields (singleSelect "True"/"False"): True/False applied; null = skip
Non-KO checkbox fields: True applied only; False/null = skip

Run: python3 scripts/apply_bool_research.py [--dry-run]
"""

import csv, json, os, sys, time, argparse
import requests
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true", help="Print changes without applying")
args = parser.parse_args()

BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "")
TOKEN   = os.environ.get("AIRTABLE_TOKEN", "")

if not args.dry_run and (not BASE_ID or not TOKEN):
    sys.exit("ERROR: Set AIRTABLE_BASE_ID and AIRTABLE_TOKEN (or use --dry-run)")

SCHEMA_FILE = Path(__file__).parent.parent / "airtable" / "airtable_schema_ids.json"
if not args.dry_run:
    if not SCHEMA_FILE.exists():
        sys.exit("ERROR: airtable_schema_ids.json not found")
    TABLE_IDS = json.loads(SCHEMA_FILE.read_text())["table_ids"]

DATA_RAW  = Path(__file__).parent.parent / "data" / "raw"
DOCS      = Path(__file__).parent.parent / "docs"

# KO bool fields — migrated to singleSelect["True","False"]
KO_SS_FIELDS = {
    "vna_capable", "stacking_capability", "vda5050_compatible", "infrastructure_free",
    "forks_free_floating", "multi_load_compatibility", "auto_hitch",
    "free_lift_open_closed_pallet", "grid_required", "outdoor_capable",
    "trailer_loading", "trailer_unloading", "barcode_readers",
    "humidity_control_capable", "rack_pin_compatible",
}

# Non-KO bool fields — still checkbox; only set True (can't store explicit False on checkbox)
NON_KO_FIELDS = {
    "autonomous_obstacle_bypass", "omnidirectional_movement", "autonomous_charging",
    "battery_swap_capable", "multi_fleet_capable", "manual_usage", "stock_line_scanning",
    "busbar_compatible", "intersection_management", "rotation_capable",
    "task_interleaving", "onboard_ui", "ergonomic_height_adjustable",
    "multi_language_display", "gamification",
}

ALL_BOOL_FIELDS = KO_SS_FIELDS | NON_KO_FIELDS

# ── Load CSVs ─────────────────────────────────────────────────────────────────

def load_csv(name):
    with open(DATA_RAW / name) as f:
        return list(csv.DictReader(f))

co_rows  = load_csv("companies.csv")
pr_rows  = load_csv("products.csv")
bm_rows  = load_csv("base_models.csv")
ext_rows = load_csv("base_model_extensions.csv")

# Build lookup maps
co_map        = {r["airtable_id"]: r["company_name"]   for r in co_rows}
bm_at_to_uuid = {r["airtable_id"]: r["base_model_id"]  for r in bm_rows}
bm_to_exts    = {}
for r in ext_rows:
    bm_to_exts.setdefault(r.get("base_model_id", ""), []).append(r)

# (company_name, product_name) → list[ext_row]
key_to_exts = {}
for pr in pr_rows:
    prod_name = pr.get("product_name", "").strip()
    co_name   = co_map.get(pr.get("company_id", "").strip(), "")
    bm_at     = pr.get("base_model_id", "").strip()
    bm_uuid   = bm_at_to_uuid.get(bm_at, bm_at)
    exts      = bm_to_exts.get(bm_uuid, []) or bm_to_exts.get(bm_at, [])
    if co_name and prod_name:
        key_to_exts.setdefault((co_name, prod_name), []).extend(exts)

def current_val(ext_row, field):
    """Parse current CSV value: returns True, False, or None."""
    v = ext_row.get(field, "").strip()
    if v.lower() in ("true", "1"):  return True
    if v.lower() in ("false", "0"): return False
    return None

# ── Parse batch files ─────────────────────────────────────────────────────────

def parse_batches():
    """Returns {(company_name, product_name): {field: value}} — research findings."""
    research = {}  # (co, prod) → {field: value}

    for batch_num in range(1, 7):
        path = DOCS / f"bool_research_batch_{batch_num}_20260722.json"
        if not path.exists():
            print(f"  MISSING: {path.name}")
            continue
        data = json.loads(path.read_text())

        for co_name, products in data.items():
            if co_name.startswith("_"):
                continue

            # Normalize to list of (product_name, bool_values_dict)
            items = []
            if isinstance(products, list):
                # Batches 3-6: [{product_name, bool_values, ...}]
                for item in products:
                    pname = item.get("product_name", "").strip()
                    bvals = item.get("bool_values", {})
                    items.append((pname, bvals))
            elif isinstance(products, dict):
                # Batches 1-2: {product_name: {field: value, _notes: {...}}}
                for pname, vals in products.items():
                    bvals = {k: v for k, v in vals.items()
                             if k in ALL_BOOL_FIELDS}
                    items.append((pname.strip(), bvals))

            for pname, bvals in items:
                key = (co_name, pname)
                if key not in research:
                    research[key] = {}
                for field, val in bvals.items():
                    if field not in ALL_BOOL_FIELDS:
                        continue
                    # Normalize: True/False/None
                    if isinstance(val, bool):
                        research[key][field] = val
                    elif isinstance(val, str):
                        if val.lower() == "true":  research[key][field] = True
                        elif val.lower() == "false": research[key][field] = False
                        # else: skip
                    elif val is None:
                        pass  # skip nulls — don't overwrite existing
                    elif isinstance(val, (int, float)):
                        research[key][field] = bool(val)

    return research

research = parse_batches()
print(f"Research entries: {len(research)} (company, product) pairs")

# ── Build change manifest ─────────────────────────────────────────────────────

changes = []  # list of {ext_at_id, company, product, field, old_val, new_val, airtable_val}
unmatched = []

for (co_name, prod_name), bvals in research.items():
    exts = key_to_exts.get((co_name, prod_name), [])
    if not exts:
        # Try case-insensitive match
        for (k_co, k_prod), v in key_to_exts.items():
            if k_co.lower() == co_name.lower() and k_prod.lower() == prod_name.lower():
                exts = v
                break
    if not exts:
        unmatched.append((co_name, prod_name))
        continue

    for ext in exts:
        ext_id = ext["airtable_id"]
        for field, new_val in bvals.items():
            old_val = current_val(ext, field)
            if new_val == old_val:
                continue  # no change

            # Decide what to send to Airtable
            if field in KO_SS_FIELDS:
                # singleSelect: "True" / "False" / None
                if new_val is True:
                    at_val = "True"
                elif new_val is False:
                    at_val = "False"
                else:
                    continue  # null → skip
            else:
                # checkbox: only set True; skip False
                if new_val is True:
                    at_val = True
                else:
                    continue  # False/null on checkbox → skip

            changes.append({
                "ext_at_id": ext_id,
                "company":   co_name,
                "product":   prod_name,
                "field":     field,
                "old_val":   old_val,
                "new_val":   new_val,
                "at_val":    at_val,
            })

# ── Print summary ─────────────────────────────────────────────────────────────

print(f"\n{'='*70}")
print(f"BOOL RESEARCH APPLY REPORT — {'DRY RUN' if args.dry_run else 'LIVE'}")
print(f"{'='*70}")

if unmatched:
    print(f"\n⚠ UNMATCHED ({len(unmatched)}) — no extension record found:")
    for co, prod in sorted(unmatched):
        print(f"  {co} / {prod}")

print(f"\n{len(changes)} changes across {len({c['ext_at_id'] for c in changes})} extension records")

# Group by company for readability
by_co = {}
for c in changes:
    by_co.setdefault(c["company"], []).append(c)

for co in sorted(by_co):
    print(f"\n  {co}")
    by_prod = {}
    for c in by_co[co]:
        by_prod.setdefault(c["product"], []).append(c)
    for prod in sorted(by_prod):
        print(f"    {prod}")
        for c in sorted(by_prod[prod], key=lambda x: x["field"]):
            old_s = str(c["old_val"]) if c["old_val"] is not None else "null"
            new_s = str(c["new_val"])
            print(f"      {c['field']:<35} {old_s:<8} → {new_s}")

# ── Apply changes ─────────────────────────────────────────────────────────────

if args.dry_run:
    print("\n[DRY RUN] No changes applied.")
    sys.exit(0)

# Group by extension record ID → merged fields dict
updates_map = {}
for c in changes:
    ext_id = c["ext_at_id"]
    updates_map.setdefault(ext_id, {})[c["field"]] = c["at_val"]

updates = [{"id": eid, "fields": fields} for eid, fields in updates_map.items()]

HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
REC_URL = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_IDS['extensions']}"

print(f"\nApplying {len(updates)} extension record updates...")
errors = 0
for i in range(0, len(updates), 10):
    batch = updates[i:i+10]
    r = requests.patch(
        f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_IDS['extensions']}",
        headers=HEADERS,
        json={"records": [{"id": u["id"], "fields": u["fields"]} for u in batch],
              "typecast": True},
    )
    if not r.ok:
        print(f"  ERROR batch {i//10+1}: {r.status_code} {r.text[:200]}")
        errors += 1
    else:
        print(f"  ... {min(i+10, len(updates))}/{len(updates)} ✓")
    time.sleep(0.25)

if errors == 0:
    print(f"\nDone. {len(changes)} field values updated across {len(updates)} records.")
    print("Run: python3 sync_airtable.py --local  (or full sync) to refresh the DB.")
else:
    print(f"\nCompleted with {errors} batch error(s). Check output above.")
