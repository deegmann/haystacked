#!/usr/bin/env python3
"""
Import 9 new suppliers + ~25 products from Session D research findings.
Creates Company → Base Model → Product → Extension records in Airtable.

Run: python3 scripts/import_suppliers_20260626.py
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


# ---------------------------------------------------------------------------
# Supplier data  (company → list of products)
# Each product: {name, agv_type, description?, ext: {spec fields}}
# ---------------------------------------------------------------------------

SUPPLIERS = [
    {
        "company": {
            "company_name": "Oceaneering Mobile Robotics",
            "website": "https://www.oceaneering.com/mobile-robotics",
        },
        "products": [
            {
                "name": "MaxMover CB D2000",
                "agv_type": "Forklift AGV",
                "source_notes": "oceaneering.com MaxMover CB D 2000 product page. Counterbalance forklift AGV, 2000kg / 4400lb, lift 5000mm, 2.0 m/s, natural-feature nav.",
                "ext": {
                    "max_payload_kg": 2000,
                    "lifting_height_mm": 5000,
                    "max_speed_ms": 2.0,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "stacking_capability": True,
                    "vna_capable": False,
                    "source_notes": "OEM page oceaneering.com/mobile-robotics — HIGH confidence. CB forklift, NOT VNA.",
                },
            },
            {
                "name": "UniMover O 600",
                "agv_type": "Mobile AMR",
                "source_notes": "oceaneering.com UniMover O 600. Underride AMR, 600kg / 1322lb, natural-feature nav.",
                "ext": {
                    "max_payload_kg": 600,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "source_notes": "OEM page oceaneering.com — HIGH confidence.",
                },
            },
            {
                "name": "UniMover U 1500",
                "agv_type": "Mobile AMR",
                "source_notes": "oceaneering.com UniMover U 1500. Underride AMR, 1500kg, natural-feature nav.",
                "ext": {
                    "max_payload_kg": 1500,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "source_notes": "OEM page oceaneering.com — HIGH confidence.",
                },
            },
        ],
    },
    {
        "company": {
            "company_name": "VisionNav Robotics",
            "country": "CN",
            "website": "https://www.visionnav.com",
        },
        "products": [
            {
                "name": "VisionNav VNP15",
                "agv_type": "Forklift AGV",
                "source_notes": "visionnav.com VNP15 product page. Pallet stacker AGV, 1500kg, lift 3000mm std (opt 4500mm), 3D SLAM nav.",
                "ext": {
                    "max_payload_kg": 1500,
                    "lifting_height_mm": 3000,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "stacking_capability": True,
                    "vna_capable": False,
                    "source_notes": "OEM visionnav.com VNP15 — HIGH confidence. Lift 3000mm standard, opt up to 4500mm.",
                },
            },
            {
                "name": "VisionNav VNP20",
                "agv_type": "Forklift AGV",
                "source_notes": "visionnav.com VNP20. Pallet stacker, 1900kg, 3D SLAM.",
                "ext": {
                    "max_payload_kg": 1900,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "stacking_capability": True,
                    "vna_capable": False,
                    "source_notes": "OEM visionnav.com VNP20 — HIGH confidence. Lift height variant-dependent; NULL until confirmed.",
                },
            },
            {
                "name": "VisionNav VNE20",
                "agv_type": "Forklift AGV",
                "source_notes": "visionnav.com VNE20. Counterbalance/reach truck AGV, 1500kg, lift 3000mm, aisle 3760mm (PM-verified). 3D SLAM.",
                "ext": {
                    "max_payload_kg": 1500,
                    "lifting_height_mm": 3000,
                    "min_aisle_width_mm": 3760,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "stacking_capability": True,
                    "vna_capable": False,
                    "source_notes": "OEM visionnav.com VNE20 — HIGH confidence. Aisle 3760mm PM-verified (standard aisle, NOT VNA). Lift 3000mm std.",
                },
            },
        ],
    },
    {
        "company": {
            "company_name": "OTTO Motors (Rockwell Automation)",
            "country": "US",
            "website": "https://ottomotors.com",
        },
        "products": [
            {
                "name": "OTTO 100",
                "agv_type": "Mobile AMR",
                "source_notes": "ottomotors.com OTTO 100. Compact underride AMR, 150kg payload (model number ≠ payload), 2.0 m/s.",
                "ext": {
                    "max_payload_kg": 150,
                    "max_speed_ms": 2.0,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "source_notes": "OEM ottomotors.com — HIGH confidence. WARNING: model '100' = 150kg payload (not 100kg).",
                },
            },
            {
                "name": "OTTO 600",
                "agv_type": "Mobile AMR",
                "source_notes": "ottomotors.com OTTO 600. Underride AMR, 600kg, 1.4 m/s.",
                "ext": {
                    "max_payload_kg": 600,
                    "max_speed_ms": 1.4,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "source_notes": "OEM ottomotors.com — HIGH confidence.",
                },
            },
            {
                "name": "OTTO 1200",
                "agv_type": "Mobile AMR",
                "source_notes": "ottomotors.com OTTO 1200. Heavy-duty tight-space AMR, 1200kg.",
                "ext": {
                    "max_payload_kg": 1200,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "source_notes": "OEM ottomotors.com — HIGH confidence.",
                },
            },
            {
                "name": "OTTO 1500",
                "agv_type": "Mobile AMR",
                "source_notes": "ottomotors.com OTTO 1500. Large underride AMR. IMPORTANT: actual payload 1900kg (model '1500' ≠ payload). 2.0 m/s.",
                "ext": {
                    "max_payload_kg": 1900,
                    "max_speed_ms": 2.0,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "source_notes": "OEM ottomotors.com — HIGH confidence. WARNING: 'OTTO 1500' = 1900kg actual payload. Model number is NOT the payload.",
                },
            },
        ],
    },
    {
        "company": {
            "company_name": "KNAPP AG",
            "country": "AT",
            "website": "https://www.knapp.com",
        },
        "products": [
            {
                "name": "Open Shuttle Fork",
                "agv_type": "Forklift AGV",
                "source_notes": "knapp.com Open Shuttle Fork. AMR pallet forklift, 1300kg, lift 0–1200mm, natural-feature SLAM.",
                "ext": {
                    "max_payload_kg": 1300,
                    "lifting_height_mm": 1200,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "stacking_capability": True,
                    "vna_capable": False,
                    "source_notes": "OEM knapp.com Open Shuttle Fork — HIGH confidence. Low-mid lift (0-1200mm), pallet transport AMR.",
                },
            },
            {
                "name": "Open Shuttle",
                "agv_type": "Mobile AMR",
                "source_notes": "knapp.com Open Shuttle container/tote transport AMR. 120kg payload, natural-feature SLAM.",
                "ext": {
                    "max_payload_kg": 120,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "source_notes": "OEM knapp.com — MEDIUM confidence (search snippet). Tote/container transport, not pallet.",
                },
            },
        ],
    },
    {
        "company": {
            "company_name": "GreyOrange",
            "country": "US",
            "website": "https://www.greyorange.com",
        },
        "products": [
            {
                "name": "GreyOrange Ranger Forklift (RF-AP)",
                "agv_type": "Forklift AGV",
                "source_notes": "greyorange.com RF-AP (Ranger Forklift AnyPallet). Forklift AMR, 2000kg, 1.7 m/s, 2D LiDAR SLAM.",
                "ext": {
                    "max_payload_kg": 2000,
                    "max_speed_ms": 1.7,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "stacking_capability": True,
                    "vna_capable": False,
                    "source_notes": "greyorange.com / mobile-robots.com directory — HIGH confidence. Lift height not published (NULL).",
                },
            },
            {
                "name": "GreyOrange Ranger RIL-H",
                "agv_type": "Mobile AMR",
                "source_notes": "greyorange.com Ranger Intralogistics-H (RIL-H). Tall underride AMR, 1400kg, 1.5 m/s.",
                "ext": {
                    "max_payload_kg": 1400,
                    "max_speed_ms": 1.5,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "source_notes": "greyorange.com / mobile-robots.com — HIGH confidence.",
                },
            },
            {
                "name": "GreyOrange Ranger RU-L",
                "agv_type": "Mobile AMR",
                "source_notes": "greyorange.com Ranger Uplift-L (RU-L). Underride lift AMR, 1000kg, 2.0 m/s.",
                "ext": {
                    "max_payload_kg": 1000,
                    "max_speed_ms": 2.0,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "source_notes": "greyorange.com / mobile-robots.com — HIGH confidence.",
                },
            },
        ],
    },
    {
        "company": {
            "company_name": "SAFELOG GmbH",
            "country": "DE",
            "website": "https://www.safelog.de",
        },
        "products": [
            {
                "name": "SAFELOG AGV L1",
                "agv_type": "Mobile AMR",
                "source_notes": "safelog.de AGV L1. Underride/tugger AMR, 1500kg carry / 3000kg tow, LiDAR SLAM. MEDIUM confidence (aggregator specs).",
                "ext": {
                    "max_payload_kg": 1500,
                    "towing_capacity_kg": 3000,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "source_notes": "qviro/directindustry aggregator — MEDIUM confidence. OEM datasheet not directly accessed.",
                },
            },
            {
                "name": "SAFELOG AGV M4",
                "agv_type": "Tugger AGV",
                "source_notes": "safelog.de AGV M4. Handling/tugger AGV, 200kg own payload, 1500kg towing, 1.6 m/s. MEDIUM.",
                "ext": {
                    "max_payload_kg": 200,
                    "towing_capacity_kg": 1500,
                    "max_speed_ms": 1.6,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "source_notes": "qviro/directindustry — MEDIUM confidence. Hybrid nav (contour+magnetic+camera+odometry); simplified as SLAM.",
                },
            },
            {
                "name": "SAFELOG AGV S3",
                "agv_type": "Mobile AMR",
                "source_notes": "safelog.de AGV S3. Light underride AMR, 150kg, LiDAR SLAM. MEDIUM.",
                "ext": {
                    "max_payload_kg": 150,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "source_notes": "qviro aggregator — MEDIUM confidence.",
                },
            },
            {
                "name": "SAFELOG AGV X1",
                "agv_type": "Mobile AMR",
                "source_notes": "safelog.de AGV X1. Low-lift underride AMR, 1200kg, lift 80mm (under-pallet only), LiDAR SLAM. MEDIUM.",
                "ext": {
                    "max_payload_kg": 1200,
                    "lifting_height_mm": 80,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "source_notes": "search snippet — MEDIUM confidence. Lift 80mm = under-pallet jack only, not a stacking forklift.",
                },
            },
        ],
    },
    {
        "company": {
            "company_name": "SEW-EURODRIVE",
            "country": "DE",
            "website": "https://www.sew-eurodrive.com",
        },
        "products": [
            {
                "name": "MAXOLUTION TV015",
                "agv_type": "Mobile AMR",
                "source_notes": "sew-eurodrive.at MAXOLUTION Mobile Assistance Systems TV015. Transport vehicle, 1500kg. Configurable nav (tape/inductive/SLAM). MEDIUM-HIGH.",
                "ext": {
                    "max_payload_kg": 1500,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "source_notes": "OEM sew-eurodrive.at page — MEDIUM-HIGH confidence. Nav configurable per site (tape/inductive/SLAM); recorded as SLAM for free-nav deployments.",
                },
            },
            {
                "name": "MAXOLUTION LA015",
                "agv_type": "Mobile AMR",
                "source_notes": "sew-eurodrive.at MAXOLUTION LA015. Logistics assistant, 1500kg. Configurable nav. MEDIUM-HIGH.",
                "ext": {
                    "max_payload_kg": 1500,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "source_notes": "OEM sew-eurodrive.at — MEDIUM-HIGH confidence.",
                },
            },
        ],
    },
    {
        "company": {
            "company_name": "Stäubli",
            "website": "https://www.staubli.com",
        },
        "products": [
            {
                "name": "Stäubli FL1500",
                "agv_type": "Forklift AGV",
                "source_notes": "staubli.com FL1500 automated counterbalance forklift, 1500kg. Lift/speed: datasheet 403-blocked. MEDIUM.",
                "ext": {
                    "max_payload_kg": 1500,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "stacking_capability": True,
                    "vna_capable": False,
                    "source_notes": "OEM product page name 'FL1500 (1.5t)' — MEDIUM confidence. Datasheet PDF 403-blocked; lift height/speed NULL until manually verified.",
                },
            },
        ],
    },
    {
        "company": {
            "company_name": "MLR System GmbH",
            "country": "DE",
            "website": "https://www.mlr.de",
        },
        "products": [
            {
                "name": "MLR Mayesto",
                "agv_type": "Mobile AMR",
                "source_notes": "mlr.de / mobile-robots.com directory. Transport AGV, 1500kg, 2.7 m/s. MEDIUM confidence (directory source).",
                "ext": {
                    "max_payload_kg": 1500,
                    "max_speed_ms": 2.7,
                    "navigation_type": ["Natural Feature (SLAM)"],
                    "source_notes": "mobile-robots.com directory — MEDIUM confidence. Speed 2.7 m/s is high (automated zone). OEM datasheet not directly accessed.",
                },
            },
        ],
    },
]


# ---------------------------------------------------------------------------
# Airtable helpers
# ---------------------------------------------------------------------------

def post_record(table_name: str, fields: dict) -> str:
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES[table_name]}"
    r = requests.post(url, headers=HEADERS, json={"fields": fields}, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def run_import():
    created = {"companies": 0, "base_models": 0, "products": 0, "extensions": 0}
    errors = []

    for supplier in SUPPLIERS:
        co = supplier["company"]
        print(f"\n=== {co['company_name']} ===")

        # 1. Create company
        try:
            co_fields = {"company_name": co["company_name"]}
            if co.get("country"):
                co_fields["country"] = co["country"]
            if co.get("website"):
                co_fields["website"] = co["website"]
            co_rec = post_record("companies", co_fields)
            created["companies"] += 1
            print(f"  ✓ Company: {co_rec}")
            time.sleep(0.25)
        except Exception as e:
            print(f"  ✗ Company FAILED: {e}")
            errors.append((co["company_name"], "company", str(e)))
            continue

        for prod in supplier["products"]:
            print(f"  → {prod['name']} ({prod['agv_type']})")

            # 2. Create base_model
            try:
                bm_fields = {
                    "base_model_name": prod["name"],
                    "agv_type": prod["agv_type"],
                    "base_model_id": str(uuid.uuid4()),
                }
                bm_rec = post_record("base_models", bm_fields)
                created["base_models"] += 1
                time.sleep(0.25)
            except Exception as e:
                print(f"    ✗ Base model FAILED: {e}")
                errors.append((prod["name"], "base_model", str(e)))
                continue

            # 3. Create product
            try:
                pr_fields = {
                    "product_name": prod["name"],
                    "agv_type": prod["agv_type"],
                    "active": True,
                    "company_id": [co_rec],
                    "base_model_id": [bm_rec],
                    "product_id": str(uuid.uuid4()),
                    "source_notes": prod.get("source_notes", ""),
                    "service_coverage": ["EU"],
                }
                pr_rec = post_record("products", pr_fields)
                created["products"] += 1
                time.sleep(0.25)
            except Exception as e:
                print(f"    ✗ Product FAILED: {e}")
                errors.append((prod["name"], "product", str(e)))
                continue

            # 4. Create extension
            try:
                ext = prod.get("ext", {})
                ext_fields = {
                    "model_name": prod["name"],
                    "agv_type": prod["agv_type"],
                    "base_model_id": [bm_rec],
                    "extension_id": str(uuid.uuid4()),
                }
                ext_fields.update(ext)
                ext_rec = post_record("extensions", ext_fields)
                created["extensions"] += 1
                print(f"    ✓ Created (co={co_rec[:8]}… bm={bm_rec[:8]}… ext={ext_rec[:8]}…)")
                time.sleep(0.25)
            except Exception as e:
                print(f"    ✗ Extension FAILED: {e}")
                errors.append((prod["name"], "extension", str(e)))

    print(f"\n{'='*50}")
    print(f"Created: {created}")
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for name, stage, msg in errors:
            print(f"  [{stage}] {name}: {msg}")
    else:
        print("No errors.")
    print("\nNext: python3 sync_airtable.py")


if __name__ == "__main__":
    run_import()
