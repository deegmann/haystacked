#!/usr/bin/env python3
"""
Import ~84 missing products across all 27 existing suppliers.
Research session: 2026-06-29. 8 parallel agv-spec-researcher agents.

Companies already exist — script only creates: Base Model → Product → Extension.
Run:  python3 scripts/import_products_20260629.py
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
# Existing company Airtable record IDs  (do NOT create new company records)
# ---------------------------------------------------------------------------
CO = {
    "AGILOX":       "reczVbLhhjMOYTRDU",
    "BA_SYSTEMES":  "recqURrzWQCNcvx5y",
    "BALYO":        "recpyJUHIF3IrIj3I",
    "DS_AUTOMOTION":"recjVkDGpP36pQokQ",
    "E80":          "rec4U8V9R8zqmsUXE",
    "EK_ROBOTICS":  "rec1ZqbEZI1N1xhER",
    "GEEKPLUS":     "recAt0MsnmNI40XJ6",
    "GRENZEBACH":   "reccYgYjiWKDCZrDt",
    "GREYORANGE":   "recjfvPS6rpvUpcKt",
    "HIKROBOT":     "rec8puMCz7RojpCwA",
    "IDEALWORKS":   "recOSC9xMrIEHZsnb",
    "JUNGHEINRICH": "recoAvZXd1iBbz0KJ",
    "KIVNON":       "rec7yndnVdYy5eTUb",
    "KNAPP":        "rec6rUDyeGz1KEUZR",
    "LINDE":        "rec8aaW4EIEDGlEe0",
    "MLR":          "reck9mB0hzWs4tHYB",
    "MIR":          "rec3kotWF4mpX7RTU",
    "MOVU":         "reczTC0zu3eDGWybk",
    "OCEANEERING":  "rec8blP7rKmtibWcx",
    "OMRON":        "receHK0TwbfKpgoWJ",
    "OTTO":         "recoyLjc5lkqQQtKL",
    "SAFELOG":      "recFnzzgpAvw62jDy",
    "SEW":          "recBp0jsgCvbubRbL",
    "STAUBLI":      "rec8FExjRRo6svtHS",
    "STILL":        "recOxIAGR6tkmh8Sc",
    "TOYOTA":       "recxPqJCeWxlTqf4V",
    "VISIONNAV":    "recukyJanezH7UdIk",
}

# ---------------------------------------------------------------------------
# New products list
# Format: {company_key, name, product_type, is_oem_product, source_notes, ext:{}}
# ---------------------------------------------------------------------------
SLAM     = ["Natural Feature (SLAM)"]
QR       = ["QR/DM Code"]
REFLECTOR = ["Laser Reflector"]
REFLECTOR_SLAM = ["Laser Reflector", "Natural Feature (SLAM)"]

NEW_PRODUCTS = [

    # =========================================================================
    # VISIONNAV ROBOTICS — 13 new models
    # Source: visionnav.com/product/ + Model Comparison page
    # All use 3D SLAM + 3D laser environmental perception
    # None are VNA (true turret truck). Narrowest aisle: VNSL14 @ 2250mm.
    # =========================================================================
    {
        "company_key": "VISIONNAV",
        "name": "VisionNav VNP30",
        "product_type": "Forklift AGV",
        "source_notes": "visionnav.com VNP30. Counterbalance stacker AGV, 3000kg, lift 3000mm std (opt 4500mm), aisle 3992mm, 1.5 m/s. HIGH confidence.",
        "ext": {
            "max_payload_kg": 3000,
            "lifting_height_mm": 3000,
            "min_aisle_width_mm": 3992,
            "max_speed_ms": 1.5,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "VISIONNAV",
        "name": "VisionNav VNR16",
        "product_type": "Forklift AGV",
        "source_notes": "visionnav.com VNR16. Reach truck AGV, 1600kg, lift 5500mm std (opt 11200mm), aisle 3250mm, 2.0 m/s. HIGH confidence.",
        "ext": {
            "max_payload_kg": 1600,
            "lifting_height_mm": 5500,
            "min_aisle_width_mm": 3250,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "VISIONNAV",
        "name": "VisionNav VNR20",
        "product_type": "Forklift AGV",
        "source_notes": "visionnav.com VNR20. Reach truck AGV, 2000kg, lift 7000mm std (opt 11200mm), aisle 3300mm, 2.0 m/s. HIGH confidence.",
        "ext": {
            "max_payload_kg": 2000,
            "lifting_height_mm": 7000,
            "min_aisle_width_mm": 3300,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "VISIONNAV",
        "name": "VisionNav VNE30",
        "product_type": "Forklift AGV",
        "source_notes": "visionnav.com VNE30. Counterbalance truck AGV, 3000kg, lift 3000mm std (opt 4500mm), aisle 4430mm, 2.2 m/s. HIGH confidence.",
        "ext": {
            "max_payload_kg": 3000,
            "lifting_height_mm": 3000,
            "min_aisle_width_mm": 4430,
            "max_speed_ms": 2.2,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "VISIONNAV",
        "name": "VisionNav VNE35",
        "product_type": "Forklift AGV",
        "source_notes": "visionnav.com VNE35. Counterbalance truck AGV, 3500kg, lift 3000mm std (opt 4500mm), aisle 4430mm, 2.2 m/s. HIGH confidence.",
        "ext": {
            "max_payload_kg": 3500,
            "lifting_height_mm": 3000,
            "min_aisle_width_mm": 4430,
            "max_speed_ms": 2.2,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "VISIONNAV",
        "name": "VisionNav VNE40",
        "product_type": "Forklift AGV",
        "source_notes": "visionnav.com VNE40. Counterbalance truck AGV, 4000kg, lift 3000mm std (opt 4500mm), aisle 4430mm, 2.2 m/s. HIGH confidence.",
        "ext": {
            "max_payload_kg": 4000,
            "lifting_height_mm": 3000,
            "min_aisle_width_mm": 4430,
            "max_speed_ms": 2.2,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "VISIONNAV",
        "name": "VisionNav VNSL14",
        "product_type": "Forklift AGV",
        "source_notes": "visionnav.com VNSL14. Slim pallet stacker AGV, 1400kg, lift 1600mm (opt 3000mm), aisle 2250mm, 1.3 m/s. NOT VNA despite narrow aisle — slim low-lift stacker. HIGH confidence.",
        "ext": {
            "max_payload_kg": 1400,
            "lifting_height_mm": 1600,
            "min_aisle_width_mm": 2250,
            "max_speed_ms": 1.3,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "VISIONNAV",
        "name": "VisionNav VNST20",
        "product_type": "Forklift AGV",
        "source_notes": "visionnav.com VNST20. Slim pallet stacker AGV (low-lift), 2000kg, lift 115mm (jacking only, not racking), aisle 2250mm, 1.8 m/s. HIGH confidence. Lift is jacking stroke, not mast height.",
        "ext": {
            "max_payload_kg": 2000,
            "lifting_height_mm": 115,
            "min_aisle_width_mm": 2250,
            "max_speed_ms": 1.8,
            "navigation_type": SLAM,
            "stacking_capability": False,
            "vna_capable": False,
        },
    },
    {
        "company_key": "VISIONNAV",
        "name": "VisionNav VNST20-SINGLE",
        "product_type": "Forklift AGV",
        "source_notes": "visionnav.com VNST20-SINGLE. Single-pallet slim stacker AGV (low-lift), 1000kg, lift 100mm (jacking), aisle 2090mm, 1.8 m/s. HIGH confidence.",
        "ext": {
            "max_payload_kg": 1000,
            "lifting_height_mm": 100,
            "min_aisle_width_mm": 2090,
            "max_speed_ms": 1.8,
            "navigation_type": SLAM,
            "stacking_capability": False,
            "vna_capable": False,
        },
    },
    {
        "company_key": "VISIONNAV",
        "name": "VisionNav VNT30-01",
        "product_type": "Forklift AGV",
        "source_notes": "visionnav.com VNT30-01. Pallet jack AGV (low-lift), 3000kg, lift 125mm (jacking only), aisle 2600mm, 1.6 m/s. HIGH confidence. Floor-level pallet transport, no racking.",
        "ext": {
            "max_payload_kg": 3000,
            "lifting_height_mm": 125,
            "min_aisle_width_mm": 2600,
            "max_speed_ms": 1.6,
            "navigation_type": SLAM,
            "stacking_capability": False,
            "vna_capable": False,
        },
    },
    {
        "company_key": "VISIONNAV",
        "name": "VisionNav VNQ50",
        "product_type": "Tugger AGV",
        "source_notes": "visionnav.com VNQ50. Autonomous tow tractor, on-platform load 5000kg, towing ~19958kg (train), min aisle 1700mm, 2.0 m/s, 3D SLAM explicit. HIGH confidence. Field towing_capacity_kg = train tow rating.",
        "ext": {
            "max_payload_kg": 5000,
            "towing_capacity_kg": 19958,
            "tugger_min_aisle_width_mm": 1700,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
            "vna_capable": False,
        },
    },
    {
        "company_key": "VISIONNAV",
        "name": "VisionNav VNK15",
        "product_type": "Mobile AMR",
        "source_notes": "visionnav.com VNK15. Platform/AGF robot (top-lift jacking), 1500kg, lift 60mm (jacking stroke only), 1.8 m/s. Cold/ultra-low-temp capable. HIGH confidence.",
        "ext": {
            "max_payload_kg": 1500,
            "lifting_height_mm": 60,
            "max_speed_ms": 1.8,
            "navigation_type": SLAM,
        },
    },
    {
        "company_key": "VISIONNAV",
        "name": "VisionNav VNKQ20",
        "product_type": "Mobile AMR",
        "source_notes": "visionnav.com VNKQ20 'Autonomous Mouse'. Slim under-load AMR, 2000kg, ~1.5 m/s (3.36 mph). Designed for narrow lanes. HIGH payload confidence, speed MEDIUM.",
        "ext": {
            "max_payload_kg": 2000,
            "max_speed_ms": 1.5,
            "navigation_type": SLAM,
        },
    },

    # =========================================================================
    # LINDE MATERIAL HANDLING — 8 new models
    # All Balyo-based ("Driven by Balyo") except C-MATIC (not Balyo).
    # is_oem_product = True (Linde = rebrander, Balyo = manufacturer)
    # =========================================================================
    {
        "company_key": "LINDE",
        "name": "Linde L-MATIC",
        "product_type": "Forklift AGV",
        "is_oem_product": True,
        "source_notes": "linde-mh.com L-MATIC. Pallet stacker AGV, 1600kg, lift 2900mm, natural-feature SLAM. OEM: Balyo LOWY. HIGH confidence.",
        "ext": {
            "max_payload_kg": 1600,
            "lifting_height_mm": 2900,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "LINDE",
        "name": "Linde L-MATIC core",
        "product_type": "Forklift AGV",
        "is_oem_product": True,
        "source_notes": "linde-mh.com L-MATIC core. Entry pallet stacker AGV, ~1600kg (family), SLAM. OEM: Balyo LOWY. MEDIUM confidence — payload inferred from LOWY family.",
        "ext": {
            "max_payload_kg": 1600,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "LINDE",
        "name": "Linde L-MATIC HD k",
        "product_type": "Forklift AGV",
        "is_oem_product": True,
        "source_notes": "linde-mh.com L-MATIC HD k. Heavy-duty pallet stacker AGV, 1600kg, lift 3000mm (Balyo)/3800mm (Linde page conflict — use 3000mm), SLAM. OEM: Balyo LOWY HD. MEDIUM confidence on lift height.",
        "ext": {
            "max_payload_kg": 1600,
            "lifting_height_mm": 3000,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "LINDE",
        "name": "Linde L-MATIC AC",
        "product_type": "Forklift AGV",
        "is_oem_product": True,
        "source_notes": "linde-mh.com L-MATIC AC. Counterbalanced pallet stacker AGV, ~1600kg, lift 4200mm, aisle ~3400mm, SLAM. OEM: Balyo LOWY CB. MEDIUM confidence on payload.",
        "ext": {
            "max_payload_kg": 1600,
            "lifting_height_mm": 4200,
            "min_aisle_width_mm": 3400,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "LINDE",
        "name": "Linde L-MATIC AC k",
        "product_type": "Forklift AGV",
        "is_oem_product": True,
        "source_notes": "linde-mh.com L-MATIC AC k. Counterbalanced pallet stacker AGV, 1400kg, lift 3800mm, aisle ~3400mm, SLAM. OEM: Balyo LOWY CB. HIGH confidence.",
        "ext": {
            "max_payload_kg": 1400,
            "lifting_height_mm": 3800,
            "min_aisle_width_mm": 3400,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "LINDE",
        "name": "Linde R-MATIC",
        "product_type": "Forklift AGV",
        "is_oem_product": True,
        "source_notes": "linde-mh.com R-MATIC. Reach truck AGV, 1600kg, lift 11000mm, aisle 2900mm, ~1.95 m/s, SLAM + 3D camera. OEM: Balyo REACHY. HIGH confidence. NOT VNA (2.9m aisle).",
        "ext": {
            "max_payload_kg": 1600,
            "lifting_height_mm": 11000,
            "min_aisle_width_mm": 2900,
            "max_speed_ms": 1.95,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "LINDE",
        "name": "Linde K-MATIC",
        "product_type": "Forklift AGV",
        "is_oem_product": True,
        "source_notes": "linde-mh.com K-MATIC. VNA turret truck AGV, 1450kg, lift 14000mm (16000 on request), aisle 1800mm, ~2.0 m/s, SLAM. OEM: Balyo VEENY. HIGH confidence. vna_capable=TRUE — only VNA in Linde MATIC range.",
        "ext": {
            "max_payload_kg": 1450,
            "lifting_height_mm": 14000,
            "min_aisle_width_mm": 1800,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": True,
        },
    },
    {
        "company_key": "LINDE",
        "name": "Linde C-MATIC",
        "product_type": "Mobile AMR",
        "is_oem_product": False,
        "source_notes": "linde-mh.com C-MATIC. Underride transport AMR (NOT Balyo-based — uses QR-code/floor navigation). Available in 10 (1000kg) and 15 (1500kg) variants; 15 used. ~1.2 m/s, no mast/lift. HIGH confidence.",
        "ext": {
            "max_payload_kg": 1500,
            "max_speed_ms": 1.2,
            "navigation_type": QR,
            "stacking_capability": False,
            "vna_capable": False,
        },
    },

    # =========================================================================
    # BALYO — 1 new model
    # =========================================================================
    {
        "company_key": "BALYO",
        "name": "Balyo TRUCKY",
        "product_type": "Forklift AGV",
        "source_notes": "balyo.com TRUCKY. Robotic pallet truck/jack, 3000kg, lift 125mm (low-lift), ~2.0 m/s. Carries 2 pallets simultaneously. Based on Linde T30 (T-MATIC equivalent). HIGH confidence on payload; speed MEDIUM.",
        "ext": {
            "max_payload_kg": 3000,
            "lifting_height_mm": 125,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
            "stacking_capability": False,
            "vna_capable": False,
        },
    },

    # =========================================================================
    # MOBILE INDUSTRIAL ROBOTS (MiR) — 4 legacy models (still sold via distributors)
    # =========================================================================
    {
        "company_key": "MIR",
        "name": "MiR100",
        "product_type": "Mobile AMR",
        "source_notes": "mobile-industrial-robots.com MiR100 (legacy). 100kg, 1.5 m/s, SLAM. Still sold through distributors. HIGH confidence.",
        "ext": {
            "max_payload_kg": 100,
            "max_speed_ms": 1.5,
            "navigation_type": SLAM,
            "autonomous_charging": True,
            "battery_type": "Li-Ion",
        },
    },
    {
        "company_key": "MIR",
        "name": "MiR200",
        "product_type": "Mobile AMR",
        "source_notes": "MiR200 (legacy successor to MiR100). 200kg, 1.5 m/s, SLAM. Present on regional MiR pages and distributor listings. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 200,
            "max_speed_ms": 1.5,
            "navigation_type": SLAM,
            "autonomous_charging": True,
            "battery_type": "Li-Ion",
        },
    },
    {
        "company_key": "MIR",
        "name": "MiR500",
        "product_type": "Mobile AMR",
        "source_notes": "mobile-industrial-robots.com MiR500 (legacy, predecessor to MiR600). 500kg, 2.0 m/s, SLAM, Li-Ion, IP52. HIGH confidence.",
        "ext": {
            "max_payload_kg": 500,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
            "autonomous_charging": True,
            "battery_type": "Li-Ion",
        },
    },
    {
        "company_key": "MIR",
        "name": "MiR1000",
        "product_type": "Mobile AMR",
        "source_notes": "MiR1000 (legacy, predecessor to MiR1350). 1000kg, 2.0 m/s, SLAM, Li-Ion. MEDIUM confidence — present on distributor listings.",
        "ext": {
            "max_payload_kg": 1000,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
            "autonomous_charging": True,
            "battery_type": "Li-Ion",
        },
    },

    # =========================================================================
    # OTTO MOTORS (Rockwell Automation) — 2 new models
    # =========================================================================
    {
        "company_key": "OTTO",
        "name": "OTTO 750",
        "product_type": "Mobile AMR",
        "source_notes": "ottomotors.com OTTO 750. Heavy underride AMR, 750kg, 2.0 m/s, 3×LiDAR + 3D camera SLAM, Li-Ion 51.2V. HIGH confidence (datasheet PDF verified).",
        "ext": {
            "max_payload_kg": 750,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
            "battery_type": "Li-Ion",
        },
    },
    {
        "company_key": "OTTO",
        "name": "OTTO Lifter",
        "product_type": "Forklift AGV",
        "source_notes": "ottomotors.com OTTO Lifter. Fork-equipped AGV, 1200kg, autonomous lift 760mm (manual mode 2.7m — use 760mm for KO matching), 1.5 m/s, SLAM. Lead-acid standard / Li-Ion option. HIGH confidence (datasheet verified). NOT VNA.",
        "ext": {
            "max_payload_kg": 1200,
            "lifting_height_mm": 760,
            "max_speed_ms": 1.5,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },

    # =========================================================================
    # OMRON MOBILE ROBOTICS — 3 new models (LD-90 already in DB)
    # =========================================================================
    {
        "company_key": "OMRON",
        "name": "Omron LD-130CT",
        "product_type": "Mobile AMR",
        "source_notes": "robotics.omron.com LD-130CT. Cart-transporter AMR, 130kg, 0.9 m/s, SLAM, lead-acid. LD platform (tows/pushes carts). HIGH confidence.",
        "ext": {
            "max_payload_kg": 130,
            "max_speed_ms": 0.9,
            "navigation_type": SLAM,
            "battery_type": "Lead-acid",
        },
    },
    {
        "company_key": "OMRON",
        "name": "Omron MD-650",
        "product_type": "Mobile AMR",
        "source_notes": "robotics.omron.com MD-650. New MD-series (2023+), medium-duty, 650kg, 2.2 m/s, SLAM, Li-Ion fast-charge (<30 min), 360° dual safety lasers, full reverse travel. HIGH confidence.",
        "ext": {
            "max_payload_kg": 650,
            "max_speed_ms": 2.2,
            "navigation_type": SLAM,
            "battery_type": "Li-Ion",
            "autonomous_charging": True,
        },
    },
    {
        "company_key": "OMRON",
        "name": "Omron MD-900",
        "product_type": "Mobile AMR",
        "source_notes": "robotics.omron.com MD-900. MD-series (2023+), 900kg, 1.8 m/s, SLAM, Li-Ion fast-charge. HIGH confidence.",
        "ext": {
            "max_payload_kg": 900,
            "max_speed_ms": 1.8,
            "navigation_type": SLAM,
            "battery_type": "Li-Ion",
            "autonomous_charging": True,
        },
    },

    # =========================================================================
    # JUNGHEINRICH AG — 1 new model
    # =========================================================================
    {
        "company_key": "JUNGHEINRICH",
        "name": "Jungheinrich ERE 225a",
        "product_type": "Forklift AGV",
        "source_notes": "jungheinrich.co.uk ERE 225a. Automated low-level / powered pallet truck, 2500kg, lift 125mm (low-lift only), 2.0 m/s, laser reflector nav, Li-Ion. HIGH confidence.",
        "ext": {
            "max_payload_kg": 2500,
            "lifting_height_mm": 125,
            "max_speed_ms": 2.0,
            "navigation_type": REFLECTOR,
            "battery_type": "Li-Ion",
            "stacking_capability": False,
            "vna_capable": False,
        },
    },

    # =========================================================================
    # STILL GmbH — 5 new models (ACH/AXH underride AMR series)
    # NOTE: iGo neo / easyPILOT excluded — operator-assist, not autonomous
    # =========================================================================
    {
        "company_key": "STILL",
        "name": "STILL ACH 06 iGo",
        "product_type": "Mobile AMR",
        "source_notes": "data.still.de VDI 2198 datasheet AXH/ACH. Underride AMR, 600kg, lift 55mm (jacking), 2.0 m/s unloaded/1.5 loaded, QR-code navigation, Li-Ion 48V. HIGH confidence (official datasheet).",
        "ext": {
            "max_payload_kg": 600,
            "lifting_height_mm": 55,
            "max_speed_ms": 2.0,
            "navigation_type": QR,
            "battery_type": "Li-Ion",
            "min_aisle_width_mm": 1473,
        },
    },
    {
        "company_key": "STILL",
        "name": "STILL ACH 10 iGo",
        "product_type": "Mobile AMR",
        "source_notes": "data.still.de VDI 2198 datasheet AXH/ACH. Underride AMR, 1000kg, lift 60mm (jacking), 1.5 m/s, QR-code navigation, Li-Ion 48V, aisle 1897mm. HIGH confidence.",
        "ext": {
            "max_payload_kg": 1000,
            "lifting_height_mm": 60,
            "max_speed_ms": 1.5,
            "navigation_type": QR,
            "battery_type": "Li-Ion",
            "min_aisle_width_mm": 1897,
        },
    },
    {
        "company_key": "STILL",
        "name": "STILL ACH 15 iGo",
        "product_type": "Mobile AMR",
        "source_notes": "data.still.de VDI 2198 datasheet AXH/ACH. Underride AMR, 1500kg, lift 60mm (jacking), 1.5 m/s, QR-code navigation, Li-Ion 48V, aisle 1897mm. HIGH confidence.",
        "ext": {
            "max_payload_kg": 1500,
            "lifting_height_mm": 60,
            "max_speed_ms": 1.5,
            "navigation_type": QR,
            "battery_type": "Li-Ion",
            "min_aisle_width_mm": 1897,
        },
    },
    {
        "company_key": "STILL",
        "name": "STILL AXH 10 iGo",
        "product_type": "Mobile AMR",
        "source_notes": "data.still.de VDI 2198 datasheet AXH/ACH. Underride AMR (SLAM variant), 1000kg, lift 40mm (jacking), 2.2 m/s, SLAM + 3D camera, Li-Ion 48V, aisle 2948mm. HIGH confidence.",
        "ext": {
            "max_payload_kg": 1000,
            "lifting_height_mm": 40,
            "max_speed_ms": 2.2,
            "navigation_type": SLAM,
            "battery_type": "Li-Ion",
            "min_aisle_width_mm": 2948,
        },
    },
    {
        "company_key": "STILL",
        "name": "STILL AXV 12 iGo",
        "product_type": "Forklift AGV",
        "source_notes": "still.de automated trucks page AXV 12 iGo. High-lift pallet truck AGV, ~1200kg (model-code inference), aisle ~2480mm. Specs incomplete — numeric KO fields should be verified before use in matching. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 1200,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },

    # =========================================================================
    # TOYOTA MATERIAL HANDLING EUROPE — 2 new models
    # =========================================================================
    {
        "company_key": "TOYOTA",
        "name": "Toyota OAE120CB Autopilot",
        "product_type": "Forklift AGV",
        "source_notes": "toyota-forklifts.eu OAE120CB spec sheet (PDF 749988-040 v5). Counterbalance order-picker/stacker AGV ('Optio'), 1200kg, lift 4150mm (Duplex Tele max), aisle 3132mm, 2.2 m/s, dual nav (reflector + natural feature), Li-Ion or lead-acid. HIGH confidence.",
        "ext": {
            "max_payload_kg": 1200,
            "lifting_height_mm": 4150,
            "min_aisle_width_mm": 3132,
            "max_speed_ms": 2.2,
            "navigation_type": REFLECTOR_SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "TOYOTA",
        "name": "Toyota RAE160 Autopilot",
        "product_type": "Forklift AGV",
        "source_notes": "toyota-forklifts.eu RAE160-250 range. Reach truck AGV, 1600kg, lift ~11000mm (range-level; not per-variant confirmed), 2.0 m/s, dual nav (reflector + natural feature), Li-Ion. HIGH confidence on type/payload/speed; lift MEDIUM.",
        "ext": {
            "max_payload_kg": 1600,
            "lifting_height_mm": 11000,
            "max_speed_ms": 2.0,
            "navigation_type": REFLECTOR_SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },

    # =========================================================================
    # AGILOX — 1 new model
    # =========================================================================
    {
        "company_key": "AGILOX",
        "name": "AGILOX NFK",
        "product_type": "Mobile AMR",
        "source_notes": "agilox.net datasheet_nfk. Narrow Fork omnidirectional fork AGV (ONE chassis + single fork), 1000kg, lift 620mm, 1.4 m/s, 1511×810×1862mm. HIGH confidence.",
        "ext": {
            "max_payload_kg": 1000,
            "lifting_height_mm": 620,
            "max_speed_ms": 1.4,
            "navigation_type": SLAM,
            "omnidirectional_movement": True,
        },
    },

    # =========================================================================
    # DS AUTOMOTION — 2 new models (assembly-line vehicles excluded per PM decision)
    # =========================================================================
    {
        "company_key": "DS_AUTOMOTION",
        "name": "DS Automotion AMY",
        "product_type": "Mobile AMR",
        "source_notes": "ds-automotion.com AMY. Compact small-load carrier AMR, 25kg, 1.8 m/s, 638×428×349mm. Dynamic load-transfer, no mast. HIGH confidence.",
        "ext": {
            "max_payload_kg": 25,
            "max_speed_ms": 1.8,
            "navigation_type": SLAM,
        },
    },
    {
        "company_key": "DS_AUTOMOTION",
        "name": "DS Automotion FLEXIHAULER",
        "product_type": "Tugger AGV",
        "source_notes": "ds-automotion.com FLEXIHAULER. Track-guided tugger AGV that docks onto mobile transport racks, 1000kg payload, 1.2 m/s. HIGH confidence.",
        "ext": {
            "max_payload_kg": 1000,
            "max_speed_ms": 1.2,
            "navigation_type": SLAM,
        },
    },

    # =========================================================================
    # SAFELOG — 3 new models
    # =========================================================================
    {
        "company_key": "SAFELOG",
        "name": "SAFELOG AGV XS1",
        "product_type": "Mobile AMR",
        "source_notes": "safelog.de blog 2024-04-18 XS1 launch. Goods-to-person AMR, 85kg (horizontal), up to 4.0 m/s, no nav type confirmed. HIGH confidence on payload/speed.",
        "ext": {
            "max_payload_kg": 85,
            "max_speed_ms": 4.0,
        },
    },
    {
        "company_key": "SAFELOG",
        "name": "SAFELOG AGV GT1 spin",
        "product_type": "Mobile AMR",
        "source_notes": "synaos.com GT1 spin partner page. Pallet/rack mobile robot, footprint 1200×830mm, loaded speed 2.2 m/s, empty 3.0 m/s. Payload not confirmed — leave NULL. MEDIUM confidence.",
        "ext": {
            "max_speed_ms": 2.2,
        },
    },
    {
        "company_key": "SAFELOG",
        "name": "SAFELOG AGV L2",
        "product_type": "Mobile AMR",
        "source_notes": "safelog.de blog 2023-07-06 L2 launch. Omnidirectional AMR, 1500kg, 0.02-1.6 m/s, hybrid nav (magnetic track / RFID / camera / contour / free nav). HIGH confidence on payload.",
        "ext": {
            "max_payload_kg": 1500,
            "max_speed_ms": 1.6,
            "navigation_type": SLAM,
            "omnidirectional_movement": True,
        },
    },

    # =========================================================================
    # KIVNON — 3 new models
    # NOTE: K03/K41 may be discontinued (absent from current site — flag for review)
    # K05/K10/K55A naming changed: K05=K05 Twister, K10P+K10HP→K10, K55A→K55
    # =========================================================================
    {
        "company_key": "KIVNON",
        "name": "KIVNON K07",
        "product_type": "Mobile AMR",
        "source_notes": "kivnon.com K07. Rotational platform mobile robot, 600-1500kg range. Nav type: SLAM or QR (MEDIUM). Payload MEDIUM (range-level). Recommend spec verification.",
        "ext": {
            "max_payload_kg": 1000,
            "navigation_type": SLAM,
            "omnidirectional_movement": True,
        },
    },
    {
        "company_key": "KIVNON",
        "name": "KIVNON K50 Pallet Truck",
        "product_type": "Forklift AGV",
        "source_notes": "kivnon.com K50 (homepage listing + press). Pallet truck AGV. Payload/lift/speed not confirmed — all NULL until OEM datasheet accessed. MEDIUM type confidence.",
        "ext": {
            "navigation_type": SLAM,
            "stacking_capability": False,
        },
    },
    {
        "company_key": "KIVNON",
        "name": "KIVNON K60 Stacker",
        "product_type": "Forklift AGV",
        "source_notes": "kivnon.com K60 + aerocom.co.uk. Pallet stacker AGV, 2000kg, lift 3000mm. Nav: SLAM, infra-free. MEDIUM confidence (aggregator source).",
        "ext": {
            "max_payload_kg": 2000,
            "lifting_height_mm": 3000,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },

    # =========================================================================
    # SEW-EURODRIVE MAXOLUTION — 3 new models (MEDIUM confidence)
    # Note: AA015 is an assembly assistant — in scope per PM decision
    # =========================================================================
    {
        "company_key": "SEW",
        "name": "MAXOLUTION TV005",
        "product_type": "Mobile AMR",
        "source_notes": "sew-eurodrive.at MAXOLUTION TV005. Transport vehicle, ~600kg. Configurable nav (tape/inductive/SLAM). MEDIUM confidence (code inference: TV=transport, 005=~600kg).",
        "ext": {
            "max_payload_kg": 600,
            "navigation_type": SLAM,
        },
    },
    {
        "company_key": "SEW",
        "name": "MAXOLUTION LA005",
        "product_type": "Mobile AMR",
        "source_notes": "sew-eurodrive.com MAXOLUTION LA005. Logistics assistant, ~300kg. Configurable nav. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 300,
            "navigation_type": SLAM,
        },
    },
    {
        "company_key": "SEW",
        "name": "MAXOLUTION AA015",
        "product_type": "Mobile AMR",
        "source_notes": "sew-eurodrive.co.uk MAXOLUTION AA015. Assembly assistant, 1400kg, modular/custom nav. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 1400,
            "navigation_type": SLAM,
        },
    },

    # =========================================================================
    # MOVU ROBOTICS — 2 missing ifollow variants
    # ifollow family has 4 payloads: 300/600/1000/1200 (DB has 600+1200 only)
    # =========================================================================
    {
        "company_key": "MOVU",
        "name": "Movu ifollow iL300",
        "product_type": "Mobile AMR",
        "source_notes": "movu-robotics.com / ifollow.fr. ifollow family, 300kg variant. Stereo cameras + long-range LiDAR, 360° natural-feature SLAM. HIGH confidence on payload.",
        "ext": {
            "max_payload_kg": 300,
            "navigation_type": SLAM,
        },
    },
    {
        "company_key": "MOVU",
        "name": "Movu ifollow iL1000",
        "product_type": "Mobile AMR",
        "source_notes": "movu-robotics.com / ifollow.fr. ifollow family, 1000kg variant. Stereo cameras + long-range LiDAR, 360° natural-feature SLAM. HIGH confidence on payload.",
        "ext": {
            "max_payload_kg": 1000,
            "navigation_type": SLAM,
        },
    },

    # =========================================================================
    # EK ROBOTICS — 3 new models
    # =========================================================================
    {
        "company_key": "EK_ROBOTICS",
        "name": "ek robotics FAST MOVE",
        "product_type": "Mobile AMR",
        "source_notes": "ek-robotics.com FAST MOVE. Low-profile omnidirectional platform AGV (up to 2m length; roller conveyor / lift table / traction pin options). Payload/speed not published — NULL. HIGH type confidence.",
        "ext": {
            "navigation_type": SLAM,
            "omnidirectional_movement": True,
        },
    },
    {
        "company_key": "EK_ROBOTICS",
        "name": "ek robotics X MOVE 300",
        "product_type": "Mobile AMR",
        "source_notes": "ek-robotics.com X MOVE 300. Underride AMR, 300kg. SLAM, natural feature. HIGH confidence on payload; speed not confirmed.",
        "ext": {
            "max_payload_kg": 300,
            "navigation_type": SLAM,
        },
    },
    {
        "company_key": "EK_ROBOTICS",
        "name": "ek robotics COMPACT MOVE CB 10",
        "product_type": "Forklift AGV",
        "source_notes": "ek-robotics.com COMPACT MOVE series. Counterbalanced forklift AGV, 1000kg (CB 10 / modular up to 1200kg), laser nav + 3D camera. HIGH confidence on payload.",
        "ext": {
            "max_payload_kg": 1000,
            "navigation_type": REFLECTOR_SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },

    # =========================================================================
    # MLR SYSTEM GmbH — 2 new models + NOTE: Mayesto type correction needed
    # (Mayesto in DB is Mobile AMR but it is a Forklift AGV high-rack stacker)
    # =========================================================================
    {
        "company_key": "MLR",
        "name": "MLR Phoenix",
        "product_type": "Forklift AGV",
        "source_notes": "rofa-group.com Phoenix series. Pallet stacker/forklift AGV, 1500kg (special config up to 4500kg), lift 3000mm (duplex mast), free/laser natural-feature nav. Comes in S/M/L sizes. HIGH confidence.",
        "ext": {
            "max_payload_kg": 1500,
            "lifting_height_mm": 3000,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "MLR",
        "name": "MLR Caesar",
        "product_type": "Tugger AGV",
        "source_notes": "rofa-group.com Caesar series. Tow tractor / platform AGV, towing up to 5500kg, platform variant carry 1000kg, 1.5 m/s. Laser + radar + 3D camera nav. Includes Caesar Hospital II compact variant. HIGH confidence.",
        "ext": {
            "max_payload_kg": 1000,
            "towing_capacity_kg": 5500,
            "max_speed_ms": 1.5,
            "navigation_type": SLAM,
        },
    },

    # =========================================================================
    # STÄUBLI — 4 new heavy-load platforms (all approved for DB per PM)
    # =========================================================================
    {
        "company_key": "STAUBLI",
        "name": "Stäubli PF3",
        "product_type": "Mobile AMR",
        "source_notes": "staubli.com PF3 / PF3 OMNI. Heavy-load platform AGV, 2721kg (6000 lb), ~1.1 m/s, laser/natural-feature (WFT drive units). 2400×1035×350mm. HIGH confidence.",
        "ext": {
            "max_payload_kg": 2721,
            "max_speed_ms": 1.1,
            "navigation_type": SLAM,
            "omnidirectional_movement": True,
        },
    },
    {
        "company_key": "STAUBLI",
        "name": "Stäubli PF6",
        "product_type": "Mobile AMR",
        "source_notes": "staubli.com PF6. Heavy-load platform AGV, 5443kg (12000 lb), ~1.1 m/s, laser/natural-feature, 2390×1320×360mm. HIGH confidence.",
        "ext": {
            "max_payload_kg": 5443,
            "max_speed_ms": 1.1,
            "navigation_type": SLAM,
        },
    },
    {
        "company_key": "STAUBLI",
        "name": "Stäubli PF30",
        "product_type": "Mobile AMR",
        "source_notes": "staubli.com / mobile-robots.com PF30. Very heavy-load platform AGV, 27215kg (60000 lb), 3650×2135×560mm, laser/natural-feature. Speed not published — NULL. HIGH confidence.",
        "ext": {
            "max_payload_kg": 27215,
            "navigation_type": SLAM,
        },
    },
    {
        "company_key": "STAUBLI",
        "name": "Stäubli PF280",
        "product_type": "Mobile AMR",
        "source_notes": "staubli.com / mobile-robots.com PF280. Ultra heavy-load platform AGV, 60000kg, 1.3 m/s, 4300×2640×650mm, laser/natural-feature. HIGH confidence.",
        "ext": {
            "max_payload_kg": 60000,
            "max_speed_ms": 1.3,
            "navigation_type": SLAM,
        },
    },

    # =========================================================================
    # KNAPP AG — 3 new Open Shuttle variants
    # =========================================================================
    {
        "company_key": "KNAPP",
        "name": "KNAPP Open Shuttle 100",
        "product_type": "Mobile AMR",
        "source_notes": "KNAPP Product Folder Open Shuttle 2024 (PDF). Container AMR, 120kg, 1.5 m/s, natural-feature SLAM, LiFePo4, VDA 5050, infra-free. Larger load carriers (max 900×650mm). HIGH confidence.",
        "ext": {
            "max_payload_kg": 120,
            "max_speed_ms": 1.5,
            "navigation_type": SLAM,
            "battery_type": "LiFePO4",
            "vda5050_compatible": True,
        },
    },
    {
        "company_key": "KNAPP",
        "name": "KNAPP Open Shuttle Boxgrip",
        "product_type": "Mobile AMR",
        "source_notes": "KNAPP Product Folder Open Shuttle 2024 (PDF). AMR with gripper for containers from flat surfaces, 25kg, 1.5 m/s, SLAM, LiFePo4, no transfer station needed. 998×753×1793mm. HIGH confidence.",
        "ext": {
            "max_payload_kg": 25,
            "max_speed_ms": 1.5,
            "navigation_type": SLAM,
            "battery_type": "LiFePO4",
            "vda5050_compatible": True,
        },
    },
    {
        "company_key": "KNAPP",
        "name": "KNAPP Open Shuttle 50 ASG",
        "product_type": "Mobile AMR",
        "source_notes": "KNAPP Product Folder Open Shuttle 2024 (PDF). AMR for PCB magazines/trays, 50kg, 1.5 m/s, SLAM, LiFePo4, integrated width adjustment. 932×800×1794mm. HIGH confidence.",
        "ext": {
            "max_payload_kg": 50,
            "max_speed_ms": 1.5,
            "navigation_type": SLAM,
            "battery_type": "LiFePO4",
            "vda5050_compatible": True,
        },
    },

    # =========================================================================
    # GRENZEBACH — 1 new model
    # =========================================================================
    {
        "company_key": "GRENZEBACH",
        "name": "Grenzebach L600",
        "product_type": "Mobile AMR",
        "source_notes": "grenzebach.com L600/L1200 page + AGV Portfolio Datasheets PDF. Underride goods-to-person AMR, 600kg, lift 60mm (electrical plate), 1.5 m/s, grid-based optical Data-Matrix marker localization, 48V LiFePo4, ±15mm positioning, 967×750×340mm, IP21. HIGH confidence.",
        "ext": {
            "max_payload_kg": 600,
            "lifting_height_mm": 60,
            "max_speed_ms": 1.5,
            "navigation_type": QR,
            "battery_type": "LiFePO4",
        },
    },

    # =========================================================================
    # GEEK+ (Geekplus) — 9 discrete model variants
    # =========================================================================
    {
        "company_key": "GEEKPLUS",
        "name": "Geek+ F12ML",
        "product_type": "Forklift AGV",
        "source_notes": "geekplus.com F-Series. F12ML forklift AMR, 1400kg, 1.2 m/s, Laser SLAM. MEDIUM confidence (aggregator + OEM page).",
        "ext": {
            "max_payload_kg": 1400,
            "max_speed_ms": 1.2,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "GEEKPLUS",
        "name": "Geek+ P500R",
        "product_type": "Mobile AMR",
        "source_notes": "geekplus.com P-Series shelf-to-person AMR. P500R, 600kg, 2.0 m/s, SLAM. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 600,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
        },
    },
    {
        "company_key": "GEEKPLUS",
        "name": "Geek+ P800R",
        "product_type": "Mobile AMR",
        "source_notes": "geekplus.com P-Series shelf-to-person AMR. P800R, 600kg, 2.0 m/s, SLAM. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 600,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
        },
    },
    {
        "company_key": "GEEKPLUS",
        "name": "Geek+ P1200R",
        "product_type": "Mobile AMR",
        "source_notes": "geekplus.com P-Series shelf-to-person AMR. P1200R heavy variant, up to 1200kg, 2.0 m/s, SLAM. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 1200,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
        },
    },
    {
        "company_key": "GEEKPLUS",
        "name": "Geek+ M200C",
        "product_type": "Mobile AMR",
        "source_notes": "geekplus.com M-Series transport AMR. M200C, 200kg, 1.5 m/s, SLAM/QR/Vision. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 200,
            "max_speed_ms": 1.5,
            "navigation_type": SLAM,
        },
    },
    {
        "company_key": "GEEKPLUS",
        "name": "Geek+ MP1000R",
        "product_type": "Mobile AMR",
        "source_notes": "geekplus.com M-Series transport AMR. MP1000R, 1000kg, 1.5 m/s, SLAM. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 1000,
            "max_speed_ms": 1.5,
            "navigation_type": SLAM,
        },
    },
    {
        "company_key": "GEEKPLUS",
        "name": "Geek+ RoboShuttle P40",
        "product_type": "Mobile AMR",
        "source_notes": "geekplus.com RS-Series (RoboShuttle). P40 tote/bin-to-person, 40kg per tote, 3.5 m/s, SLAM. Very high speed goods-to-person. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 40,
            "max_speed_ms": 3.5,
            "navigation_type": SLAM,
        },
    },
    {
        "company_key": "GEEKPLUS",
        "name": "Geek+ RoboShuttle RS8-DA",
        "product_type": "Mobile AMR",
        "source_notes": "geekplus.com RS-Series RS8-DA. Tote-to-person, 40kg per tote, max reach 7935mm, 1.8 m/s, SLAM. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 40,
            "max_speed_ms": 1.8,
            "navigation_type": SLAM,
        },
    },
    {
        "company_key": "GEEKPLUS",
        "name": "Geek+ RoboShuttle RS11-DA",
        "product_type": "Mobile AMR",
        "source_notes": "geekplus.com RS-Series RS11-DA. Tote-to-person, 40kg per tote, max reach 10765mm, 1.8 m/s, SLAM. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 40,
            "max_speed_ms": 1.8,
            "navigation_type": SLAM,
        },
    },

    # =========================================================================
    # HIKROBOT — 7 new models (F-series and Q-series)
    # All: Laser SLAM. Speeds mostly MEDIUM (aggregator source; OEM JS-blocked).
    # =========================================================================
    {
        "company_key": "HIKROBOT",
        "name": "Hikrobot F1-300T-A",
        "product_type": "Forklift AGV",
        "source_notes": "agvnetwork.com / hikrobotics.com F1-300T-A. Forklift AMR, 300kg, lift 340mm, SLAM. Speed not confirmed. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 300,
            "lifting_height_mm": 340,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "HIKROBOT",
        "name": "Hikrobot F1-1000U-A",
        "product_type": "Forklift AGV",
        "source_notes": "agvnetwork.com / hikrobotics.com F1-1000U-A. Forklift AMR, 600kg, lift 2044mm, SLAM. Speed not confirmed. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 600,
            "lifting_height_mm": 2044,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "HIKROBOT",
        "name": "Hikrobot F5-1600",
        "product_type": "Forklift AGV",
        "source_notes": "directindustry / agvnetwork Hikrobot F5-1600. Forklift AGV, 1600kg, lift 3000mm, 1.5 m/s, SLAM. MEDIUM confidence (aggregator).",
        "ext": {
            "max_payload_kg": 1600,
            "lifting_height_mm": 3000,
            "max_speed_ms": 1.5,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "HIKROBOT",
        "name": "Hikrobot Q2L-300A",
        "product_type": "Mobile AMR",
        "source_notes": "agvnetwork.com Hikrobot Q2L-300A. Latent-lift platform AMR, 300kg, QR-code nav. Speed not confirmed. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 300,
            "navigation_type": QR,
        },
    },
    {
        "company_key": "HIKROBOT",
        "name": "Hikrobot Q3-600C",
        "product_type": "Mobile AMR",
        "source_notes": "agvnetwork / directindustry Hikrobot Q3-600C. Platform AMR, 600kg, natural feature / QR nav. Speed not confirmed. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 600,
            "navigation_type": SLAM,
        },
    },
    {
        "company_key": "HIKROBOT",
        "name": "Hikrobot Q7-1000D",
        "product_type": "Mobile AMR",
        "source_notes": "agvnetwork Hikrobot Q7-1000D. Heavy-duty platform AMR, 1000kg, 1.8 m/s, SLAM/QR. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 1000,
            "max_speed_ms": 1.8,
            "navigation_type": SLAM,
        },
    },
    {
        "company_key": "HIKROBOT",
        "name": "Hikrobot Q7-1000E",
        "product_type": "Mobile AMR",
        "source_notes": "agvnetwork Hikrobot Q7-1000E. Heavy-duty platform AMR, 1000kg, 2.0 m/s, SLAM/QR. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 1000,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
        },
    },

    # =========================================================================
    # GREYORANGE — 1 new model (XXL/AnyPallet excluded: combined-load payload)
    # =========================================================================
    {
        "company_key": "GREYORANGE",
        "name": "GreyOrange Ranger RIL-L",
        "product_type": "Mobile AMR",
        "source_notes": "mobile-robots.com + RIL brochure. Ranger Intralogistics-L, 1000kg, 2.0 m/s, 2D LiDAR SLAM (GreyMatter). HIGH confidence. Note: RU-L (existing DB) may share identical chassis — verify before field-level matching.",
        "ext": {
            "max_payload_kg": 1000,
            "max_speed_ms": 2.0,
            "navigation_type": SLAM,
        },
    },

    # =========================================================================
    # BA SYSTÈMES / ALSTEF — 6 new models (DB had only GT16 + Loadstar)
    # =========================================================================
    {
        "company_key": "BA_SYSTEMES",
        "name": "Alstef GLR",
        "product_type": "Forklift AGV",
        "source_notes": "alstefgroup.com AGV/AMR range. GLR narrow-aisle reach truck AGV, 1400kg, lift 9000mm, 2.5 m/s. HIGH confidence.",
        "ext": {
            "max_payload_kg": 1400,
            "lifting_height_mm": 9000,
            "max_speed_ms": 2.5,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "BA_SYSTEMES",
        "name": "Alstef GL",
        "product_type": "Forklift AGV",
        "source_notes": "alstefgroup.com AGV/AMR range. GL fork-over forklift AGV, lift 1000-3000mm. Payload/speed not confirmed — NULL. MEDIUM confidence.",
        "ext": {
            "navigation_type": SLAM,
            "stacking_capability": True,
        },
    },
    {
        "company_key": "BA_SYSTEMES",
        "name": "Alstef GF2",
        "product_type": "Forklift AGV",
        "source_notes": "alstefgroup.com AGV range. GF2 counterbalance stacker, twin-pallet (2×1400kg), lift up to 6500mm. Payload = 1400kg per single pallet for KO matching. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 1400,
            "lifting_height_mm": 6500,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "BA_SYSTEMES",
        "name": "Alstef GF12",
        "product_type": "Forklift AGV",
        "source_notes": "alstefgroup.com AGV range. GF12 counterbalance stacker, lift 8000mm. Payload/speed not confirmed — NULL. MEDIUM confidence.",
        "ext": {
            "lifting_height_mm": 8000,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "BA_SYSTEMES",
        "name": "Alstef GF10.1",
        "product_type": "Forklift AGV",
        "source_notes": "alstefgroup.com AGV range. GF10.1 counterbalance stacker (low-lift), up to 1500mm. Payload/speed not confirmed — NULL. MEDIUM confidence.",
        "ext": {
            "lifting_height_mm": 1500,
            "navigation_type": SLAM,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "BA_SYSTEMES",
        "name": "Alstef CM",
        "product_type": "Tugger AGV",
        "source_notes": "alstefgroup.com AGV range. CM powered-conveyor tugger, up to 1500kg load (1-4 loads), transfer height 500mm. Speed not confirmed. MEDIUM confidence.",
        "ext": {
            "max_payload_kg": 1500,
            "navigation_type": SLAM,
        },
    },

    # =========================================================================
    # E80 GROUP / ELETTRIC80 — 2 new models
    # NOTE: Trilateral LGV in DB — verify vna_capable = True (VNA forklift)
    # =========================================================================
    {
        "company_key": "E80",
        "name": "E80 Micro LGV",
        "product_type": "Forklift AGV",
        "source_notes": "elettric80.com / e80group.com Micro LGV. Compact laser-guided forklift, 1500kg, lift 1500mm, ≤1.5 m/s, laser reflector nav, deep-freeze −26°C capable. HIGH confidence.",
        "ext": {
            "max_payload_kg": 1500,
            "lifting_height_mm": 1500,
            "max_speed_ms": 1.5,
            "navigation_type": REFLECTOR,
            "stacking_capability": True,
            "vna_capable": False,
        },
    },
    {
        "company_key": "E80",
        "name": "E80 Quad LGV",
        "product_type": "Forklift AGV",
        "source_notes": "e80group.com LGV page. Quad LGV roller-conveyor type, 4000kg, laser reflector nav. Speed not confirmed. HIGH confidence on type/payload.",
        "ext": {
            "max_payload_kg": 4000,
            "navigation_type": REFLECTOR,
        },
    },
]


# ---------------------------------------------------------------------------
# Airtable helpers
# ---------------------------------------------------------------------------

def post_record(table_name: str, fields: dict) -> str:
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES[table_name]}"
    r = requests.post(url, headers=HEADERS, json={"fields": fields}, timeout=30)
    if not r.ok:
        print(f"    HTTP {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    return r.json()["id"]


def run_import():
    created = {"base_models": 0, "products": 0, "extensions": 0}
    errors = []

    for prod in NEW_PRODUCTS:
        co_key = prod["company_key"]
        co_rec = CO[co_key]
        name   = prod["name"]
        atype  = prod["product_type"]
        print(f"\n→ {name}  ({atype})")

        # 1. Create base_model
        try:
            bm_fields = {
                "base_model_name": name,
                "product_type": atype,
                "base_model_id": str(uuid.uuid4()),
            }
            bm_rec = post_record("base_models", bm_fields)
            created["base_models"] += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  ✗ base_model FAILED: {e}")
            errors.append((name, "base_model", str(e)))
            continue

        # 2. Create product
        try:
            pr_fields = {
                "product_name": name,
                "product_type": atype,
                "active": True,
                "company_id": [co_rec],
                "base_model_id": [bm_rec],
                "product_id": str(uuid.uuid4()),
                "source_notes": prod.get("source_notes", ""),
                "service_coverage": ["EU"],
            }
            if prod.get("is_oem_product"):
                pr_fields["is_oem_product"] = True
            pr_rec = post_record("products", pr_fields)
            created["products"] += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  ✗ product FAILED: {e}")
            errors.append((name, "product", str(e)))
            continue

        # 3. Create extension
        try:
            ext = prod.get("ext", {})
            ext_fields = {
                "model_name": name,
                "product_type": atype,
                "base_model_id": [bm_rec],
                "extension_id": str(uuid.uuid4()),
            }
            ext_fields.update(ext)
            ext_rec = post_record("extensions", ext_fields)
            created["extensions"] += 1
            print(f"  ✓ bm={bm_rec[:8]}… pr={pr_rec[:8]}… ext={ext_rec[:8]}…")
            time.sleep(0.3)
        except Exception as e:
            print(f"  ✗ extension FAILED: {e}")
            errors.append((name, "extension", str(e)))

    print(f"\n{'='*60}")
    print(f"Created: {created}")
    total = len(NEW_PRODUCTS)
    ok = created["products"]
    print(f"Products: {ok}/{total} succeeded")
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for name, stage, msg in errors:
            print(f"  [{stage}] {name}: {msg}")
    else:
        print("No errors.")
    print("\nNext steps:")
    print("  python3 sync_airtable.py")
    print("\nManual corrections still needed (separate task):")
    print("  1. MLR Mayesto: reclassify Mobile AMR → Forklift AGV (high-rack stacker, 11m)")
    print("  2. VisionNav VNE20: verify payload 1500kg (DB) vs 2000kg (website)")
    print("  3. Grenzebach FF1200S: navigation_type → Inductive Loop (not SLAM/contour)")
    print("  4. E80 Trilateral LGV: set vna_capable = True")
    print("  5. KIVNON K03/K41: check if discontinued, remove if so")
    print("  6. Linde: add OEM base_model link to Balyo records (pending schema support)")


if __name__ == "__main__":
    run_import()
