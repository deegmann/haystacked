#!/usr/bin/env python3
"""
One-shot: apply research findings from docs/research_findings_20260625.md
to Airtable base_model_extensions.

Only HIGH-confidence findings with clear evidence. Conflicts and
config-dependent values are skipped.
"""
import json, os, sys, time
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
    # vna_capable corrections — prevents wrong KO_BOOL_EXCLUSIVE matches
    ("recfrmzRIlf9qRUmX", "Jungheinrich EKS 215a",
     {"vna_capable": False},
     "Official UK page: 'not a VNA truck'; compact order-picker stacker for mixed operation"),

    ("recLVLj2jw1DxTfIb", "Linde R-MATIC k",
     {"vna_capable": False},
     "Automated reach truck (2.90 m aisle), NOT a VNA turret. VNA Linde = K-MATIC (different model)"),

    ("recKFSeK9Ygr47as9", "ek robotics VARIO MOVE CB",
     {"vna_capable": False},
     "Counterbalance forklift AGV — not VNA capable"),

    # New specs — previously NULL
    ("rectyxcOu0GbJTm6X", "STILL MX-X iGo",
     {"min_aisle_width_mm": 1480},
     "VDI technical datasheet: Ast (working aisle) 1480–1875 mm; 1480 is minimum"),

    ("rectbk9yv3dLaLnh8", "STILL LTX 50 iGo",
     {"turning_radius_mm": 1480},
     "STILL official datasheet (VDI 2198/3597): Wa = 1480 mm for LTX 50 Li-Ion variant"),

    ("recIBjvlueDyUwcOv", "KIVNON K05 Underride",
     {"towing_capacity_kg": 1000},
     "Kivnon K05 Twister spec: towing capacity 1000 kg (vs. 450 kg onboard payload). DB had 500 — incorrect."),

    # Coupling type — more complete
    ("recLC0uIJCh68Nrk4", "DS AMADEUS Tugger",
     {"coupling_type": ["Automatic", "Manual"]},
     "DS Automotion page: 'Manual clutch with automatic clutch option' — base is manual, auto is option"),

    # Lift height precision
    ("recWFZZL6OFKj5mJ7", "Balyo VEENY",
     {"lifting_height_mm": 17200},
     "Balyo website: '17,200 mm' lifting height. DB had 17000 — rounding error"),
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
        print(f"    reason: {reason[:80]}")
        try:
            result = patch_record(rec_id, fields)
            updated = result.get("fields", {})
            for k, v in fields.items():
                print(f"    ✓ {k} = {updated.get(k, '?')}")
            ok += 1
        except requests.HTTPError as e:
            print(f"    ✗ FAILED: {e}")
        print()
        time.sleep(0.3)  # rate limit

    print(f"{ok}/{len(UPDATES)} records updated.")
    if ok == len(UPDATES):
        print("\nNow run: python3 sync_airtable.py --local")
        print("Wait — that rebuilds from CSV, not Airtable. Run full sync:")
        print("  python3 sync_airtable.py")


if __name__ == "__main__":
    main()
