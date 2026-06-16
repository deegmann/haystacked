#!/usr/bin/env python3
"""
Imports new supplier research results (offline research JSON) into Airtable.

Creates Companies -> Base Models -> Products -> Extensions, mirroring the
ap2_import.py 4-phase pattern. Unlike ap2_import.py, field casting is derived
from the LIVE Airtable schema (Meta API) rather than hardcoded Python lists,
since those lists have drifted from the current AP0 spec.

Prerequisites:
  - .env with AIRTABLE_TOKEN and AIRTABLE_BASE_ID
  - airtable/airtable_schema_ids.json (table IDs)

Run:
  python3 airtable/import_research_results.py --json src/research_results_2026-06-10.json --dry-run
  python3 airtable/import_research_results.py --json src/research_results_2026-06-10.json
"""

import os, sys, json, time, uuid, argparse
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv()

parser = argparse.ArgumentParser()
parser.add_argument("--json", required=True)
parser.add_argument("--dry-run", action="store_true", help="Build records and print summary, but do not call the Airtable API")
args = parser.parse_args()

BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "")
TOKEN   = os.environ.get("AIRTABLE_TOKEN", "")
if not BASE_ID or not TOKEN:
    sys.exit("ERROR: Set AIRTABLE_BASE_ID and AIRTABLE_TOKEN (.env) first.")

json_path = Path(args.json)
if not json_path.exists():
    sys.exit(f"ERROR: {json_path} not found.")

schema_file = Path(__file__).parent / "airtable_schema_ids.json"
if not schema_file.exists():
    sys.exit("ERROR: airtable_schema_ids.json not found.")
TABLE_IDS = json.loads(schema_file.read_text())["table_ids"]

HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
REC_URL = f"https://api.airtable.com/v0/{BASE_ID}"
META    = f"https://api.airtable.com/v0/meta/bases/{BASE_ID}"

# Known-bad values: type-valid strings that don't fit the field's semantics.
# (wms_integration_native=1 etc. are caught generically — not type str — see cast_value.)
MANUAL_SKIP = {
    ("Base Model Extensions", "cleanroom_class", "ISO 1–9"),
    ("Base Model Extensions", "storage_system_type", "VNA Rack"),
}

warnings = []

# ── API helpers ───────────────────────────────────────────────────────────────

def _call(method, url, **kw):
    r = getattr(requests, method)(url, headers=HEADERS, **kw)
    if not r.ok:
        print(f"    ERROR {r.status_code}: {r.text[:300]}")
        r.raise_for_status()
    time.sleep(0.25)
    return r.json()

def batch_create(table_key, records):
    if args.dry_run:
        return [{"id": f"DRYRUN-{table_key}-{i}", "fields": r} for i, r in enumerate(records)]
    tid = TABLE_IDS[table_key]
    created = []
    for i in range(0, len(records), 10):
        batch = records[i:i + 10]
        resp = _call("post", f"{REC_URL}/{tid}",
                     json={"records": [{"fields": r} for r in batch], "typecast": True})
        created.extend(resp["records"])
        print(f"    ... {min(i + 10, len(records))}/{len(records)}")
    return created

def fetch_live_schema():
    data = _call("get", f"{META}/tables")
    field_types = {}
    field_choices = {}
    for t in data["tables"]:
        ft = {}
        fc = {}
        for f in t["fields"]:
            ft[f["name"]] = f["type"]
            if f["type"] in ("singleSelect", "multipleSelects"):
                fc[f["name"]] = [c["name"] for c in f["options"]["choices"]]
        field_types[t["name"]] = ft
        field_choices[t["name"]] = fc
    return field_types, field_choices

def omit_none(d):
    return {k: v for k, v in d.items() if v is not None}

# ── Value casting (driven by live Airtable schema, not hardcoded field lists) ──

def cast_value(table_name, field_name, raw):
    if raw is None:
        return None
    ftype = FIELD_TYPES.get(table_name, {}).get(field_name)
    if ftype is None:
        warnings.append(f"unknown field {table_name}.{field_name} (value dropped: {raw!r})")
        return None

    if (table_name, field_name, raw) in MANUAL_SKIP:
        warnings.append(f"manually excluded {table_name}.{field_name}={raw!r} (doesn't fit field semantics)")
        return None

    if ftype == "checkbox":
        if raw in (0, 1):
            return bool(raw)
        warnings.append(f"bad bool {table_name}.{field_name}={raw!r}")
        return None

    if ftype == "number":
        if isinstance(raw, (int, float)):
            return raw
        warnings.append(f"bad number {table_name}.{field_name}={raw!r}")
        return None

    if ftype in ("singleLineText", "multilineText", "url"):
        s = str(raw).strip()
        return s or None

    if ftype == "singleSelect":
        if not isinstance(raw, str) or not raw.strip():
            warnings.append(f"bad singleSelect {table_name}.{field_name}={raw!r}")
            return None
        choices = FIELD_CHOICES.get(table_name, {}).get(field_name, [])
        if raw not in choices:
            warnings.append(f"new choice {table_name}.{field_name}={raw!r} (not in current {len(choices)} options — will be added via typecast)")
        return raw

    if ftype == "multipleSelects":
        if not isinstance(raw, str):
            warnings.append(f"bad multipleSelects {table_name}.{field_name}={raw!r} (not a string)")
            return None
        parts = [p.strip() for p in raw.split("|") if p.strip()]
        if not parts:
            return None
        choices = FIELD_CHOICES.get(table_name, {}).get(field_name, [])
        for p in parts:
            if p not in choices:
                warnings.append(f"new choice {table_name}.{field_name}={p!r} (not in current {len(choices)} options — will be added via typecast)")
        return parts

    warnings.append(f"unhandled field type {ftype} for {table_name}.{field_name}")
    return None

# ── Phases ───────────────────────────────────────────────────────────────────

def import_companies(entries):
    print(f"\n=== Phase 1: Companies ===")
    seen = {}
    records = []
    names = []
    for e in entries:
        name = e["company"]
        if name in seen:
            continue
        seen[name] = True
        names.append(name)
        f = omit_none({
            "company_name": name,
            "company_id": str(uuid.uuid4()),
            "website": cast_value("Companies", "website", e.get("website")),
        })
        records.append(f)
    created = batch_create("companies", records)
    name_to_id = {names[i]: created[i]["id"] for i in range(len(created))}
    print(f"    {len(created)} Companies")
    return name_to_id

def import_base_models(entries):
    print(f"\n=== Phase 2: Base Models ===")
    records = []
    for e in entries:
        records.append(omit_none({
            "base_model_name": e["product"],
            "base_model_id": str(uuid.uuid4()),
            "agv_type": cast_value("Base Models", "agv_type", e["agv_type"]),
        }))
    created = batch_create("base_models", records)
    print(f"    {len(created)} Base Models")
    return [r["id"] for r in created]

def import_products(entries, company_name_to_id, bm_ids):
    print(f"\n=== Phase 3: Products ===")
    records = []
    for i, e in enumerate(entries):
        co_at_id = company_name_to_id.get(e["company"])
        source_notes = f"{e.get('notes', '')}\n\nSource: {e.get('source_url', '')}".strip()
        records.append(omit_none({
            "product_name": e["product"],
            "product_id": str(uuid.uuid4()),
            "company_id": [co_at_id] if co_at_id else None,
            "base_model_id": [bm_ids[i]] if i < len(bm_ids) else None,
            "agv_type": cast_value("Products", "agv_type", e["agv_type"]),
            "active": True,
            "source_notes": cast_value("Products", "source_notes", source_notes) if source_notes else None,
        }))
    created = batch_create("products", records)
    print(f"    {len(created)} Products")
    return created

def import_extensions(entries, bm_ids):
    print(f"\n=== Phase 4: Base Model Extensions ===")
    records = []
    for i, e in enumerate(entries):
        source_notes = f"{e.get('notes', '')}\n\nSource: {e.get('source_url', '')}".strip()
        f = omit_none({
            "model_name": e["product"],
            "extension_id": str(uuid.uuid4()),
            "base_model_id": [bm_ids[i]] if i < len(bm_ids) else None,
            "agv_type": cast_value("Base Model Extensions", "agv_type", e["agv_type"]),
            "source_notes": cast_value("Base Model Extensions", "source_notes", source_notes) if source_notes else None,
        })
        for key, val in e["specs"].items():
            if key == "product_name":
                continue
            casted = cast_value("Base Model Extensions", key, val)
            if casted is not None:
                f[key] = casted
        records.append(f)
    created = batch_create("extensions", records)
    print(f"    {len(created)} Extensions")
    return created

# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    global FIELD_TYPES, FIELD_CHOICES

    entries = json.loads(json_path.read_text())
    print(f"Loaded {len(entries)} research entries from {json_path}")
    print("Fetching live Airtable schema for field validation...")
    FIELD_TYPES, FIELD_CHOICES = fetch_live_schema()

    if args.dry_run:
        print("\n*** DRY RUN — no Airtable writes will be made ***")

    company_name_to_id = import_companies(entries)
    bm_ids              = import_base_models(entries)
    products            = import_products(entries, company_name_to_id, bm_ids)
    extensions          = import_extensions(entries, bm_ids)

    print(f"\n=== Summary ===")
    print(f"    Companies: {len(company_name_to_id)}")
    print(f"    Base Models / Products / Extensions: {len(bm_ids)} / {len(products)} / {len(extensions)}")

    if warnings:
        print(f"\n=== Warnings ({len(warnings)}) ===")
        for w in warnings:
            print(f"    - {w}")
    else:
        print("\n    No warnings.")

    if args.dry_run:
        print("\nDry run complete. Re-run without --dry-run to write to Airtable.")

if __name__ == "__main__":
    main()
