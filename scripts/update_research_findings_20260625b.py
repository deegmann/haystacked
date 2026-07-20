#!/usr/bin/env python3
"""
One-shot: apply research findings from docs/research_findings_20260625b.md
to Airtable base_model_extensions.

Session B focus: KO fields (max_payload_kg, lifting_height_mm) + selected
min_aisle_width_mm. All HIGH + PM-approved MEDIUM confidence values.
"""
import json, os, time
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TOKEN   = os.environ["AIRTABLE_TOKEN"]
BASE_ID = os.environ["AIRTABLE_BASE_ID"]

schema = json.loads((Path(__file__).parent.parent / "airtable/airtable_schema_ids.json").read_text())
EXT_TABLE = schema["table_ids"]["extensions"]

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

# (record_id, product_name, {field: value}, reason)
UPDATES = [
    # --- HIGH confidence ---
    ("recKUtxbe4c53mcOo", "STILL EXV iGo",
     {"max_payload_kg": 1600, "lifting_height_mm": 3800},
     "STILL IFOY 2024 press + search: 'residual capacity up to 1600 kg', 'lift goods up to 3.8 m'. "
     "EXV iGo = high-lift pallet truck (NOT counterbalance). Was NULL."),

    ("recYzifAvuLqgIUe5", "DS LUCY",
     {"lifting_height_mm": 600},
     "Official DS Automotion page: 'Lifting height: 600 mm / 23.62 in'. "
     "LUCY is a WHEEL-ARM forklift (low-lift), not counterbalance — 600 mm is correct. Was NULL."),

    ("rec6s86LBKCFblbPX", "Kivnon K55A Pallet Stacker",
     {"max_payload_kg": 1200, "lifting_height_mm": 1500},
     "PMM press article + qviro: '2,645 lbs = 1200 kg payload', '4.9 ft / 1.5 m lift'. "
     "Official Kivnon URL 404s; two independent sources consistent. LOW-lift stacker. Both NULL."),

    ("rectyxcOu0GbJTm6X", "STILL MX-X iGo",
     {"max_payload_kg": 1500, "lifting_height_mm": 14000},
     "STILL.co.uk VNA page: 'load capacities up to 1.5 t'. "
     "iGo automated variant capped at 14,000 mm (manned MX-X = 18m, NOT applicable). "
     "Series max 1500 kg; conservative iGo alternative is 1400 kg. Both were NULL."),

    # --- MEDIUM confidence (PM sign-off given) ---
    ("rec3cCMqMyG9FtMXE", "E80 Trilateral LGV",
     {"min_aisle_width_mm": 1500},
     "elettric80.com VNA page snippet: 'particularly narrow aisles, only 1.5 m wide'. "
     "MEDIUM — not in a numeric datasheet table. E80 LGVs are custom-configured. Was NULL."),

    ("recxRgEceUWbaIX2i", "Hikrobot F3-1500",
     {"min_aisle_width_mm": 2100},
     "Search summary: '2.1 m min aisle for 1200x1000 pallets, right-angle stacking'. "
     "MEDIUM — official hikrobotics.com page returned 403; 2100 mm plausible for low-lift mover. Was NULL."),
]


def patch_record(rec_id: str, fields: dict) -> dict:
    url = f"https://api.airtable.com/v0/{BASE_ID}/{EXT_TABLE}/{rec_id}"
    r = requests.patch(url, headers=HEADERS, json={"fields": fields}, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    print(f"Updating {len(UPDATES)} records in Airtable extensions table...\n")
    ok = 0
    for rec_id, name, fields, reason in UPDATES:
        print(f"  {name} ({rec_id})")
        print(f"    → {fields}")
        print(f"    reason: {reason[:100]}")
        try:
            result = patch_record(rec_id, fields)
            updated = result.get("fields", {})
            for k, v in fields.items():
                print(f"    ✓ {k} = {updated.get(k, '?')}")
            ok += 1
        except requests.HTTPError as e:
            print(f"    ✗ FAILED: {e}")
        print()
        time.sleep(0.3)

    print(f"{ok}/{len(UPDATES)} records updated.")
    if ok == len(UPDATES):
        print("\nRun sync: python3 sync_airtable.py")


if __name__ == "__main__":
    main()
