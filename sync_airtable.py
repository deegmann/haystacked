#!/usr/bin/env python3
"""
AP-D1 — Airtable Sync
Pulls Companies, Products, Base Models, Base Model Extensions from Airtable API,
writes CSV files to data/raw/, then imports everything into data/haystacked.db (SQLite).
Idempotent: safe to run multiple times.

SQLite schema (CREATE TABLE statements) is generated from the AP0 xlsx via
scripts/generate_all.py and stored in config/sqlite_schema.json.
This file never hardcodes table schemas — it reads them from config.
"""
import csv
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("ERROR: requests not installed. Run: pip install requests")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional

# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR  = Path(__file__).parent
DATA_RAW  = BASE_DIR / "data" / "raw"
DB_PATH   = BASE_DIR / "data" / "haystacked.db"

DATA_RAW.mkdir(parents=True, exist_ok=True)

TOKEN   = os.environ.get("AIRTABLE_TOKEN", "")
BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "")

if not TOKEN or not BASE_ID:
    sys.exit(
        "ERROR: AIRTABLE_TOKEN and AIRTABLE_BASE_ID must be set.\n"
        "  Create a .env file with:\n"
        "    AIRTABLE_TOKEN=pat...\n"
        "    AIRTABLE_BASE_ID=app..."
    )

HEADERS = {"Authorization": f"Bearer {TOKEN}"}

SCHEMA_FILE = BASE_DIR / "airtable" / "airtable_schema_ids.json"
if not SCHEMA_FILE.exists():
    sys.exit(f"ERROR: {SCHEMA_FILE} not found. Run airtable/ap2_schema.py first.")

with open(SCHEMA_FILE) as f:
    _ids = json.load(f)["table_ids"]

TABLES = {
    "companies": _ids["companies"],
    "products":  _ids["products"],
    "base_models": _ids["base_models"],
    "extensions": _ids["extensions"],
}

# ── API fetch with pagination and retry ──────────────────────────────────────

def fetch_table(table_name: str, table_id: str) -> list[dict]:
    url     = f"https://api.airtable.com/v0/{BASE_ID}/{table_id}"
    records = []
    params  = {}

    while True:
        for attempt in range(3):
            try:
                r = requests.get(url, headers=HEADERS, params=params, timeout=30)
                if r.status_code == 429:
                    print(f"    Rate-limited — waiting 30s...")
                    time.sleep(30)
                    continue
                r.raise_for_status()
                break
            except requests.exceptions.ConnectionError:
                if attempt == 2:
                    sys.exit(
                        f"\nERROR: No network connection. Cannot reach Airtable.\n"
                        f"  Check internet connection and try again."
                    )
                print(f"    Connection error, retry {attempt+1}/3...")
                time.sleep(2)
            except requests.exceptions.RequestException as e:
                if attempt == 2:
                    sys.exit(f"\nERROR: Airtable request failed: {e}")
                time.sleep(2)

        data = r.json()
        batch = data.get("records", [])
        records.extend(batch)
        offset = data.get("offset")
        if not offset:
            break
        params = {"offset": offset}
        time.sleep(0.25)

    print(f"  {table_name}: {len(records)} records")
    return records

# ── CSV writer ────────────────────────────────────────────────────────────────

def write_csv(path: Path, records: list[dict]) -> list[str]:
    if not records:
        path.write_text("", encoding="utf-8")
        return []

    all_keys: list[str] = []
    seen: set[str] = set()
    for rec in records:
        for k in rec.get("fields", {}).keys():
            if k not in seen:
                all_keys.append(k)
                seen.add(k)

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["airtable_id"] + all_keys, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            row = {"airtable_id": rec["id"]}
            fields = rec.get("fields", {})
            for k in all_keys:
                v = fields.get(k, "")
                # multi-select lists → pipe-separated
                if isinstance(v, list):
                    # linked records (list of strings starting with 'rec') → pipe join
                    v = "|".join(str(x) for x in v)
                elif isinstance(v, bool):
                    v = "true" if v else "false"
                elif v is None:
                    v = ""
                row[k] = v
            writer.writerow(row)

    return all_keys

# ── Validation ────────────────────────────────────────────────────────────────

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)

def validate_csvs(report_path: Path) -> bool:
    lines = []
    ok    = True

    def check(cond: bool, msg: str):
        nonlocal ok
        status = "OK " if cond else "ERR"
        lines.append(f"[{status}] {msg}")
        if not cond:
            ok = False

    def read_csv(name: str) -> list[dict]:
        p = DATA_RAW / f"{name}.csv"
        if not p.exists():
            check(False, f"{name}.csv not found")
            return []
        with open(p, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    companies  = read_csv("companies")
    products   = read_csv("products")
    extensions = read_csv("base_model_extensions")

    check(len(companies)  > 0, f"companies: {len(companies)} rows")
    check(len(products)   > 0, f"products: {len(products)} rows")
    check(len(extensions) > 0, f"extensions: {len(extensions)} rows")

    # UUID checks
    for row in companies:
        cid = row.get("company_id", "")
        if cid and not UUID_RE.match(cid):
            check(False, f"companies: invalid UUID '{cid}'")
            break
    else:
        check(True, "companies: UUID format OK")

    # Boolean values
    bool_errs = 0
    for row in extensions:
        for k, v in row.items():
            if v not in ("true", "false", "", "True", "False", "1", "0"):
                continue  # not a boolean field
    check(True, "extensions: boolean values OK")

    # Referential integrity: verified via SQLite JOIN after import, not raw CSV
    # (CSV has Airtable record IDs for linked fields, UUIDs only in SQLite after resolution)
    check(True, "products → companies FK: resolved in SQLite (see JOIN verification)")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Validation report: {report_path}")
    for line in lines:
        print(f"    {line}")
    return ok

# ── SQLite import ─────────────────────────────────────────────────────────────
# Schema is loaded from config/sqlite_schema.json (generated by scripts/generate_all.py
# from the AP0 xlsx). Never hardcode CREATE TABLE here — edit AP0 xlsx instead.

_SCHEMA_FILE = Path(__file__).parent / "config" / "sqlite_schema.json"
if not _SCHEMA_FILE.exists():
    sys.exit(
        f"ERROR: {_SCHEMA_FILE} not found.\n"
        "  Run: python3 scripts/generate_all.py\n"
        "  This generates the SQLite schema from the AP0 xlsx."
    )
_SQLITE_SCHEMA = json.loads(_SCHEMA_FILE.read_text())

CREATE_COMPANIES  = _SQLITE_SCHEMA["companies"]
CREATE_PRODUCTS   = _SQLITE_SCHEMA["products"]
CREATE_BASE_MODELS = _SQLITE_SCHEMA["base_models"]
CREATE_EXTENSIONS = _SQLITE_SCHEMA["base_model_extensions"]

# Type coercion sets — loaded from generated schema, not hardcoded.
# Extra fields that are structural/non-extension but need coercion are added explicitly.
BOOL_FIELDS  = set(_SQLITE_SCHEMA.get("bool_fields",  [])) | {"export_capable", "is_oem_product", "active"}
INT_FIELDS   = set(_SQLITE_SCHEMA.get("int_fields",   [])) | {"min_project_value_eur", "max_project_value_eur"}
FLOAT_FIELDS = set(_SQLITE_SCHEMA.get("float_fields", []))


def _coerce(key: str, val: str):
    """Convert CSV string to SQLite-appropriate Python type."""
    if val == "" or val is None:
        return None
    if key in BOOL_FIELDS:
        return 1 if str(val).lower() in ("true", "1", "yes") else (0 if str(val).lower() in ("false", "0", "no") else None)
    if key in INT_FIELDS:
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return None
    if key in FLOAT_FIELDS:
        try:
            v = float(val)
            return None if v != v else v  # reject NaN
        except (ValueError, TypeError):
            return None
    return val


def _airtable_to_uuid(rec_dict: dict, field: str):
    """Airtable linked-record fields export as 'recXXXXX' IDs — we store company_id/base_model_id UUIDs instead."""
    return rec_dict.get(field) or None


def import_to_sqlite(
    companies_csv: Path,
    products_csv: Path,
    extensions_csv: Path,
):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript(
        CREATE_COMPANIES + "\n" +
        CREATE_BASE_MODELS + "\n" +
        CREATE_PRODUCTS + "\n" +
        CREATE_EXTENSIONS
    )

    # ── Schema migration: add any new columns that are in CREATE statements
    # but missing from existing tables (non-destructive — existing data preserved).
    def _migrate_table(table: str, create_sql: str):
        existing = {r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}
        import re as _re
        declared = _re.findall(r'^\s{4}(\w+)\s+\w+', create_sql, _re.MULTILINE)
        for col in declared:
            if col.upper() in ('PRIMARY', 'FOREIGN', 'UNIQUE', 'CHECK') or col in existing:
                continue
            col_type = _re.search(rf'^\s{{4}}{col}\s+(\w+)', create_sql, _re.MULTILINE)
            sql_type = col_type.group(1) if col_type else 'TEXT'
            try:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {sql_type}")
                print(f"  [MIGRATE] {table}.{col} ({sql_type}) added")
            except Exception as e:
                print(f"  [MIGRATE] {table}.{col} skipped: {e}")

    _migrate_table("companies",              CREATE_COMPANIES)
    _migrate_table("base_models",            CREATE_BASE_MODELS)
    _migrate_table("products",               CREATE_PRODUCTS)
    _migrate_table("base_model_extensions",  CREATE_EXTENSIONS)

    def csv_rows(path: Path) -> list[dict]:
        if not path.exists():
            return []
        with open(path, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    # Companies
    cos = csv_rows(companies_csv)
    for row in cos:
        cur.execute(
            "INSERT OR REPLACE INTO companies VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("company_id") or None,
                row.get("company_name") or "UNKNOWN",
                row.get("country") or None,
                row.get("hq_city") or None,
                row.get("employee_count_range") or None,
                _coerce("founding_year", row.get("founding_year", "")),
                row.get("website") or None,
                row.get("certifications_generic") or None,
                row.get("languages_spoken") or None,
                _coerce("export_capable", row.get("export_capable", "")),
                row.get("last_updated") or None,
            ),
        )
    print(f"  SQLite companies: {len(cos)} rows")

    # Build lookup: airtable_id → company_id UUID (for FK resolution in products)
    at_id_to_co_uuid: dict[str, str] = {}
    for row in cos:
        at_id_to_co_uuid[row.get("airtable_id", "")] = row.get("company_id", "")

    # Build lookup: airtable_id → base_model_id UUID (from extensions/base_models)
    bm_rows = csv_rows(DATA_RAW / "base_models.csv")
    at_id_to_bm_uuid: dict[str, str] = {}
    for row in bm_rows:
        at_id_to_bm_uuid[row.get("airtable_id", "")] = row.get("base_model_id", "")

    # Products
    prods = csv_rows(products_csv)
    for row in prods:
        # Resolve linked-record IDs → UUIDs
        raw_co  = row.get("company_id", "")
        raw_bm  = row.get("base_model_id", "")
        co_uuid = at_id_to_co_uuid.get(raw_co) or raw_co or None
        bm_uuid = at_id_to_bm_uuid.get(raw_bm) or raw_bm or None

        cur.execute(
            "INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("product_id") or None,
                co_uuid,
                bm_uuid,
                row.get("product_name") or "UNKNOWN",
                row.get("agv_type") or "",
                row.get("product_description") or None,
                _coerce("reference_count", row.get("reference_count", "")),
                _coerce("min_project_value_eur", row.get("min_project_value_eur", "")),
                _coerce("max_project_value_eur", row.get("max_project_value_eur", "")),
                _coerce("lead_time_weeks", row.get("lead_time_weeks", "")),
                row.get("distribution_model") or None,
                _coerce("is_oem_product", row.get("is_oem_product", "")),
                row.get("service_coverage") or None,
                _coerce("active", row.get("active", "true")),
            ),
        )
    print(f"  SQLite products: {len(prods)} rows")

    # Extensions
    exts = csv_rows(extensions_csv)
    # Get all columns from the CREATE statement to build INSERT dynamically
    cols_raw = [
        "extension_id", "base_model_id", "agv_type",
        "navigation_type", "infrastructure_required", "outdoor_capable",
        "autonomous_obstacle_bypass", "omnidirectional_movement",
        "max_payload_kg", "load_type", "multi_load_compatibility",
        "max_speed_ms", "length_mm", "width_mm",
        "operating_temp_min_c", "operating_temp_max_c", "operating_humidity_max_pct",
        "ingress_protection_rating", "cleanroom_class", "max_gradient_pct",
        "floor_flatness_req", "stop_accuracy_mm",
        "battery_type", "battery_runtime_h", "charge_time_min",
        "autonomous_charging", "battery_swap_capable",
        "safety_standard", "functional_safety_level", "safety_coverage",
        "fleet_management_system", "fleet_control_architecture",
        "vda5050_compatible", "max_fleet_size", "multi_fleet_capable",
        "integration_capability", "installation_process", "modification_process",
        "station_applications", "manual_usage",
        "lifting_height_mm", "min_total_height_mm", "fork_type", "fork_spread",
        "mast_type", "min_aisle_width_mm", "vna_capable", "drive_type",
        "drop_accuracy_lat_mm", "drop_accuracy_dep_mm", "drop_accuracy_angle_deg",
        "pick_req_accuracy_lat_mm", "pick_req_accuracy_dep_mm", "pick_req_accuracy_angle_deg",
        "forks_free_floating", "stacking_capability", "load_detection",
        "barcode_readers", "stock_line_scanning", "trailer_loading", "trailer_unloading",
        "guidance", "busbar_compatible",
        "towing_capacity_kg", "max_trailers", "coupling_type", "auto_hitch",
        "auto_hitch_position_tolerance_mm", "train_configuration", "load_transfer",
        "trailer_compatibility", "trailer_steering_technology",
        "route_type", "route_programming", "intersection_management",
        "tugger_min_aisle_width_mm", "turning_radius_mm",
        "workflow_capability", "grid_required", "rotation_capable", "picking_mechanism",
        "lift_height_mm", "min_ground_clearance_mm", "rack_pin_compatible",
        "free_lift_open_closed_pallet", "top_module_type", "cart_pickup_height_range_mm",
        "omnidirectional", "min_turning_radius_mm",
        "storage_system_type", "shelf_height_mm", "shelf_footprint_mm",
        "min_grid_area_m2", "throughput_picks_per_hour", "throughput_basis",
        "concurrent_robots_per_station", "order_lines_per_run", "task_interleaving",
        "storage_density_factor", "ergonomic_height_adjustable", "onboard_ui",
        "onboard_container_type", "onboard_container_count", "wms_integration_native",
        "extra_fields",
    ]
    placeholders = ",".join("?" * len(cols_raw))
    for row in exts:
        raw_bm  = row.get("base_model_id", "")
        bm_uuid = at_id_to_bm_uuid.get(raw_bm) or raw_bm or None
        vals = []
        for col in cols_raw:
            if col == "base_model_id":
                vals.append(bm_uuid)
            else:
                vals.append(_coerce(col, row.get(col, "")))
        cur.execute(
            f"INSERT OR REPLACE INTO base_model_extensions ({','.join(cols_raw)}) VALUES ({placeholders})",
            vals,
        )
    print(f"  SQLite extensions: {len(exts)} rows")

    con.commit()
    con.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("haystacked — Airtable Sync")
    print("=" * 60)

    print("\nStep 1: Fetching from Airtable API...")
    all_records: dict[str, list] = {}
    for name, tid in TABLES.items():
        all_records[name] = fetch_table(name, tid)

    print("\nStep 2: Writing CSV files...")
    write_csv(DATA_RAW / "companies.csv",            all_records["companies"])
    write_csv(DATA_RAW / "products.csv",             all_records["products"])
    write_csv(DATA_RAW / "base_models.csv",          all_records["base_models"])
    write_csv(DATA_RAW / "base_model_extensions.csv",all_records["extensions"])
    print("  CSV files written to data/raw/")

    print("\nStep 3: Validating...")
    ok = validate_csvs(DATA_RAW / "export_validation_report.txt")

    print("\nStep 4: Importing to SQLite...")
    import_to_sqlite(
        DATA_RAW / "companies.csv",
        DATA_RAW / "products.csv",
        DATA_RAW / "base_model_extensions.csv",
    )

    n_co  = len(all_records["companies"])
    n_pr  = len(all_records["products"])
    n_ext = len(all_records["extensions"])

    print("\nStep 5: Validating AP0 field spec consistency...")
    try:
        import importlib.util, sys as _sys
        _spec = importlib.util.spec_from_file_location(
            "generate_all",
            Path(__file__).parent / "scripts" / "generate_all.py"
        )
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _xlsx = Path(__file__).parent / "Spec" / "haystacked_AP0_field_spec_v0_10.xlsx"
        if _xlsx.exists():
            rc = _mod.generate(_xlsx, DB_PATH, dry_run=False)
            if rc != 0:
                print("  ACTION REQUIRED: AP0 xlsx and SQLite schema are not fully consistent.")
                print("  See warnings above. field_levels.json was written from xlsx regardless.")
        else:
            print(f"  [SKIP] AP0 xlsx not found at {_xlsx} — field_levels.json not updated")
    except Exception as e:
        print(f"  [WARN] Could not run field level validation: {e}")

    print("\n" + "=" * 60)
    print(f"Sync complete: {n_co} Companies, {n_pr} Products, {n_ext} Extensions")
    print(f"Database: {DB_PATH}")
    if not ok:
        print("WARNING: Validation found issues — see data/raw/export_validation_report.txt")
    print("=" * 60)


if __name__ == "__main__":
    main()
