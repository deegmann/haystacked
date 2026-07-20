#!/usr/bin/env python3
"""Fix corrections that failed in patch_extensions_20260630.py."""
import json, os, time, requests
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

TOKEN   = os.environ["AIRTABLE_TOKEN"]
BASE_ID = os.environ["AIRTABLE_BASE_ID"]
schema  = json.loads((Path(__file__).parent.parent / "airtable/airtable_schema_ids.json").read_text())
TABLES  = {k: schema["table_ids"][k] for k in ["companies","base_models","products","extensions"]}
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def find_ext(name):
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES['extensions']}"
    r = requests.get(url, headers=HEADERS,
                     params={"filterByFormula": f'{{model_name}}="{name}"', "maxRecords": 1},
                     timeout=30)
    r.raise_for_status()
    recs = r.json().get("records", [])
    return recs[0] if recs else None


def find_product(name):
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES['products']}"
    r = requests.get(url, headers=HEADERS,
                     params={"filterByFormula": f'{{product_name}}="{name}"', "maxRecords": 1},
                     timeout=30)
    r.raise_for_status()
    recs = r.json().get("records", [])
    return recs[0] if recs else None


def patch(table, rec_id, fields):
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES[table]}/{rec_id}"
    r = requests.patch(url, headers=HEADERS, json={"fields": fields}, timeout=30)
    if not r.ok:
        print(f"    HTTP {r.status_code}: {r.text[:200]}")
    r.raise_for_status()


def list_kivnon_products():
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES['products']}"
    r = requests.get(url, headers=HEADERS,
                     params={"filterByFormula": 'FIND("K0", {product_name})', "maxRecords": 20},
                     timeout=30)
    r.raise_for_status()
    return [(rec["id"], rec["fields"].get("product_name",""), rec["fields"].get("active",""))
            for rec in r.json().get("records", [])]


if __name__ == "__main__":
    # 1. MLR Mayesto: update extension (product was already updated)
    print("→ MLR Mayesto extension")
    ext = find_ext("MLR Mayesto")
    if ext:
        patch("extensions", ext["id"], {
            "product_type": "Forklift AGV",
            "max_payload_kg": 1500,
            "lifting_height_mm": 11000,
            "max_speed_ms": 2.7,
            "navigation_type": ["Magnetic Tape"],
            "stacking_capability": True,
        })
        print("  ✓ Extension updated")
    else:
        print("  ✗ Not found")
    time.sleep(0.3)

    # 2. VisionNav VNE20: payload → 2000
    print("→ VisionNav VNE20")
    ext = find_ext("VisionNav VNE20")
    if ext:
        patch("extensions", ext["id"], {"max_payload_kg": 2000})
        print("  ✓ payload → 2000 kg")
    else:
        print("  ✗ Not found")
    time.sleep(0.3)

    # 3. Grenzebach FF1200S: navigation → Inductive Loop
    print("→ Grenzebach FF1200S")
    ext = find_ext("Grenzebach FF1200S")
    if ext:
        patch("extensions", ext["id"], {"navigation_type": ["Inductive Loop"]})
        print("  ✓ navigation_type → Inductive Loop")
    else:
        print("  ✗ Not found")
    time.sleep(0.3)

    # 4. E80 Trilateral LGV: vna_capable = True
    print("→ E80 Trilateral LGV")
    ext = find_ext("E80 Trilateral LGV")
    if ext:
        patch("extensions", ext["id"], {"vna_capable": True})
        print("  ✓ vna_capable = True")
    else:
        print("  ✗ Not found")
    time.sleep(0.3)

    # 5. KIVNON: find K03/K41 by listing K0* products
    print("→ KIVNON K0x products:")
    for rec_id, name, active in list_kivnon_products():
        print(f"  {name!r}  active={active}  id={rec_id[:8]}…")
    time.sleep(0.3)

    # Try common name variants
    for name in ["K41 Platform", "KIVNON K41 Platform", "K41 (Platform)"]:
        prod = find_product(name)
        if prod:
            patch("products", prod["id"], {"active": False})
            print(f"  ✓ Deactivated: {name}")
            time.sleep(0.3)
            break
    else:
        print("  ⚠ K41 not found under any variant — check Airtable manually")

    print("\nDone. Next: python3 sync_airtable.py")
