#!/usr/bin/env python3
"""
Part 1: Add 3 missing Oceaneering products to existing company record.
Part 2: Patch confirmed specs onto existing idealworks product extensions.

Sources:
  Oceaneering UniMover D 100  — materialhandling247.com + therobotreport.com (MODEX launch)
  Oceaneering CompactMover FOL U 1200 — antdriven.com/oceaneering-compactmover-fol-u-1200
  Oceaneering CompactMover Conveyor U 400 — oceaneering.com/compactmover-conveyor-u-400/
  idealworks iw.hub specs — idealworks.com/en/iw-hub-e/ + qviro cross-reference

Run:
  python3 scripts/add_products_20260630.py
  python3 sync_airtable.py
"""
import json, os, time, uuid
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TOKEN   = os.environ["AIRTABLE_TOKEN"]
BASE_ID = os.environ["AIRTABLE_BASE_ID"]
schema  = json.loads((Path(__file__).parent.parent / "airtable/airtable_schema_ids.json").read_text())

TABLES = {
    "companies":   schema["table_ids"]["companies"],
    "base_models": schema["table_ids"]["base_models"],
    "products":    schema["table_ids"]["products"],
    "extensions":  schema["table_ids"]["extensions"],
}
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

SLAM = ["Natural Feature (SLAM)"]

# Oceaneering's Airtable company record ID (existing)
OCEANEERING_CO = "rec8blP7rKmtibWcx"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def post(table: str, fields: dict) -> str:
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES[table]}"
    r = requests.post(url, headers=HEADERS, json={"fields": fields}, timeout=30)
    if not r.ok:
        print(f"    HTTP {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    return r.json()["id"]


def patch(table: str, rec_id: str, fields: dict) -> None:
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES[table]}/{rec_id}"
    r = requests.patch(url, headers=HEADERS, json={"fields": fields}, timeout=30)
    if not r.ok:
        print(f"    HTTP {r.status_code}: {r.text[:300]}")
    r.raise_for_status()


def find_ext_by_name(name: str):
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES['extensions']}"
    r = requests.get(url, headers=HEADERS,
                     params={"filterByFormula": f'{{model_name}}="{name}"', "maxRecords": 1},
                     timeout=30)
    r.raise_for_status()
    recs = r.json().get("records", [])
    return recs[0] if recs else None


def find_base_model_by_name(name: str):
    """Return existing Airtable base_model record ID, or None."""
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES['base_models']}"
    r = requests.get(url, headers=HEADERS,
                     params={"filterByFormula": f'{{base_model_name}}="{name}"', "maxRecords": 1},
                     timeout=30)
    r.raise_for_status()
    recs = r.json().get("records", [])
    return recs[0]["id"] if recs else None


def create_product(company_rec_id: str, name: str, product_type: str, ext_fields: dict,
                   source_notes: str = "", is_oem: bool = False) -> None:
    print(f"\n  → {name}")

    # 1. Base model — reuse if already exists (idempotent)
    bm_id = find_base_model_by_name(name)
    if bm_id:
        print(f"    base_model={bm_id[:8]}… (existing)")
    else:
        bm_id = post("base_models", {
            "base_model_name": name,
            "product_type": product_type,
            "oem_link_public": True,
            "last_updated": "2026-06-30",
        })
        print(f"    base_model={bm_id[:8]}… (new)")
    time.sleep(0.3)

    # 2. Product (linked to company + base_model; no service_coverage — multi-select, set in Airtable UI)
    prod_fields = {
        "product_name": name,
        "product_type": product_type,
        "company_id": [company_rec_id],
        "base_model_id": [bm_id],
        "product_description": source_notes or name,
        "active": True,
        "is_oem_product": is_oem,
    }
    prod_id = post("products", prod_fields)
    print(f"    product={prod_id[:8]}…")
    time.sleep(0.3)

    # 3. Extension (spec fields)
    ext = {
        "model_name": name,
        "product_type": product_type,
        "base_model_id": [bm_id],
        "extension_id": str(uuid.uuid4()),
    }
    ext.update(ext_fields)
    ext_id = post("extensions", ext)
    print(f"    extension={ext_id[:8]}… ✓")
    time.sleep(0.3)


# ---------------------------------------------------------------------------
# Part 1: New Oceaneering products
# ---------------------------------------------------------------------------

OCEANEERING_PRODUCTS = [
    {
        "name": "UniMover D 100",
        "product_type": "Mobile AMR",
        "source_notes": (
            "oceaneering.com / materialhandling247.com UniMover D 100. "
            "Smallest underride AMR, 100 kg / 220 lb, 1.9 m/s, BlueBotics ANT "
            "natural-feature SLAM. Launched at MODEX 2022 alongside O 600 and "
            "MaxMover CB D 2000. Confirmed current 2026-06-30. HIGH confidence."
        ),
        "ext": {
            "max_payload_kg": 100,
            "max_speed_ms": 1.9,
            "navigation_type": SLAM,
            "vna_capable": False,
            "stacking_capability": False,
        },
    },
    {
        "name": "CompactMover FOL U 1200",
        "product_type": "Forklift AGV",
        "source_notes": (
            "antdriven.com/oceaneering-compactmover-fol-u-1200 (BlueBotics ANT partner mirror). "
            "Fork-over-leg pallet stacker AGV, 1200 kg, lift 1100 mm (mast height), "
            "BlueBotics ANT natural-feature SLAM. Speed not OEM-published — NULL. "
            "Not VNA (conventional fork-over-leg geometry). HIGH confidence on payload/lift."
        ),
        "ext": {
            "max_payload_kg": 1200,
            "lifting_height_mm": 1100,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "name": "CompactMover Conveyor U 400",
        "product_type": "Mobile AMR",
        "source_notes": (
            "oceaneering.com/compactmover-conveyor-u-400/. Conveyor-deck transfer AMR, "
            "400 kg, 1.9 m/s, BlueBotics ANT natural-feature SLAM. Transfer height "
            "428–1600 mm is conveyor-level, NOT mast lift → lifting_height_mm = NULL. "
            "HIGH confidence."
        ),
        "ext": {
            "max_payload_kg": 400,
            "max_speed_ms": 1.9,
            "navigation_type": SLAM,
            "stacking_capability": False,
            "vna_capable": False,
        },
    },
]


def run_oceaneering():
    print("=" * 60)
    print("PART 1: Oceaneering — 3 new products")
    print("=" * 60)
    for p in OCEANEERING_PRODUCTS:
        create_product(
            company_rec_id=OCEANEERING_CO,
            name=p["name"],
            product_type=p["product_type"],
            ext_fields=p["ext"],
            source_notes=p["source_notes"],
        )
    print("\nOceaneering done.")


# ---------------------------------------------------------------------------
# Part 2: idealworks — patch confirmed specs onto existing extensions
# ---------------------------------------------------------------------------

IDEALWORKS_PATCHES = [
    {
        "name": "iw.hub",
        "fields": {
            "max_payload_kg": 1000,
            "max_speed_ms": 2.2,
            "navigation_type": SLAM,
        },
        "note": "Source: idealworks.com/en/iw-hub-e/ + qviro — HIGH confidence",
    },
    {
        "name": "iw.hub + Pallet Dock",
        "fields": {
            "max_payload_kg": 1000,
            "max_speed_ms": 2.2,
            "navigation_type": SLAM,
        },
        "note": "Same chassis as iw.hub — accessory config, identical KO specs",
    },
]


def find_product_by_name(name: str):
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES['products']}"
    r = requests.get(url, headers=HEADERS,
                     params={"filterByFormula": f'{{product_name}}="{name}"', "maxRecords": 1},
                     timeout=30)
    r.raise_for_status()
    recs = r.json().get("records", [])
    return recs[0] if recs else None


def run_idealworks():
    print("\n" + "=" * 60)
    print("PART 2: idealworks — create/patch extension specs")
    print("=" * 60)
    for p in IDEALWORKS_PATCHES:
        print(f"\n  → {p['name']}")
        # Try patch first; if no extension, create one via the product's base_model
        ext = find_ext_by_name(p["name"])
        if ext:
            patch("extensions", ext["id"], p["fields"])
            print(f"    ✓ patched: {p['fields']}")
        else:
            prod = find_product_by_name(p["name"])
            if not prod:
                print(f"    ✗ Product not found in Airtable")
                continue
            bm_ids = prod["fields"].get("base_model_id", [])
            if not bm_ids:
                print(f"    ✗ Product has no base_model_id")
                continue
            bm_id = bm_ids[0]
            # Determine product_type from product
            product_type = prod["fields"].get("product_type", "Mobile AMR")
            ext_fields = {
                "model_name": p["name"],
                "product_type": product_type,
                "base_model_id": [bm_id],
                "extension_id": str(uuid.uuid4()),
            }
            ext_fields.update(p["fields"])
            ext_id = post("extensions", ext_fields)
            print(f"    ✓ created extension={ext_id[:8]}… with {p['fields']}")
        time.sleep(0.3)
    print("\nidealworks done.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_oceaneering()
    run_idealworks()
    print("\n" + "=" * 60)
    print("All done. Next: python3 sync_airtable.py")
