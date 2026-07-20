#!/usr/bin/env python3
"""
One-shot Airtable migration: Option D fixup for IK records.

What this does:
  1. Add 'served_categories' MultiSelect field to Base Model Extensions (if missing)
  2. Update existing IK extension records:
     - agv_type: "Process Cooling"/"Cold Store"/"Deep Freeze" → "Industrial Refrigeration"
     - served_categories: set to original agv_type value (or "Cold Store|Deep Freeze" for BITZER)
  3. Update existing IK base_model records: same agv_type fix
  4. Update existing IK product records: same agv_type fix
  5. Re-run sync_airtable.py to regenerate local CSVs and DB

Run once after airtable_ik_migration.py was already run (pre-Option-D records exist).
Idempotent: safe to re-run.
"""

import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TOKEN   = os.environ.get("AIRTABLE_TOKEN", "")
BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "")
if not TOKEN or not BASE_ID:
    sys.exit("ERROR: AIRTABLE_TOKEN and AIRTABLE_BASE_ID must be set in .env")

HEADERS  = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
META_URL = f"https://api.airtable.com/v0/meta/bases/{BASE_ID}/tables"
DATA_URL = f"https://api.airtable.com/v0/{BASE_ID}"

TABLE_IDS = {
    "companies":   "tblxZNhyTlfd1c5Po",
    "base_models": "tblsaCzUQUrC4m7lj",
    "products":    "tblgizCLjKYcCAbwp",
    "extensions":  "tblinb1Zn0Ihc977M",
}

IK_SUBTYPES = {"Process Cooling", "Cold Store", "Deep Freeze"}

# BITZER dual-capability: gets both Cold Store AND Deep Freeze
BITZER_KEYWORDS = {"bitzer", "coss", "transcritical", "co2 system"}


def _get(url, **kwargs):
    r = requests.get(url, headers=HEADERS, **kwargs)
    r.raise_for_status()
    return r.json()


def _post(url, data):
    r = requests.post(url, headers=HEADERS, json=data)
    if not r.ok:
        print(f"  POST error {r.status_code}: {r.text[:400]}")
    r.raise_for_status()
    time.sleep(0.3)
    return r.json()


def _patch(url, data, typecast=False):
    payload = dict(data)
    if typecast:
        payload["typecast"] = True
    r = requests.patch(url, headers=HEADERS, json=payload)
    if not r.ok:
        print(f"  PATCH error {r.status_code}: {r.text[:400]}")
    r.raise_for_status()
    time.sleep(0.3)
    return r.json()


def _fetch_all(table_key):
    records = []
    params  = {}
    url     = f"{DATA_URL}/{TABLE_IDS[table_key]}"
    while True:
        data = _get(url, params=params)
        records.extend(data.get("records", []))
        if not data.get("offset"):
            break
        params = {"offset": data["offset"]}
        time.sleep(0.25)
    return records


def get_table_schema():
    data = _get(META_URL)
    return {t["name"]: t for t in data["tables"]}


def step0_add_agv_type_option(schema):
    """Add 'Industrial Refrigeration' as a valid choice to agv_type Single Select in all three tables."""
    print("\nStep 0: Adding 'Industrial Refrigeration' option to agv_type field...")
    for table_name in ("Base Model Extensions", "Base Models", "Products"):
        t   = schema.get(table_name)
        if not t:
            print(f"  {table_name}: not found in schema — skip")
            continue
        tid = t["id"]
        # Find the agv_type field
        agv_field = next((f for f in t["fields"] if f["name"] == "agv_type"), None)
        if not agv_field:
            print(f"  {table_name}: agv_type field not found — skip")
            continue
        existing_choices = [c["name"] for c in agv_field.get("options", {}).get("choices", [])]
        if "Industrial Refrigeration" in existing_choices:
            print(f"  {table_name}: 'Industrial Refrigeration' already in choices — skip")
            continue
        # PATCH the field to add the new choice.
        # Airtable requires ALL existing choices (with their IDs) + new choice (no ID).
        url = f"{META_URL}/{tid}/fields/{agv_field['id']}"
        existing_choice_objs = agv_field.get("options", {}).get("choices", [])
        new_choices = [{"id": c["id"], "name": c["name"]} for c in existing_choice_objs]
        new_choices.append({"name": "Industrial Refrigeration"})
        r = requests.patch(url, headers=HEADERS, json={
            "options": {"choices": new_choices}
        })
        if not r.ok:
            print(f"  {table_name}: PATCH error {r.status_code}: {r.text[:400]}")
            r.raise_for_status()
        print(f"  {table_name}: added 'Industrial Refrigeration' to agv_type choices")
        time.sleep(0.3)


def step1_add_served_categories_field(schema):
    """Add 'served_categories' MultiSelect to Base Model Extensions if missing."""
    print("\nStep 1: served_categories field in Base Model Extensions...")
    t   = schema["Base Model Extensions"]
    tid = t["id"]
    existing = {f["name"] for f in t["fields"]}
    if "served_categories" in existing:
        print("  served_categories: already exists — skip")
        return
    url     = f"{META_URL}/{tid}/fields"
    payload = {
        "name": "served_categories",
        "type": "multipleSelects",
        "options": {
            "choices": [
                {"name": "Process Cooling"},
                {"name": "Cold Store"},
                {"name": "Deep Freeze"},
            ]
        },
    }
    _post(url, payload)
    print("  served_categories: created (multipleSelects)")


def _is_bitzer(fields: dict) -> bool:
    """Heuristic: is this the BITZER dual-capability record?"""
    for val in fields.values():
        if isinstance(val, str) and any(kw in val.lower() for kw in BITZER_KEYWORDS):
            return True
    return False


def step2_fix_extensions(schema):
    """Fix agv_type + set served_categories on IK extension records."""
    print("\nStep 2: Fixing IK extension records...")
    records = _fetch_all("extensions")
    ik_recs = [r for r in records if r["fields"].get("agv_type") in IK_SUBTYPES]
    print(f"  Found {len(ik_recs)} IK extension records to fix")
    for rec in ik_recs:
        rec_id      = rec["id"]
        fields      = rec["fields"]
        old_subtype = fields["agv_type"]
        # Dual-capability check for BITZER
        if _is_bitzer(fields):
            served = ["Cold Store", "Deep Freeze"]
        else:
            served = [old_subtype]
        url = f"{DATA_URL}/{TABLE_IDS['extensions']}/{rec_id}"
        _patch(url, {"fields": {
            "agv_type":         "Industrial Refrigeration",
            "served_categories": served,
        }}, typecast=True)
        print(f"  {rec_id}: agv_type {old_subtype!r} → 'Industrial Refrigeration', served_categories={served}")


def step3_fix_base_models():
    """Fix agv_type on IK base_model records."""
    print("\nStep 3: Fixing IK base_model records...")
    records = _fetch_all("base_models")
    ik_recs = [r for r in records if r["fields"].get("agv_type") in IK_SUBTYPES]
    print(f"  Found {len(ik_recs)} IK base_model records to fix")
    for rec in ik_recs:
        rec_id      = rec["id"]
        old_subtype = rec["fields"]["agv_type"]
        url = f"{DATA_URL}/{TABLE_IDS['base_models']}/{rec_id}"
        _patch(url, {"fields": {"agv_type": "Industrial Refrigeration"}}, typecast=True)
        print(f"  {rec_id}: agv_type {old_subtype!r} → 'Industrial Refrigeration'")


def step4_fix_products():
    """Fix agv_type on IK product records."""
    print("\nStep 4: Fixing IK product records...")
    records = _fetch_all("products")
    ik_recs = [r for r in records if r["fields"].get("agv_type") in IK_SUBTYPES]
    print(f"  Found {len(ik_recs)} IK product records to fix")
    for rec in ik_recs:
        rec_id      = rec["id"]
        old_subtype = rec["fields"]["agv_type"]
        url = f"{DATA_URL}/{TABLE_IDS['products']}/{rec_id}"
        _patch(url, {"fields": {"agv_type": "Industrial Refrigeration"}}, typecast=True)
        print(f"  {rec_id}: agv_type {old_subtype!r} → 'Industrial Refrigeration'")


def main():
    print("=" * 60)
    print("haystacked — IK Airtable Migration (Option D fixup)")
    print("=" * 60)

    schema = get_table_schema()

    # step0 skipped: typecast=True in record updates handles new select options
    step1_add_served_categories_field(schema)
    step2_fix_extensions(schema)
    step3_fix_base_models()
    step4_fix_products()

    print("\n" + "=" * 60)
    print("Done. Now run:")
    print("  python3 sync_airtable.py")
    print("to regenerate local CSVs and DB from Airtable.")
    print("=" * 60)


if __name__ == "__main__":
    main()
