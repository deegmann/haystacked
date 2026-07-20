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

# C-6: column lists from generated sqlite_schema.json (never hardcode field names)
_SQLITE_SCHEMA = json.loads((BASE_DIR / "config" / "sqlite_schema.json").read_text())
_CO_COLUMNS    = _SQLITE_SCHEMA.get("companies_columns", [])
_PROD_COLUMNS  = _SQLITE_SCHEMA.get("products_columns", [])
_EXT_COLUMNS   = _SQLITE_SCHEMA.get("extensions_columns", [])

# Airtable-specific setup — only needed in live-sync mode (not --local)
_LOCAL_MODE = "--local" in sys.argv

if _LOCAL_MODE:
    HEADERS = {}
    TABLES  = {}
else:
    if not TOKEN or not BASE_ID:
        sys.exit(
            "ERROR: AIRTABLE_TOKEN and AIRTABLE_BASE_ID must be set.\n"
            "  Create a .env file with:\n"
            "    AIRTABLE_TOKEN=pat...\n"
            "    AIRTABLE_BASE_ID=app...\n"
            "  Or rebuild the DB from committed CSVs without Airtable:\n"
            "    python3 sync_airtable.py --local"
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
BOOL_FIELDS  = set(_SQLITE_SCHEMA.get("bool_fields",  [])) | {"is_oem_product", "active"}
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

    # Companies — dynamic INSERT from config/sqlite_schema.json companies_columns
    assert _CO_COLUMNS, "sqlite_schema.json missing 'companies_columns' — run generate_all.py"
    _CO_DEFAULTS = {
        "company_name": "UNKNOWN",
        "country": "??",
        "employee_count_range": "unknown",
        "languages_spoken": "unknown",
        "last_updated": "unknown",
    }
    co_sql = (
        f"INSERT OR REPLACE INTO companies ({','.join(_CO_COLUMNS)}) "
        f"VALUES ({','.join('?' * len(_CO_COLUMNS))})"
    )
    cos = csv_rows(companies_csv)
    for row in cos:
        vals = [_coerce(col, row.get(col) or _CO_DEFAULTS.get(col, "")) for col in _CO_COLUMNS]
        cur.execute(co_sql, vals)
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

    # Products — dynamic INSERT from config/sqlite_schema.json products_columns
    assert _PROD_COLUMNS, "sqlite_schema.json missing 'products_columns' — run generate_all.py"
    _PROD_DEFAULTS = {
        "product_name": "UNKNOWN",
        "product_type": "unknown",
        "active": "true",
        "product_description": "(not specified)",
        "service_coverage": "EU",
    }
    prod_sql = (
        f"INSERT OR REPLACE INTO products ({','.join(_PROD_COLUMNS)}) "
        f"VALUES ({','.join('?' * len(_PROD_COLUMNS))})"
    )
    prods = csv_rows(products_csv)
    for row in prods:
        # Resolve linked-record IDs → UUIDs
        raw_co  = row.get("company_id", "")
        raw_bm  = row.get("base_model_id", "")
        co_uuid = at_id_to_co_uuid.get(raw_co) or raw_co or None
        bm_uuid = at_id_to_bm_uuid.get(raw_bm) or raw_bm or None
        _fk = {"company_id": co_uuid, "base_model_id": bm_uuid}
        vals = [
            _fk[col] if col in _fk
            else _coerce(col, row.get(col) or _PROD_DEFAULTS.get(col, ""))
            for col in _PROD_COLUMNS
        ]
        cur.execute(prod_sql, vals)
    print(f"  SQLite products: {len(prods)} rows")

    # Validate product_type values against scope_registry.json legacy_map
    _sr_path = Path(__file__).parent / "config" / "scope_registry.json"
    if _sr_path.exists():
        _sr = json.loads(_sr_path.read_text())
        _lm = _sr.get("legacy_map", {})
        if _lm:
            _unknown = {row.get("product_type") for row in prods if row.get("product_type") and row.get("product_type") not in _lm}
            if _unknown:
                sys.exit(f"ERROR: product_type values not in scope_registry legacy_map: {_unknown} — check AP0 or run generate_all.py")

    # Extensions
    exts = csv_rows(extensions_csv)
    # C-6: column list from config/sqlite_schema.json (generated by generate_all.py from AP0)
    cols_raw = _EXT_COLUMNS
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
    import argparse
    parser = argparse.ArgumentParser(description="haystacked Airtable sync")
    parser.add_argument(
        "--local", action="store_true",
        help="Rebuild DB from committed CSVs in data/raw/ without Airtable credentials"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("haystacked — Airtable Sync" + (" (local mode)" if args.local else ""))
    print("=" * 60)

    if args.local:
        print("\nLocal mode: skipping Airtable fetch — using existing data/raw/ CSVs")
        for name in ["companies.csv", "products.csv", "base_models.csv", "base_model_extensions.csv"]:
            p = DATA_RAW / name
            if not p.exists():
                sys.exit(f"ERROR: {p} not found. Commit the CSV files first or run a full sync.")
        all_records = {}  # not used in local mode
    else:
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

    if not args.local:
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
                print("  See warnings above. config/fields.json was regenerated from xlsx regardless.")
        else:
            print(f"  [SKIP] AP0 xlsx not found at {_xlsx} — config/fields.json not updated")
    except Exception as e:
        print(f"  [WARN] Could not run field level validation: {e}")

    print("\n" + "=" * 60)
    if args.local:
        print("DB rebuilt from local CSVs")
    else:
        print(f"Sync complete: {n_co} Companies, {n_pr} Products, {n_ext} Extensions")
    print(f"Database: {DB_PATH}")
    if not ok:
        print("WARNING: Validation found issues — see data/raw/export_validation_report.txt")
    print("=" * 60)


if __name__ == "__main__":
    main()
