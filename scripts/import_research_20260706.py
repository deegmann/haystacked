"""
Import research findings from docs/research_findings_20260706_*.json into haystacked.db.
Updates base_model_extensions for matched products. Skips low-confidence entries.
Only updates NULL fields unless --overwrite is passed.
"""
import json, sqlite3, sys, glob
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "haystacked.db"
DOCS = Path(__file__).parent.parent / "docs"
OVERWRITE = "--overwrite" in sys.argv

# Fields that are multi-select and stored pipe-separated in DB
MULTISELECT = {"navigation_type", "battery_type", "drive_type", "safety_standard",
               "load_type", "service_coverage", "fleet_management_system",
               "station_applications", "coupling_type", "languages_spoken",
               "industries_served", "workflow_capability", "picking_mechanism"}

# Fields that are boolean (0/1 in SQLite)
BOOLEAN = {"rotation_capable", "autonomous_charging", "outdoor_capable", "vda5050_compatible",
           "infrastructure_required", "stacking_capability", "manual_usage", "vna_capable",
           "multi_fleet_capable", "wms_integration_native", "battery_swap_capable",
           "barcode_readers", "trailer_loading", "trailer_unloading", "autonomous_obstacle_bypass",
           "rack_pin_compatible", "forks_free_floating", "multi_load_compatibility",
           "grid_required", "load_detection", "auto_hitch", "busbar_compatible",
           "stock_line_scanning", "ergonomic_height_adjustable", "gamification",
           "omnidirectional_movement", "task_interleaving"}

def to_db_value(field, value):
    if isinstance(value, bool):
        return 1 if value else 0
    if field in BOOLEAN and isinstance(value, int):
        return value
    if field in MULTISELECT and isinstance(value, list):
        return "|".join(value)
    return value

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Build lookup: product_name (lower) → base_model_id
cur.execute("SELECT product_name, base_model_id FROM products WHERE active=1")
name_to_bmid = {r["product_name"].lower().strip(): r["base_model_id"] for r in cur.fetchall()}

files = sorted(DOCS.glob("research_findings_20260706_*.json"))
if not files:
    print("No research files found.")
    sys.exit(1)

total_updated = 0
total_skipped = 0
total_no_match = 0

for fpath in files:
    with open(fpath) as f:
        data = json.load(f)
    company = data.get("company", fpath.stem)
    products = data.get("products", [])
    print(f"\n{'='*60}")
    print(f"Company: {company} ({len(products)} products in file)")

    for prod in products:
        name = prod.get("product_name", "").lower().strip()
        confidence = prod.get("confidence", "medium")
        fields = prod.get("fields", {})

        if confidence == "low":
            print(f"  SKIP (low confidence): {prod.get('product_name')}")
            total_skipped += 1
            continue

        bmid = name_to_bmid.get(name)
        if not bmid:
            # Try partial match
            matches = [k for k in name_to_bmid if name in k or k in name]
            if len(matches) == 1:
                bmid = name_to_bmid[matches[0]]
                print(f"  Partial match: '{prod.get('product_name')}' → '{matches[0]}'")
            else:
                print(f"  NO MATCH: '{prod.get('product_name')}' (candidates: {matches[:3]})")
                total_no_match += 1
                continue

        # Fetch current bme row
        cur.execute("SELECT * FROM base_model_extensions WHERE base_model_id=?", (bmid,))
        row = cur.fetchone()
        if not row:
            print(f"  NO BME ROW for base_model_id={bmid} ({prod.get('product_name')})")
            total_no_match += 1
            continue

        updates = {}
        for field, value in fields.items():
            if field not in row.keys():
                print(f"    UNKNOWN FIELD: {field} — skip")
                continue
            current = row[field]
            if current is not None and not OVERWRITE:
                # Don't overwrite existing values unless --overwrite
                continue
            db_val = to_db_value(field, value)
            updates[field] = db_val

        if updates:
            set_clause = ", ".join(f"{k}=?" for k in updates)
            cur.execute(
                f"UPDATE base_model_extensions SET {set_clause} WHERE base_model_id=?",
                list(updates.values()) + [bmid]
            )
            print(f"  OK  {prod.get('product_name')}: {list(updates.keys())}")
            total_updated += 1
        else:
            print(f"  --  {prod.get('product_name')}: nothing new (all fields already set or empty fields dict)")

conn.commit()
conn.close()

print(f"\n{'='*60}")
print(f"DONE: {total_updated} products updated, {total_skipped} skipped (low conf), {total_no_match} no match")
print("Run 'python3 scripts/import_research_20260706.py --overwrite' to overwrite existing values.")
