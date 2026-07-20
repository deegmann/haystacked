#!/usr/bin/env python3
"""
Patch: create missing extensions for 18 products that failed in import_products_20260629.py.
Fixes: battery_type must be array (multi-select), tugger_min_aisle_width_mm → min_aisle_width_mm.
Also applies the 5 manual corrections (MLR Mayesto, VNE20, Grenzebach, E80, KIVNON).

Run: python3 scripts/patch_extensions_20260630.py
Then: python3 sync_airtable.py
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

SLAM      = ["Natural Feature (SLAM)"]
QR        = ["QR/DM Code"]
REFLECTOR = ["Laser Reflector"]
REFLECTOR_SLAM = ["Laser Reflector", "Natural Feature (SLAM)"]

# battery_type as arrays (multi-select)
LI_ION   = ["Li-Ion"]
LIFEPO4  = ["LiFePO4"]
LEAD_ACID = ["Lead-Acid"]


def get_record(table_name: str, record_id: str) -> dict:
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES[table_name]}/{record_id}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def find_base_model_by_name(name: str):
    """Return Airtable record ID of base_model with given base_model_name."""
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES['base_models']}"
    params = {"filterByFormula": f'{{base_model_name}}="{name}"', "maxRecords": 1}
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    records = r.json().get("records", [])
    return records[0]["id"] if records else None


def post_record(table_name: str, fields: dict) -> str:
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES[table_name]}"
    r = requests.post(url, headers=HEADERS, json={"fields": fields}, timeout=30)
    if not r.ok:
        print(f"    HTTP {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    return r.json()["id"]


def patch_record(table_name: str, record_id: str, fields: dict) -> None:
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES[table_name]}/{record_id}"
    r = requests.patch(url, headers=HEADERS, json={"fields": fields}, timeout=30)
    if not r.ok:
        print(f"    HTTP {r.status_code}: {r.text[:300]}")
    r.raise_for_status()


# ---------------------------------------------------------------------------
# Part 1: Missing extensions (18 products)
# ---------------------------------------------------------------------------

MISSING_EXTENSIONS = [
    {
        "name": "VisionNav VNQ50",
        "agv_type": "Tugger AGV",
        "ext": {
            "max_payload_kg": 5000,
            "towing_capacity_kg": 19958,
            "min_aisle_width_mm": 1700,   # fixed: was tugger_min_aisle_width_mm
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
            "vna_capable": False,
        },
    },
    {
        "name": "MiR100",
        "agv_type": "Mobile AMR",
        "ext": {
            "max_payload_kg": 100,
            "max_speed_ms": 1.5,
            "navigation_type": SLAM,
            "autonomous_charging": True,
            "battery_type": LI_ION,    # fixed: was "Li-Ion"
        },
    },
    {
        "name": "MiR200",
        "agv_type": "Mobile AMR",
        "ext": {
            "max_payload_kg": 200,
            "max_speed_ms": 1.5,
            "navigation_type": SLAM,
            "autonomous_charging": True,
            "battery_type": LI_ION,
        },
    },
    {
        "name": "MiR500",
        "agv_type": "Mobile AMR",
        "ext": {
            "max_payload_kg": 500,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
            "autonomous_charging": True,
            "battery_type": LI_ION,
        },
    },
    {
        "name": "MiR1000",
        "agv_type": "Mobile AMR",
        "ext": {
            "max_payload_kg": 1000,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
            "autonomous_charging": True,
            "battery_type": LI_ION,
        },
    },
    {
        "name": "OTTO 750",
        "agv_type": "Mobile AMR",
        "ext": {
            "max_payload_kg": 750,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
            "battery_type": LI_ION,
        },
    },
    {
        "name": "Omron LD-130CT",
        "agv_type": "Mobile AMR",
        "ext": {
            "max_payload_kg": 130,
            "max_speed_ms": 0.9,
            "navigation_type": SLAM,
            "battery_type": LEAD_ACID,
        },
    },
    {
        "name": "Omron MD-650",
        "agv_type": "Mobile AMR",
        "ext": {
            "max_payload_kg": 650,
            "max_speed_ms": 2.2,
            "navigation_type": SLAM,
            "battery_type": LI_ION,
            "autonomous_charging": True,
        },
    },
    {
        "name": "Omron MD-900",
        "agv_type": "Mobile AMR",
        "ext": {
            "max_payload_kg": 900,
            "max_speed_ms": 1.8,
            "navigation_type": SLAM,
            "battery_type": LI_ION,
            "autonomous_charging": True,
        },
    },
    {
        "name": "Jungheinrich ERE 225a",
        "agv_type": "Forklift AGV",
        "ext": {
            "max_payload_kg": 2500,
            "lifting_height_mm": 125,
            "max_speed_ms": 2.0,
            "navigation_type": REFLECTOR,
            "battery_type": LI_ION,
            "stacking_capability": False,
            "vna_capable": False,
        },
    },
    {
        "name": "STILL ACH 06 iGo",
        "agv_type": "Mobile AMR",
        "ext": {
            "max_payload_kg": 600,
            "lifting_height_mm": 55,
            "max_speed_ms": 2.0,
            "navigation_type": QR,
            "battery_type": LI_ION,
            "min_aisle_width_mm": 1473,
        },
    },
    {
        "name": "STILL ACH 10 iGo",
        "agv_type": "Mobile AMR",
        "ext": {
            "max_payload_kg": 1000,
            "lifting_height_mm": 60,
            "max_speed_ms": 1.5,
            "navigation_type": QR,
            "battery_type": LI_ION,
            "min_aisle_width_mm": 1897,
        },
    },
    {
        "name": "STILL ACH 15 iGo",
        "agv_type": "Mobile AMR",
        "ext": {
            "max_payload_kg": 1500,
            "lifting_height_mm": 60,
            "max_speed_ms": 1.5,
            "navigation_type": QR,
            "battery_type": LI_ION,
            "min_aisle_width_mm": 1897,
        },
    },
    {
        "name": "STILL AXH 10 iGo",
        "agv_type": "Mobile AMR",
        "ext": {
            "max_payload_kg": 1000,
            "lifting_height_mm": 40,
            "max_speed_ms": 2.2,
            "navigation_type": SLAM,
            "battery_type": LI_ION,
            "min_aisle_width_mm": 2948,
        },
    },
    {
        "name": "KNAPP Open Shuttle 100",
        "agv_type": "Mobile AMR",
        "ext": {
            "max_payload_kg": 120,
            "max_speed_ms": 1.5,
            "navigation_type": SLAM,
            "battery_type": LIFEPO4,
            "vda5050_compatible": True,
        },
    },
    {
        "name": "KNAPP Open Shuttle Boxgrip",
        "agv_type": "Mobile AMR",
        "ext": {
            "max_payload_kg": 25,
            "max_speed_ms": 1.5,
            "navigation_type": SLAM,
            "battery_type": LIFEPO4,
            "vda5050_compatible": True,
        },
    },
    {
        "name": "KNAPP Open Shuttle 50 ASG",
        "agv_type": "Mobile AMR",
        "ext": {
            "max_payload_kg": 50,
            "max_speed_ms": 1.5,
            "navigation_type": SLAM,
            "battery_type": LIFEPO4,
            "vda5050_compatible": True,
        },
    },
    {
        "name": "Grenzebach L600",
        "agv_type": "Mobile AMR",
        "ext": {
            "max_payload_kg": 600,
            "lifting_height_mm": 60,
            "max_speed_ms": 1.5,
            "navigation_type": QR,
            "battery_type": LIFEPO4,
        },
    },
]


# ---------------------------------------------------------------------------
# Part 2: Corrections to existing records
# ---------------------------------------------------------------------------

def apply_corrections():
    """5 manual corrections to existing Airtable records."""

    # ---- Helper: find product record by product_name ----
    def find_product(name):
        url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES['products']}"
        r = requests.get(url, headers=HEADERS,
                         params={"filterByFormula": f'{{product_name}}="{name}"', "maxRecords": 1},
                         timeout=30)
        r.raise_for_status()
        recs = r.json().get("records", [])
        return recs[0] if recs else None

    def find_extension_for_bm(bm_id):
        url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES['extensions']}"
        r = requests.get(url, headers=HEADERS,
                         params={"filterByFormula": f'FIND("{bm_id}", ARRAYJOIN({{base_model_id}}))', "maxRecords": 1},
                         timeout=30)
        r.raise_for_status()
        recs = r.json().get("records", [])
        return recs[0] if recs else None

    corrections = [
        # 1. MLR Mayesto: Mobile AMR → Forklift AGV
        {
            "product_name": "MLR Mayesto",
            "product_fields": {"agv_type": "Forklift AGV"},
            "ext_fields": {
                "agv_type": "Forklift AGV",
                "max_payload_kg": 1500,
                "lifting_height_mm": 11000,
                "max_speed_ms": 2.7,
                "navigation_type": ["Magnetic Tape"],
                "stacking_capability": True,
            },
            "label": "MLR Mayesto: Mobile AMR → Forklift AGV (high-rack stacker, 11m lift)",
        },
        # 2. VisionNav VNE20: payload 1500 → 2000 kg
        {
            "product_name": "VisionNav VNE20",
            "product_fields": {},
            "ext_fields": {"max_payload_kg": 2000},
            "label": "VisionNav VNE20: payload 1500 → 2000 kg (OEM website 2026-06-29)",
        },
        # 3. Grenzebach FF1200S: navigation_type → Inductive Loop
        {
            "product_name": "Grenzebach FF1200S",
            "product_fields": {},
            "ext_fields": {"navigation_type": ["Inductive Loop"]},
            "label": "Grenzebach FF1200S: navigation_type → Inductive Loop (per OEM datasheet)",
        },
        # 4. E80 Trilateral LGV: vna_capable = True
        {
            "product_name": "E80 Trilateral LGV",
            "product_fields": {},
            "ext_fields": {"vna_capable": True},
            "label": "E80 Trilateral LGV: vna_capable = True (VNA turret forklift)",
        },
        # 5a. KIVNON K03 Twister: deactivate (absent from current site)
        {
            "product_name": "KIVNON K03 Twister",
            "product_fields": {"active": False},
            "ext_fields": {},
            "label": "KIVNON K03 Twister: deactivate (absent from current kivnon.com — likely discontinued)",
        },
        # 5b. KIVNON K41 Platform: deactivate
        {
            "product_name": "KIVNON K41 Platform",
            "product_fields": {"active": False},
            "ext_fields": {},
            "label": "KIVNON K41 Platform: deactivate (absent from current kivnon.com — likely discontinued)",
        },
    ]

    print("\n" + "="*60)
    print("PART 2: Applying corrections to existing records")
    print("="*60)

    for corr in corrections:
        print(f"\n  → {corr['label']}")
        prod_rec = find_product(corr["product_name"])
        if not prod_rec:
            print(f"    ✗ Product not found: {corr['product_name']}")
            continue
        prod_id = prod_rec["id"]
        bm_ids  = prod_rec["fields"].get("base_model_id", [])

        # Update product fields
        if corr["product_fields"]:
            try:
                patch_record("products", prod_id, corr["product_fields"])
                print(f"    ✓ Product updated: {corr['product_fields']}")
                time.sleep(0.3)
            except Exception as e:
                print(f"    ✗ Product update failed: {e}")

        # Update extension fields
        if corr["ext_fields"] and bm_ids:
            ext_rec = find_extension_for_bm(bm_ids[0])
            if ext_rec:
                try:
                    patch_record("extensions", ext_rec["id"], corr["ext_fields"])
                    print(f"    ✓ Extension updated: {corr['ext_fields']}")
                    time.sleep(0.3)
                except Exception as e:
                    print(f"    ✗ Extension update failed: {e}")
            else:
                print(f"    ⚠ No extension found for base_model {bm_ids[0]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    created = 0
    errors  = []

    print("PART 1: Creating missing extensions (18 records)")
    print("="*60)

    for item in MISSING_EXTENSIONS:
        name  = item["name"]
        atype = item["agv_type"]
        print(f"\n→ {name}")

        bm_rec = find_base_model_by_name(name)
        if not bm_rec:
            print(f"  ✗ Base model not found: {name}")
            errors.append((name, "base_model not found"))
            continue
        time.sleep(0.2)

        try:
            ext = item["ext"]
            ext_fields = {
                "model_name": name,
                "agv_type": atype,
                "base_model_id": [bm_rec],
                "extension_id": str(uuid.uuid4()),
            }
            ext_fields.update(ext)
            ext_id = post_record("extensions", ext_fields)
            print(f"  ✓ ext={ext_id[:8]}…")
            created += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  ✗ extension FAILED: {e}")
            errors.append((name, str(e)))

    print(f"\nExtensions created: {created}/18")
    if errors:
        print("Errors:", errors)

    apply_corrections()

    print("\n" + "="*60)
    print("Done. Next: python3 sync_airtable.py")


if __name__ == "__main__":
    run()
