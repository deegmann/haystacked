#!/usr/bin/env python3
"""
AP2 Airtable Schema Setup — haystacked-AGV-PoC
Creates all 4 tables with correct field types and views.

Prerequisites:
  export AIRTABLE_BASE_ID=appXXXXXXXXXXXXXX
  export AIRTABLE_TOKEN=patXXXXXXXXXXXXXX

Run: python3 ap2_schema.py
Output: airtable_schema_ids.json  (read by ap2_import.py)
"""

import os, sys, json, time
import requests

BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "")
TOKEN   = os.environ.get("AIRTABLE_TOKEN", "")

if not BASE_ID or not TOKEN:
    sys.exit("ERROR: Set AIRTABLE_BASE_ID and AIRTABLE_TOKEN environment variables first.")

HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
META    = f"https://api.airtable.com/v0/meta/bases/{BASE_ID}"

# ── API helpers ───────────────────────────────────────────────────────────────

def _call(method, url, **kw):
    r = getattr(requests, method)(url, headers=HEADERS, **kw)
    if not r.ok:
        print(f"    ERROR {r.status_code}: {r.text}")
        r.raise_for_status()
    time.sleep(0.25)  # 5 req/s rate limit
    return r.json()

def create_table(name, primary_field_def):
    """Create a table with a single primary field; returns table dict."""
    print(f"  Creating table '{name}'...")
    return _call("post", f"{META}/tables", json={"name": name, "fields": [primary_field_def]})

def add_field(table_id, field_def):
    return _call("post", f"{META}/tables/{table_id}/fields", json=field_def)

def create_view(table_id, name, view_type="grid"):
    return _call("post", f"{META}/tables/{table_id}/views", json={"name": name, "type": view_type})

# ── Field type builders ───────────────────────────────────────────────────────

def text(name):          return {"name": name, "type": "singleLineText"}
def longtext(name):      return {"name": name, "type": "multilineText"}
def num_int(name):       return {"name": name, "type": "number", "options": {"precision": 0}}
def num_dec(name):       return {"name": name, "type": "number", "options": {"precision": 8}}
def url_f(name):         return {"name": name, "type": "url"}
def email_f(name):       return {"name": name, "type": "email"}
def phone_f(name):       return {"name": name, "type": "phoneNumber"}
def check(name):         return {"name": name, "type": "checkbox", "options": {"icon": "check", "color": "greenBright"}}
def date_f(name):        return {"name": name, "type": "date", "options": {"dateFormat": {"name": "iso"}}}
def link_to(name, tid):  return {"name": name, "type": "multipleRecordLinks", "options": {"linkedTableId": tid}}

def ss(name, choices):
    return {"name": name, "type": "singleSelect", "options": {"choices": [{"name": c} for c in choices]}}

def ms(name, choices):
    return {"name": name, "type": "multipleSelects", "options": {"choices": [{"name": c} for c in choices]}}

# ── Dropdown value lists ──────────────────────────────────────────────────────

COUNTRIES = [
    "AD","AE","AF","AG","AI","AL","AM","AO","AQ","AR","AS","AT","AU","AW","AX",
    "AZ","BA","BB","BD","BE","BF","BG","BH","BI","BJ","BL","BM","BN","BO","BQ",
    "BR","BS","BT","BV","BW","BY","BZ","CA","CC","CD","CF","CG","CH","CI","CK",
    "CL","CM","CN","CO","CR","CU","CV","CW","CX","CY","CZ","DE","DJ","DK","DM",
    "DO","DZ","EC","EE","EG","EH","ER","ES","ET","FI","FJ","FK","FM","FO","FR",
    "GA","GB","GD","GE","GF","GG","GH","GI","GL","GM","GN","GP","GQ","GR","GS",
    "GT","GU","GW","GY","HK","HM","HN","HR","HT","HU","ID","IE","IL","IM","IN",
    "IO","IQ","IR","IS","IT","JE","JM","JO","JP","KE","KG","KH","KI","KM","KN",
    "KP","KR","KW","KY","KZ","LA","LB","LC","LI","LK","LR","LS","LT","LU","LV",
    "LY","MA","MC","MD","ME","MF","MG","MH","MK","ML","MM","MN","MO","MP","MQ",
    "MR","MS","MT","MU","MV","MW","MX","MY","MZ","NA","NC","NE","NF","NG","NI",
    "NL","NO","NP","NR","NU","NZ","OM","PA","PE","PF","PG","PH","PK","PL","PM",
    "PN","PR","PS","PT","PW","PY","QA","RE","RO","RS","RU","RW","SA","SB","SC",
    "SD","SE","SG","SH","SI","SJ","SK","SL","SM","SN","SO","SR","SS","ST","SV",
    "SX","SY","SZ","TC","TD","TF","TG","TH","TJ","TK","TL","TM","TN","TO","TR",
    "TT","TV","TW","TZ","UA","UG","UM","US","UY","UZ","VA","VC","VE","VG","VI",
    "VN","VU","WF","WS","XK","YE","YT","ZA","ZM","ZW",
]

AGV_TYPES = ["Forklift AGV", "Tugger AGV", "Mobile AMR"]

# ── Table field definitions ───────────────────────────────────────────────────
# Each list entry is passed to add_field() after table creation.
# Primary field is created inline with create_table().

COMPANIES_FIELDS = [
    text("company_id"),
    ss("country", COUNTRIES),
    text("hq_city"),
    text("hq_address"),
    url_f("hq_maps_link"),
    longtext("all_sites"),
    ss("employee_count_range", ["<50", "50–250", "250–1000", ">1000"]),
    text("fleet_size_vehicles"),
    num_int("founding_year"),
    url_f("website"),
    email_f("email"),
    phone_f("phone"),
    text("contact_person"),
    ms("certifications_generic", ["ISO 9001", "ISO 14001", "CE", "TÜV", "VDA5050 ready"]),
    ms("languages_spoken", ["DE", "EN", "FR", "ES", "IT", "ZH", "DK", "+local"]),
    ms("service_coverage", ["None", "DACH", "EU", "Global"]),
    date_f("last_updated"),
]

BASE_MODELS_FIELDS = [
    # oem_company_id (link) added after Companies table exists
    text("base_model_id"),
    ss("agv_type", AGV_TYPES),
    check("oem_link_public"),
    date_f("last_updated"),
]

PRODUCTS_FIELDS = [
    # company_id (link) and base_model_id (link) added after other tables exist
    text("product_id"),
    ss("agv_type", AGV_TYPES),
    longtext("product_description"),
    num_int("reference_count"),
    num_int("min_project_value_eur"),
    num_int("max_project_value_eur"),
    num_int("lead_time_weeks"),
    ss("distribution_model", ["Direct", "Dealer Network", "Integrator only", "License Platform"]),
    check("is_oem_product"),
    ms("service_coverage", ["None", "DACH", "EU", "Global"]),
    check("active"),
    longtext("source_notes"),
]

EXTENSIONS_FIELDS = [
    # base_model_id (link) added after Base Models table exists
    text("extension_id"),
    ss("agv_type", AGV_TYPES),
    # SHARED — Navigation & Infrastructure
    ms("navigation_type", [
        "Laser Reflector", "Natural Feature (SLAM)", "Magnetic Tape",
        "QR/DM Code", "Contour", "Inductive Loop", "Vision",
    ]),
    check("infrastructure_required"),
    check("autonomous_obstacle_bypass"),
    check("omnidirectional_movement"),
    # SHARED — Load Handling
    num_dec("max_payload_kg"),
    ms("load_type", [
        "Pallet EUR", "Pallet ISO", "Half-Euro", "UK Pallet",
        "Plastic (closed)", "Tote", "Roll Container", "Custom Carrier", "None",
    ]),
    check("multi_load_compatibility"),
    # SHARED — Dimensions & Environment
    num_dec("max_speed_ms"),
    num_int("length_mm"),
    num_int("width_mm"),
    num_int("operating_temp_min_c"),
    num_int("operating_temp_max_c"),
    num_int("operating_humidity_max_pct"),
    ss("ingress_protection_rating", ["None", "IP20", "IP21", "IP44", "IP52", "IP54", "IP65", "IP67"]),
    ss("cleanroom_class", ["None", "ISO 1", "ISO 2", "ISO 3", "ISO 4", "ISO 5", "ISO 6", "ISO 7", "ISO 8", "ISO 9"]),
    check("outdoor_capable"),
    num_dec("max_gradient_pct"),
    ss("floor_flatness_req", ["None stated", "Standard (FM2)", "High (FM1)", "Very High (F-number)"]),
    num_int("stop_accuracy_mm"),
    # SHARED — Power
    ms("battery_type", ["Li-Ion", "LiFePO4", "Lead-Acid", "Hydrogen FC"]),
    num_dec("battery_runtime_h"),
    num_int("charge_time_min"),
    check("autonomous_charging"),
    check("battery_swap_capable"),
    # SHARED — Safety & Certification
    ms("safety_standard", ["None", "ISO 3691-4", "EN 1525 (legacy)", "ANSI/ITSDF B56.5", "UL 3100"]),
    ss("functional_safety_level", ["None", "PLd", "PLe", "SIL 2", "SIL 3"]),
    ss("safety_coverage", ["Single plane (2D)", "Limited 3D (e.g. waterfall)", "Full 3D"]),
    # SHARED — Fleet & Integration
    ss("fleet_management_system", [
        "Proprietary", "Open API", "VDA 5050 compatible", "Third-party WMS native",
    ]),
    ss("fleet_control_architecture", ["Centralized", "Decentralized/Swarm", "Hybrid"]),
    check("vda5050_compatible"),
    num_int("max_fleet_size"),
    check("multi_fleet_capable"),
    ms("integration_capability", ["None", "SAP", "WMS", "ERP", "REST API", "MQTT", "OPC-UA", "Modbus", "MES"]),
    # SHARED — Stations & Context
    ms("station_applications", [
        "Floor", "Conveyor", "Machine cell", "Gravity rack", "Standard rack",
        "Shuttle rack", "Mobile rack", "Workstation", "Dock",
    ]),
    check("manual_usage"),
    ms("industries_served", [
        "Automotive", "F&B", "Pharma", "E-Commerce", "General Manufacturing",
        "3PL", "Retail", "Tissue/Paper",
    ]),
    # Forklift AGV — type-specific
    num_int("lifting_height_mm"),
    num_int("min_total_height_mm"),
    ms("special_fork_option", ["Telescopic", "Side-Shift", "Clamp"]),
    ss("fork_spread", ["None", "Manual", "Auto"]),
    ss("mast_type", ["Simplex", "Duplex", "Triplex", "Quadruplex"]),
    num_int("min_aisle_width_mm"),
    check("vna_capable"),
    ss("drive_type", ["Counterbalanced", "Reach Truck", "Straddle Stacker", "Pallet Mover", "VNA Turret"]),
    num_int("drop_accuracy_lat_mm"),
    num_int("drop_accuracy_dep_mm"),
    num_int("drop_accuracy_angle_deg"),
    num_int("pick_req_accuracy_lat_mm"),
    num_int("pick_req_accuracy_dep_mm"),
    num_int("pick_req_accuracy_angle_deg"),
    check("forks_free_floating"),
    check("stacking_capability"),
    ms("load_detection", [
        "None", "Camera/Vision", "Laser/LiDAR profiling", "RFID",
        "Barcode/DataMatrix", "Mechanical/Tactile", "Predefined coordinates",
    ]),
    check("barcode_readers"),
    check("stock_line_scanning"),
    check("trailer_loading"),
    check("trailer_unloading"),
    ms("guidance", ["None", "Rail", "Wire"]),
    check("busbar_compatible"),
    # Tugger AGV — type-specific
    num_dec("towing_capacity_kg"),
    num_int("max_trailers"),
    ms("coupling_type", ["Automatic", "Manual", "Pintle Hook", "Towbar", "Retractable Pin"]),
    check("auto_hitch"),
    num_int("auto_hitch_position_tolerance_mm"),  # AP0 v0.6 canonical name
    ss("train_configuration", ["B-frame", "C-frame", "Underride/Mouse", "Tugger + trailers"]),
    ms("load_transfer", ["Manual", "Automatic roller", "Lift", "Pull-out frame"]),
    longtext("trailer_compatibility"),
    ms("trailer_steering_technology", [
        "Passive caster", "Dual-steer", "Center-steer", "Quad-steer",
        "Tracking drawbar / virtual coupling", "Forced/positive axle steer", "Manual only",
    ]),
    ss("route_type", ["Fixed Route", "Flexible Route", "Fully Dynamic"]),
    ss("route_programming", ["Teach-in", "Map-based", "Mixed"]),
    check("intersection_management"),
    num_int("turning_radius_mm"),
    # Mobile AMR — type-specific
    ms("workflow_capability", ["Transport", "Goods-to-Person", "Picking support"]),
    check("grid_required"),
    check("rotation_capable"),
    ss("picking_mechanism", [
        "None", "Human-assisted (cart follower)", "Autonomous arm",
        "Conveyor-integrated", "Bin-transfer",
    ]),
    num_int("lift_height_mm"),
    num_int("min_ground_clearance_mm"),
    check("rack_pin_compatible"),
    check("free_lift_open_closed_pallet"),
    ms("top_module_type", ["None", "Lift", "Hook", "Shelf Carrier", "Conveyor", "Roller", "Cobot arm", "Custom"]),
    num_int("min_turning_radius_mm"),
    ss("storage_system_type", [
        "None", "Shelf-to-Person", "Bin-to-Person", "Tote-to-Person", "Pallet-to-Person",
    ]),
    num_int("shelf_height_mm"),
    text("shelf_footprint_mm"),
    num_int("throughput_picks_per_hour"),
    ss("throughput_basis", ["Per station", "Per robot", "Per system"]),
    check("task_interleaving"),
    check("onboard_ui"),
    ms("onboard_container_type", ["None", "Tote", "Bag", "Open shelf", "Bulk bin", "Shipping box"]),
    ms("wms_integration_native", ["None", "SAP EWM", "Oracle WMS", "Manhattan", "Blue Yonder", "Custom API"]),
    # Meta
    longtext("source_notes"),
    # SHARED — Installation & Modification (AP0 v0.6)
    ms("installation_process", ["Supplier only", "Client"]),
    ms("modification_process", ["Supplier only", "Supplier limited", "Client: All"]),
    num_int("min_fleet_size"),
    # Mobile AMR — additional fields (AP0 v0.6)
    text("cart_pickup_height_range_mm"),
    num_int("min_grid_area_m2"),
    num_int("concurrent_robots_per_station"),
    num_int("order_lines_per_run"),
    num_dec("storage_density_factor"),
    check("ergonomic_height_adjustable"),
    check("multi_language_display"),
    check("gamification"),
    num_int("onboard_container_count"),
]

# ── Views ─────────────────────────────────────────────────────────────────────

EXTENSION_VIEWS = [
    "🔧 Forklift AGV",
    "🚛 Tugger AGV",
    "🤖 Mobile AMR",
    "📋 All — Unsorted",
]

PRODUCT_VIEWS = [
    "Forklift AGV",
    "Tugger AGV",
    "Mobile AMR",
    "Active only",
]

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ids = {}  # table_name → {id, field_ids}

    print("\n=== Phase 1: Create tables ===")

    t = create_table("Companies", text("company_name"))
    ids["companies"] = t["id"]
    print(f"    ✓ id={t['id']}")

    t = create_table("Base Models", text("base_model_name"))
    ids["base_models"] = t["id"]
    print(f"    ✓ id={t['id']}")

    t = create_table("Products", text("product_name"))
    ids["products"] = t["id"]
    print(f"    ✓ id={t['id']}")

    t = create_table("Base Model Extensions", text("model_name"))
    ids["extensions"] = t["id"]
    print(f"    ✓ id={t['id']}")

    print("\n=== Phase 2: Add non-linked fields ===")

    def add_all(table_key, fields):
        tid = ids[table_key]
        for f in fields:
            print(f"    + {table_key}.{f['name']}")
            add_field(tid, f)

    add_all("companies",  COMPANIES_FIELDS)
    add_all("base_models", BASE_MODELS_FIELDS)
    add_all("products",   PRODUCTS_FIELDS)
    add_all("extensions", EXTENSIONS_FIELDS)

    print("\n=== Phase 3: Add linked record fields ===")

    add_field(ids["base_models"], link_to("oem_company_id", ids["companies"]))
    print("    ✓ Base Models.oem_company_id → Companies")

    add_field(ids["products"], link_to("company_id", ids["companies"]))
    print("    ✓ Products.company_id → Companies")

    add_field(ids["products"], link_to("base_model_id", ids["base_models"]))
    print("    ✓ Products.base_model_id → Base Models")

    add_field(ids["extensions"], link_to("base_model_id", ids["base_models"]))
    print("    ✓ Base Model Extensions.base_model_id → Base Models")

    print("\n=== Phase 4: Create views ===")

    for v in EXTENSION_VIEWS:
        create_view(ids["extensions"], v)
        print(f"    ✓ Extensions: {v}")

    for v in PRODUCT_VIEWS:
        create_view(ids["products"], v)
        print(f"    ✓ Products: {v}")

    # Save IDs for the import script
    out = {"table_ids": ids}
    with open("airtable_schema_ids.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\n✓ Saved table IDs → airtable_schema_ids.json")

    print("""
╔══════════════════════════════════════════════════════════════════╗
║  MANUAL STEP — Set view filters in Airtable UI                  ║
╠══════════════════════════════════════════════════════════════════╣
║  Base Model Extensions table:                                    ║
║    🔧 Forklift AGV   → agv_type  is  "Forklift AGV"             ║
║    🚛 Tugger AGV     → agv_type  is  "Tugger AGV"               ║
║    🤖 Mobile AMR     → agv_type  is  "Mobile AMR"               ║
║  Products table:                                                  ║
║    Forklift AGV      → agv_type  is  "Forklift AGV"             ║
║    Tugger AGV        → agv_type  is  "Tugger AGV"               ║
║    Mobile AMR        → agv_type  is  "Mobile AMR"               ║
║    Active only       → active    is  checked                     ║
╚══════════════════════════════════════════════════════════════════╝

Next step: python3 ap2_import.py --xlsx /path/to/haystacked_supplier_seed_v03.xlsx
""")

if __name__ == "__main__":
    main()
