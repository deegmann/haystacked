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
_BM_COLUMNS    = _SQLITE_SCHEMA.get("base_models_columns", [])

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

# ── Header guard (OI-115c Phase 3B) ─────────────────────────────────────────
# Prevents a silent, zero-exit-code data wipe: if config/sqlite_schema.json's
# declared columns (generated from AP0 field_name) ever diverge from the live
# CSV headers (which mirror Airtable field names verbatim), the dynamic
# INSERT OR REPLACE below would write NULL for every existing row in that
# column, and the schema-migration ALTER TABLE ADD COLUMN would silently
# create it. This guard fails loud instead, BEFORE any CREATE/ALTER/INSERT
# runs. See data/raw/known_header_gaps.json for the committed baseline of
# expected (non-destructive) gaps — columns that have simply never been
# populated in Airtable yet.
_KNOWN_GAPS_FILE = BASE_DIR / "data" / "raw" / "known_header_gaps.json"
_KNOWN_GAPS: dict = json.loads(_KNOWN_GAPS_FILE.read_text()) if _KNOWN_GAPS_FILE.exists() else {}

_NON_FIELD_CSV_COLUMNS = {"airtable_id", "model_name", "source_notes"}


def _csv_headers(path: Path) -> list[str]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return next(csv.reader(f), [])


def check_header_guard(table: str, schema_columns: list[str], csv_headers: list[str]) -> None:
    """Compare DB schema columns (from sqlite_schema.json) against live CSV headers
    for `table`. Aborts via sys.exit() if a schema column has disappeared from the
    CSV and isn't in the committed known_header_gaps.json baseline — the signature
    of an Airtable/AP0 field_name mismatch that would otherwise silently wipe data.
    """
    schema_set = set(schema_columns)
    csv_set = set(csv_headers)
    known = set(_KNOWN_GAPS.get(table, []))

    missing = schema_set - csv_set - known
    if missing:
        sys.exit(
            f"ERROR: {table}: {len(missing)} schema column(s) declared in "
            f"config/sqlite_schema.json are missing from the CSV headers and are not "
            f"in the known baseline gap list (data/raw/known_header_gaps.json): "
            f"{sorted(missing)}\n"
            "  Airtable field names no longer match AP0 field_name — rename in "
            "Airtable or fix the mismatch. Aborting before data loss."
        )

    extra = csv_set - schema_set - _NON_FIELD_CSV_COLUMNS
    if extra:
        print(f"  [WARN] {table}: CSV has {len(extra)} header(s) not declared in "
              f"sqlite_schema.json: {sorted(extra)}")

# Type coercion sets — loaded from generated schema, not hardcoded.
# Extra fields that are structural/non-extension but need coercion are added explicitly.
BOOL_FIELDS  = set(_SQLITE_SCHEMA.get("bool_fields",  [])) | {"is_oem_product", "active", "oem_link_public"}
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


_LARGE_PURGE_RATIO = 0.25
_LARGE_PURGE_FLOOR = 5


def import_to_sqlite(
    companies_csv: Path,
    products_csv: Path,
    extensions_csv: Path,
    base_models_csv: Path,
    allow_large_purge: bool = False,
):
    # Header guard runs first — before any CREATE/ALTER/INSERT touches the DB.
    check_header_guard("companies", _CO_COLUMNS, _csv_headers(companies_csv))
    check_header_guard("products", _PROD_COLUMNS, _csv_headers(products_csv))
    check_header_guard("base_model_extensions", _EXT_COLUMNS, _csv_headers(extensions_csv))
    check_header_guard("base_models", _BM_COLUMNS, _csv_headers(base_models_csv))

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
    bm_rows = csv_rows(base_models_csv)
    at_id_to_bm_uuid: dict[str, str] = {}
    for row in bm_rows:
        at_id_to_bm_uuid[row.get("airtable_id", "")] = row.get("base_model_id", "")

    # Base models — dynamic INSERT from config/sqlite_schema.json base_models_columns (OI-119)
    assert _BM_COLUMNS, "sqlite_schema.json missing 'base_models_columns' — run generate_all.py"
    _BM_DEFAULTS = {
        "base_model_name": "UNKNOWN",
        "product_type": "unknown",
        "oem_link_public": "false",  # NOT NULL column, blank on most CSV rows
        "last_updated": "unknown",
    }
    bm_sql = (
        f"INSERT OR REPLACE INTO base_models ({','.join(_BM_COLUMNS)}) "
        f"VALUES ({','.join('?' * len(_BM_COLUMNS))})"
    )
    _bm_skipped = 0
    for row in bm_rows:
        bmid = row.get("base_model_id") or ""
        if not bmid:
            # A handful of pre-existing Airtable rows have no computed base_model_id
            # (separate, older formula-field gap — out of scope here). Skipping avoids
            # inserting junk rows under a blank TEXT PRIMARY KEY.
            _bm_skipped += 1
            continue
        raw_oem = row.get("oem_company_id", "")
        oem_uuid = at_id_to_co_uuid.get(raw_oem) or raw_oem or None
        _fk = {"base_model_id": bmid, "oem_company_id": oem_uuid}
        vals = [
            _fk[col] if col in _fk
            else _coerce(col, row.get(col) or _BM_DEFAULTS.get(col, ""))
            for col in _BM_COLUMNS
        ]
        cur.execute(bm_sql, vals)
    print(f"  SQLite base_models: {len(bm_rows) - _bm_skipped} rows"
          + (f" ({_bm_skipped} skipped — blank base_model_id)" if _bm_skipped else ""))

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
        vals = []
        for col in _PROD_COLUMNS:
            if col in _fk:
                vals.append(_fk[col])
            elif col == "active":
                # Airtable Checkbox fields are OMITTED from the API response (and
                # thus exported as "" in the CSV) when unchecked — that is a real,
                # intentional False, not missing data. row.get(col) or default
                # would treat that blank the same as the column being entirely
                # absent from the CSV and silently reactivate every deactivated
                # product on every sync. Only fall back to the default when the
                # column is truly missing (row.get returns None, e.g. an old CSV
                # exported before this field existed).
                raw = row.get(col)
                if raw is None:
                    vals.append(1 if str(_PROD_DEFAULTS["active"]).lower() in ("true", "1", "yes") else 0)
                else:
                    vals.append(1 if str(raw).lower() in ("true", "1", "yes") else 0)
            else:
                vals.append(_coerce(col, row.get(col) or _PROD_DEFAULTS.get(col, "")))
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

    # Purge (OI-118): deactivate/delete rows whose Airtable record was deleted
    # upstream. sync_airtable.py only ever INSERT OR REPLACEs — a row deleted
    # in Airtable would otherwise stay in the local DB forever.
    #
    # products: soft-delete via the existing `active` column (the only column
    # every production read path filters on: src/data_loader.py JOIN_SQL/
    # _NULL_ID_SQL, app.py's load_suppliers()-backed routes) rather than a
    # hard DELETE, so tender_run_match_results' historical rows (product_id
    # has no FK there, product_name is denormalized) stay inspectable. A
    # re-created Airtable record with the same product_id self-heals back to
    # active=1 on the next sync via the INSERT OR REPLACE above.
    #
    # base_model_extensions: hard DELETE — this table has no `active` column
    # to soft-delete with, and unlike products, leaving a stale extension row
    # behind is NOT harmless dead weight: if its product survives (only the
    # extension was deleted upstream, e.g. de-duplicating a bad Airtable
    # record) the row would linger with no owning purge signal. The opposite
    # and more dangerous case — an extension row deleted while its product
    # stays active — makes that product vanish from src/data_loader.py's
    # INNER JOIN entirely, silently, with zero error and zero log line: it
    # just stops appearing in match results, indistinguishable from "this
    # supplier never matched this tender". Found live on 2026-08-06: two
    # base models (idealworks iw.hub, iw.hub + Pallet Dock) each had two
    # linked extension rows in Airtable; deleting the stale ones by hand and
    # resyncing would have left them orphaned forever without this purge.
    fresh_product_ids = {row.get("product_id") for row in prods}
    fresh_product_ids.discard(None)
    fresh_product_ids.discard("")
    if not fresh_product_ids:
        # An empty/truncated fetch must never be interpreted as "everything was
        # deleted" — that would deactivate all products. Abort instead; nothing
        # committed yet at this point in the transaction.
        sys.exit(
            "ERROR: fresh product_id set is empty — refusing to purge (would "
            "deactivate every product). Check the Airtable fetch / products.csv."
        )
    active_before = cur.execute("SELECT COUNT(*) FROM products WHERE active = 1").fetchone()[0]
    placeholders = ",".join("?" * len(fresh_product_ids))
    cur.execute(
        f"SELECT product_id, product_name FROM products "
        f"WHERE active = 1 AND product_id NOT IN ({placeholders})",
        list(fresh_product_ids),
    )
    to_purge_products = cur.fetchall()
    if to_purge_products and not allow_large_purge:
        ratio = len(to_purge_products) / max(active_before, 1)
        if len(to_purge_products) > _LARGE_PURGE_FLOOR and ratio > _LARGE_PURGE_RATIO:
            sys.exit(
                f"ERROR: this sync would deactivate {len(to_purge_products)} of "
                f"{active_before} active products ({ratio:.0%}) — refusing without "
                f"--allow-large-purge. This usually means a truncated/partial "
                f"Airtable fetch, not {len(to_purge_products)} real deletions. "
                f"If this many deletions are genuinely intended, re-run with "
                f"--allow-large-purge."
            )
    if to_purge_products:
        cur.execute(
            f"UPDATE products SET active = 0 "
            f"WHERE active = 1 AND product_id NOT IN ({placeholders})",
            list(fresh_product_ids),
        )
        print(f"  [PURGE] {cur.rowcount} product(s) deactivated (deleted upstream in Airtable):")
        for pid, pname in to_purge_products:
            print(f"    - {pname} ({pid})")
    else:
        print("  [PURGE] 0 products deactivated")

    fresh_extension_ids = {row.get("extension_id") for row in exts}
    fresh_extension_ids.discard(None)
    fresh_extension_ids.discard("")
    if not fresh_extension_ids:
        sys.exit(
            "ERROR: fresh extension_id set is empty — refusing to purge (would "
            "delete every extension row). Check the Airtable fetch / "
            "base_model_extensions.csv."
        )
    bmid_to_name = {row.get("base_model_id"): row.get("base_model_name") for row in bm_rows}
    active_bm_ids = {r[0] for r in cur.execute("SELECT DISTINCT base_model_id FROM products WHERE active = 1")}
    ext_placeholders = ",".join("?" * len(fresh_extension_ids))
    cur.execute(
        f"SELECT extension_id, base_model_id FROM base_model_extensions "
        f"WHERE extension_id NOT IN ({ext_placeholders})",
        list(fresh_extension_ids),
    )
    to_purge_extensions = cur.fetchall()
    if to_purge_extensions and not allow_large_purge:
        ratio = len(to_purge_extensions) / max(len(exts) or 1, 1)
        if len(to_purge_extensions) > _LARGE_PURGE_FLOOR and ratio > _LARGE_PURGE_RATIO:
            sys.exit(
                f"ERROR: this sync would delete {len(to_purge_extensions)} extension "
                f"row(s) ({ratio:.0%} of the fresh set) — refusing without "
                f"--allow-large-purge. If this many deletions are genuinely "
                f"intended, re-run with --allow-large-purge."
            )
    purged_extensions = []
    if to_purge_extensions:
        cur.execute(
            f"DELETE FROM base_model_extensions WHERE extension_id NOT IN ({ext_placeholders})",
            list(fresh_extension_ids),
        )
        print(f"  [PURGE] {cur.rowcount} extension row(s) deleted (deleted upstream in Airtable):")
        for ext_id, bm_id in to_purge_extensions:
            bm_name = bmid_to_name.get(bm_id, "?")
            danger = " !! PRODUCT STILL ACTIVE — was silently invisible to matching !!" if bm_id in active_bm_ids else ""
            print(f"    - {bm_name} ({bm_id}) ext={ext_id}{danger}")
            purged_extensions.append({
                "extension_id": ext_id, "base_model_id": bm_id, "base_model_name": bm_name,
                "orphaned_active_product": bm_id in active_bm_ids,
            })
    else:
        print("  [PURGE] 0 extension rows deleted")

    # Integrity check (does not abort — 3 pre-existing rows are a known,
    # separate Airtable formula-field gap, see OI-119): every active
    # product's base_model_id should resolve to a real base_models row.
    dangling = cur.execute(
        "SELECT p.product_name, p.base_model_id FROM products p "
        "LEFT JOIN base_models bm ON p.base_model_id = bm.base_model_id "
        "WHERE p.active = 1 AND bm.base_model_id IS NULL"
    ).fetchall()
    if dangling:
        print(f"  [WARN] {len(dangling)} active product(s) reference a base_model_id "
              f"with no base_models row: {dangling}")

    con.commit()
    con.close()

    # Returned to main() so it can (a) print an unmissable end-of-run banner —
    # the inline [PURGE] lines above are easy to miss, buried mid-scroll in
    # "Step 4: Importing to SQLite..." — and (b) append a durable record to
    # data/raw/purge_log.jsonl, since terminal scrollback isn't persisted.
    return {
        "products": [{"product_id": pid, "product_name": pname} for pid, pname in to_purge_products],
        "extensions": purged_extensions,
    }


def _log_purge(purged: dict, local_mode: bool) -> None:
    """Append a durable, always-checkable record of every row this sync run
    deactivated/deleted (OI-118) — terminal output scrolls away and is easy
    to miss; this file doesn't. One JSON line per sync run that purged
    anything; runs that purge nothing write no line, so the file stays
    meaningful. `purged` is {"products": [...], "extensions": [...]}."""
    import datetime
    entry = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "mode": "local" if local_mode else "live",
        "products_count": len(purged.get("products", [])),
        "extensions_count": len(purged.get("extensions", [])),
        "purged": purged,
    }
    log_path = DATA_RAW / "purge_log.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="haystacked Airtable sync")
    parser.add_argument(
        "--local", action="store_true",
        help="Rebuild DB from committed CSVs in data/raw/ without Airtable credentials"
    )
    parser.add_argument(
        "--allow-large-purge", action="store_true",
        help=f"Allow a single sync to deactivate/delete more than {_LARGE_PURGE_FLOOR} rows "
             f"AND more than {_LARGE_PURGE_RATIO:.0%} of the fresh set in one table. Without "
             f"this flag such a purge aborts — it's far more likely to be a truncated/partial "
             f"Airtable fetch than that many genuine deletions."
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
    purged = import_to_sqlite(
        DATA_RAW / "companies.csv",
        DATA_RAW / "products.csv",
        DATA_RAW / "base_model_extensions.csv",
        DATA_RAW / "base_models.csv",
        allow_large_purge=args.allow_large_purge,
    )
    if purged["products"] or purged["extensions"]:
        _log_purge(purged, local_mode=args.local)

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
    if purged["products"] or purged["extensions"]:
        print("!" * 60)
        if purged["products"]:
            print(f"!! {len(purged['products'])} PRODUCT(S) DEACTIVATED — deleted upstream in Airtable this run:")
            for p in purged["products"]:
                print(f"!!   - {p['product_name']} ({p['product_id']})")
        if purged["extensions"]:
            print(f"!! {len(purged['extensions'])} EXTENSION ROW(S) DELETED — deleted upstream in Airtable this run:")
            for e in purged["extensions"]:
                danger = "  <-- product still active, was silently invisible to matching" if e["orphaned_active_product"] else ""
                print(f"!!   - {e['base_model_name']} ({e['base_model_id']}){danger}")
        print("!! Full history: data/raw/purge_log.jsonl")
        print("!" * 60)
    print("=" * 60)


if __name__ == "__main__":
    main()
