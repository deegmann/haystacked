"""
generate_all.py — Single Source of Truth pipeline

Reads TWO xlsx files and generates ALL runtime config:
  AP0_[industry].xlsx        — industry-specific (fields, operators, scoring weights
                                inline, vehicle types, extraction hints in description col)
  platform_config.xlsx       — cross-industry (NACE codes, basic extraction schema,
                                platform scope definition)

Architecture principle:
  NOTHING industry-specific is hardcoded in Python or .txt files.
  All fields, prompts, matching rules, vehicle types, scoring weights come from AP0.xlsx.
  Cross-industry config (NACE, basic extraction schema, platform scope) comes from
  platform_config.xlsx. When a new industry is added, only the xlsx files change —
  no Python code changes are needed.

Usage:
    python3 scripts/generate_all.py [--xlsx PATH] [--platform PATH] [--db PATH] [--dry-run]

Generated files:
    config/field_levels.json       — KO/COND_KO/Scoring/Context + operators
    config/vehicle_types.json      — _VT_MAP, VNA detection, keyword fallback
    config/scoring_weights.json    — scoring weights (inline from AP0 field sheets)
    config/nace_codes.json         — NACE Prio-1 list + platform scope
    config/sqlite_schema.json      — CREATE TABLE SQL generated from AP0 Entity Model
    config/plausibility.json       — LLM value plausibility ranges per extraction field
    config/prompts/*.txt           — all LLM prompt files (generated, never edit manually)
    config/ap0_checksum.txt        — MD5 for startup auto-regen

All extraction fields come from AP0 xlsx via the "Tender JSON Key" column.
    No extraction-only fields remain — all are anchored in AP0:
      required_vehicle_type  ← agv_type (SHARED, K.O.)
      required_navigation    ← navigation_type (SHARED, Cond. K.O.)
      required_weight_capacity_kg ← max_payload_kg (SHARED, K.O.)
      required_max_lift_height_m  ← lifting_height_mm (Forklift, K.O.)
      required_min_aisle_width_m  ← min_aisle_width_mm (Forklift, K.O.)
      required_outdoor       ← outdoor_capable (SHARED, Cond. K.O.)
      required_temp_min_c    ← operating_temp_min_c (SHARED, Cond. K.O.)
      required_clean_room    ← cleanroom_class (SHARED, Cond. K.O.)
      required_load_types    ← load_type (SHARED, K.O.)
      required_towing_capacity_kg ← towing_capacity_kg (Tugger, K.O.)
      required_integration   ← integration_capability (SHARED, Scoring)
      required_station_types ← station_applications (SHARED, Cond. K.O.)
"""

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

try:
    import openpyxl
except ImportError:
    sys.exit("openpyxl not installed: pip3 install openpyxl")

ROOT             = Path(__file__).parent.parent
DEFAULT_XLSX     = ROOT / "Spec" / "haystacked_AP0_field_spec_v0_10.xlsx"
DEFAULT_PLATFORM = ROOT / "Spec" / "haystacked_platform_config.xlsx"
DEFAULT_DB       = ROOT / "data" / "haystacked.db"
CONFIG_DIR   = ROOT / "config"
PROMPTS_DIR  = CONFIG_DIR / "prompts"

LEVEL_MAP = {"K.O.": "KO", "Cond. K.O.": "COND_KO", "Scoring": "SCORING", "Context": "CONTEXT"}
VALID_OPS  = {"KO_IF_LT","KO_IF_GT","KO_IF_NEQ","KO_BOOL_REQUIRED","KO_BOOL_EXCLUSIVE","KO_SUBSET"}
DATA_SHEETS = ["SHARED – All AGV Types", "Forklift AGV", "Tugger AGV", "Mobile AMR"]

# AP0 Data Type → SQLite column type mapping
SQLITE_TYPE_MAP = {
    "Boolean": "INTEGER", "Boolean (derived)": "INTEGER",
    "Integer": "INTEGER",
    "Real": "REAL", "Float": "REAL",
    "Dropdown": "TEXT", "Multi-Select": "TEXT",
    "Text": "TEXT", "Long Text": "TEXT",
    "UUID": "TEXT", "UUID (Linked)": "TEXT",
    "ISO 3166": "TEXT", "Date": "TEXT", "URL": "TEXT",
}

SQLITE_SKIP = {
    "extension_id","base_model_id","company_id","product_id","company_name","product_name",
    "product_description","base_model_name","oem_company_id","oem_link_public","website",
    "last_updated","export_capable","is_oem_product","active","extra_fields",
    "pick_req_accuracy_lat_mm_amr","pick_req_accuracy_dep_mm_amr","pick_req_accuracy_angle_deg_amr",
    "drop_accuracy_lat_mm_amr","drop_accuracy_dep_mm_amr","drop_accuracy_angle_deg_amr",
    "min_project_value_eur","max_project_value_eur",
}

# Plausibility ranges for LLM-extracted values.
# Format: json_key → (min, max, unit, label, mm_to_m_conversion)
# mm_to_m_conversion: True if value > 10 should be auto-converted from mm to m.
# These ranges are used in validate_agv_criteria() in app.py.
# Stored in config/plausibility.json so app.py never hardcodes domain knowledge.
PLAUSIBILITY_RANGES = {
    "required_weight_capacity_kg": (100,   50_000, "kg",  "Traglast",       False),
    "required_max_speed_ms":       (0.3,   5.0,    "m/s", "Geschwindigkeit", False),
    "required_min_aisle_width_m":  (0.5,   5.0,    "m",   "Gangbreite",      True),
    "required_max_lift_height_m":  (0.5,   30.0,   "m",   "Hubhöhe",         True),
    "required_temp_min_c":         (-40,   30,     "°C",  "Temp. min",       False),
    "required_temp_max_c":         (0,     60,     "°C",  "Temp. max",       False),
    "required_quantity":           (1,     10_000, "Stk", "Anzahl",          False),
}


# ── Readers ───────────────────────────────────────────────────────────────────

def _rows(ws, min_row=1):
    return list(ws.iter_rows(min_row=min_row, values_only=True))

def _find_header(rows, key="Field Name"):
    for i, row in enumerate(rows):
        if row and row[0] == key:
            return i, {v: j for j, v in enumerate(row) if v}
    return None, {}


def read_field_levels(wb) -> dict:
    fields = {}
    for sheet in DATA_SHEETS:
        if sheet not in wb.sheetnames:
            print(f"  [WARN] Sheet missing: {sheet}")
            continue
        rows = _rows(wb[sheet])
        hi, cols = _find_header(rows)
        if hi is None:
            continue
        col_level   = cols.get("Level")
        col_op      = cols.get("Matching Operator")
        col_tkey    = cols.get("Tender JSON Key")
        col_dtype   = cols.get("Data Type")
        col_allowed = cols.get("Allowed Values / Unit")
        for row in rows[hi+1:]:
            fname = row[0]
            if not fname or str(fname).startswith("──"):
                continue
            raw_level = row[col_level] if col_level is not None else None
            level = LEVEL_MAP.get(str(raw_level).strip()) if raw_level else None
            if not level:
                continue
            entry = {"level": level}
            raw_dtype = str(row[col_dtype]).strip() if col_dtype is not None and col_dtype < len(row) and row[col_dtype] else ""
            if raw_dtype:
                entry["data_type"] = raw_dtype
            if col_op is not None and col_op < len(row) and row[col_op]:
                op = str(row[col_op]).strip()
                if op in VALID_OPS:
                    entry["operator"] = op
                else:
                    print(f"  [WARN] Unknown operator '{op}' for '{fname}'")
            if col_tkey is not None and col_tkey < len(row) and row[col_tkey]:
                entry["tender_key"] = str(row[col_tkey]).strip()
            # Store allowed values for Dropdown/Multi-Select fields as a validation list
            if raw_dtype in ("Dropdown", "Multi-Select") and col_allowed is not None and col_allowed < len(row) and row[col_allowed]:
                raw_av = str(row[col_allowed]).strip()
                # Parse "A | B | C" into ["A","B","C"], skip pure unit strings
                av_list = [v.strip() for v in raw_av.split("|") if v.strip() and v.strip() not in ("…", "")]
                if av_list:
                    entry["allowed_values"] = av_list
            if level in ("KO","COND_KO") and "operator" not in entry:
                print(f"  [WARN] '{fname}' is {level} but has no operator")
            if level in ("KO","COND_KO") and "operator" in entry and "tender_key" not in entry:
                print(f"  [WARN] '{fname}' has operator but no Tender JSON Key")
            if fname not in fields:
                fields[str(fname)] = entry
    return fields


def read_vehicle_types(wb) -> dict:
    """Returns structured vehicle type config."""
    if "Vehicle Types" not in wb.sheetnames:
        print("  [WARN] 'Vehicle Types' sheet missing — vehicle_types.json will be empty")
        return {}
    rows = _rows(wb["Vehicle Types"], min_row=2)
    hi, cols = _find_header(rows, "LLM Output")
    if hi is None:
        print("  [WARN] No header in Vehicle Types sheet")
        return {}

    vt_map = {}         # llm_output_lower → canonical
    vna_subtypes = []   # list of llm_output_lower values
    overrides = []      # list of {regex, canonical, vna}
    keyword_map = {}    # canonical → list of keywords
    llm_guide = []      # list of {name, description, key_indicators} for prompt

    c_llm    = cols.get("LLM Output", 0)
    c_canon  = cols.get("Canonical Type", 1)
    c_vna    = cols.get("VNA Subtype", 2)
    c_kw     = cols.get("Fallback Keywords (|sep)", 3)
    c_regex  = cols.get("Text Override Regex", 4)
    c_desc   = cols.get("LLM Description", 5)
    c_ind    = cols.get("LLM Key Indicators", 6)

    for row in rows[hi+1:]:
        if not row or not row[c_llm]:
            continue
        llm_out  = str(row[c_llm]).strip()
        canon    = str(row[c_canon]).strip() if row[c_canon] else ""
        is_vna   = str(row[c_vna]).strip().lower() == "yes" if row[c_vna] else False
        kw_raw   = str(row[c_kw]).strip() if c_kw < len(row) and row[c_kw] else ""
        regex    = str(row[c_regex]).strip() if c_regex < len(row) and row[c_regex] else ""
        desc     = str(row[c_desc]).strip() if c_desc < len(row) and row[c_desc] else ""
        ind      = str(row[c_ind]).strip()  if c_ind  < len(row) and row[c_ind]  else ""

        if canon:
            vt_map[llm_out.lower()] = canon
        if is_vna:
            vna_subtypes.append(llm_out.lower())
        if regex and canon:
            overrides.append({"regex": regex, "canonical": canon, "vna": is_vna})
        if kw_raw and canon:
            kws = [k.strip() for k in kw_raw.split("|") if k.strip()]
            keyword_map.setdefault(canon, []).extend(kws)
        if desc:
            llm_guide.append({"name": llm_out, "description": desc, "key_indicators": ind})

    return {
        "vt_map":       vt_map,
        "vna_subtypes": vna_subtypes,
        "text_overrides": overrides,
        "keyword_map":  {k: list(dict.fromkeys(v)) for k, v in keyword_map.items()},
        "llm_guide":    llm_guide,
    }


def read_scoring_weights(wb) -> dict:
    """Read scoring weights from inline 'Scoring Weight' column in each sheet."""
    result = {"default": {}, "forklift_specific": {}, "tugger_specific": {}, "amr_specific": {}}
    sheet_map = {
        "SHARED – All AGV Types": "default",
        "Forklift AGV": "forklift_specific",
        "Tugger AGV": "tugger_specific",
        "Mobile AMR": "amr_specific",
    }
    def _int(v):
        try: return int(v) if v is not None and v != '' else 0
        except: return 0

    for sheet, bucket in sheet_map.items():
        if sheet not in wb.sheetnames: continue
        rows = _rows(wb[sheet])
        hi, cols = _find_header(rows)
        if hi is None: continue
        c_field = cols.get("Field Name", 0)
        c_weight = cols.get("Scoring Weight")
        if c_weight is None: continue
        for row in rows[hi+1:]:
            if not row or not row[c_field]: continue
            fname = str(row[c_field]).strip()
            if fname.startswith("──"): continue
            w = _int(row[c_weight] if c_weight < len(row) else None)
            if w:
                result[bucket][fname] = w
    return result


def read_extraction_schema(wb) -> list:
    """Build extraction schema from AP0 field sheets:
    - 'Tender JSON Key' column gives the JSON key
    - 'Description' column gives the LLM extraction hint
    - 'Mand.' column indicates if mandatory
    Supplemented by hardcoded extraction-only fields (process, wms, etc.)
    that have no DB counterpart.
    """
    schema = []
    seen = set()

    for sheet in DATA_SHEETS:
        if sheet not in wb.sheetnames: continue
        rows = _rows(wb[sheet])
        hi, cols = _find_header(rows)
        if hi is None: continue
        c_field = cols.get("Field Name", 0)
        c_jk    = cols.get("Tender JSON Key")
        c_desc  = cols.get("Description — what it is · where to find it · what it implies")
        c_mand  = cols.get("Mand.")
        if c_jk is None: continue

        for row in rows[hi+1:]:
            if not row or not row[c_field]: continue
            fname = str(row[c_field]).strip()
            if fname.startswith("──"): continue
            jk = str(row[c_jk]).strip() if c_jk < len(row) and row[c_jk] else ""
            if not jk or jk in seen: continue
            seen.add(jk)
            hint = str(row[c_desc]).strip() if c_desc is not None and c_desc < len(row) and row[c_desc] else ""
            mand = bool(row[c_mand]) if c_mand is not None and c_mand < len(row) else False
            schema.append({"key": jk, "db_field": fname, "mandatory": mand, "hint": hint})

    # All extraction fields now come from AP0 xlsx via the Tender JSON Key column:
    #   required_vehicle_type  ← agv_type         (SHARED, K.O.)
    #   required_navigation    ← navigation_type   (SHARED, Cond. K.O.)
    #   required_weight_capacity_kg ← max_payload_kg (SHARED, K.O.)
    #   required_max_lift_height_m  ← lifting_height_mm (Forklift, K.O.)
    #   required_min_aisle_width_m  ← min_aisle_width_mm (Forklift, K.O.)
    #   required_outdoor       ← outdoor_capable   (SHARED, Cond. K.O.)
    #   required_temp_min_c    ← operating_temp_min_c (SHARED, Cond. K.O.)
    #   required_clean_room    ← cleanroom_class   (SHARED, Cond. K.O.)
    #   required_load_types    ← load_type         (SHARED, K.O.)
    #   required_towing_capacity_kg ← towing_capacity_kg (Tugger, K.O.)
    #   required_integration   ← integration_capability (SHARED, Scoring)
    #   required_station_types ← station_applications  (SHARED, Cond. K.O.)
    #
    # Dropped (Option B — not matchable, covered by basic extraction summary):
    #   required_process            — informational only, no supplier field
    #   required_wms_integration    — replaced by required_integration (richer)
    #   required_conveyor_integration — replaced by required_station_types (richer)
    #   required_quantity           — rarely stated, no supplier field
    #   agv_notes                   — covered by summary from basic extraction

    return schema


def read_sqlite_schema(wb) -> dict:
    """Generate CREATE TABLE SQL statements from AP0 Entity Model + AGV-type sheets.

    Returns dict:
      {
        "companies":             CREATE TABLE SQL,
        "products":              CREATE TABLE SQL,
        "base_models":           CREATE TABLE SQL,
        "base_model_extensions": CREATE TABLE SQL,
        "bool_fields":  [list of boolean field names for sync_airtable coercion],
        "int_fields":   [list],
        "float_fields": [list],
      }
    """
    # ── Parse Entity Model for L1 / L2 / L3 structural fields ─────────────────
    ws = wb["Entity Model"] if "Entity Model" in wb.sheetnames else None
    l1, l2, l3 = [], [], []   # list of (name, sqlite_type, mandatory, desc, notes)

    if ws:
        rows = list(ws.iter_rows(values_only=True))
        current = None
        for row in rows:
            if not any(row):
                continue
            cells = [str(c).strip() if c else "" for c in row]
            r1 = cells[1]  # field/header text lives in column B

            if "L1 · Company" in r1:
                current = "L1"; continue
            elif "L2 · Product" in r1:
                current = "L2"; continue
            elif "L3 · OEM Base Model" in r1:
                current = "L3"; continue
            elif r1 in ("Field", "") or r1.startswith("→") or r1.startswith("Reading") \
                    or "Three-Layer" in r1 or "Matching happens" in r1 \
                    or "Company (1)" in r1 or "L1 (seller)" in r1:
                continue

            if current and r1 and cells[2]:
                entry = (
                    r1,                                          # name
                    SQLITE_TYPE_MAP.get(cells[2], "TEXT"),       # sqlite type
                    cells[4] == "✓",                             # mandatory
                    cells[3][:120] if cells[3] else "",          # description
                    cells[5][:80]  if cells[5] else "",          # notes
                )
                if current == "L1":
                    l1.append(entry)
                elif current == "L2":
                    l2.append(entry)
                elif current == "L3":
                    l3.append(entry)

    def _is_pk(desc: str) -> bool:
        return "Primary key" in desc

    def _is_fk(desc: str) -> bool:
        return desc.startswith("FK →")

    def _col_sql(name, sql_type, mandatory, desc, notes) -> str:
        constraints = ""
        if _is_pk(desc):
            constraints = " PRIMARY KEY"
        elif mandatory:
            constraints = " NOT NULL"
        return f"    {name:<45} {sql_type}{constraints}"

    def _fk_sql(name, target_table, target_col="rowid") -> str:
        fk_map = {
            "company_id":    "companies(company_id)",
            "base_model_id": "base_models(base_model_id)",
            "oem_company_id": "companies(company_id)",
        }
        ref = fk_map.get(name, f"{target_table}({name})")
        return f"    FOREIGN KEY ({name}) REFERENCES {ref}"

    # ── companies ──────────────────────────────────────────────────────────────
    co_lines = ["CREATE TABLE IF NOT EXISTS companies ("]
    for entry in l1:
        co_lines.append(_col_sql(*entry) + ",")
    # Remove trailing comma from last real column, add closing paren
    co_lines[-1] = co_lines[-1].rstrip(",")
    co_lines.append(");")
    companies_sql = "\n".join(co_lines)

    # ── products ───────────────────────────────────────────────────────────────
    pr_lines = ["CREATE TABLE IF NOT EXISTS products ("]
    fk_clauses = []
    for entry in l2:
        name, sql_type, mandatory, desc, notes = entry
        if name == "is_oem_product":
            mandatory = False  # derived field, never mandatory in insert
        pr_lines.append(_col_sql(*entry) + ",")
        if _is_fk(desc):
            fk_clauses.append(_fk_sql(name, ""))
    for fk in fk_clauses:
        pr_lines.append(fk + ",")
    pr_lines[-1] = pr_lines[-1].rstrip(",")
    pr_lines.append(");")
    products_sql = "\n".join(pr_lines)

    # ── base_models ────────────────────────────────────────────────────────────
    bm_lines = ["CREATE TABLE IF NOT EXISTS base_models ("]
    bm_fk = []
    for entry in l3:
        name, sql_type, mandatory, desc, notes = entry
        if name == "→ all AP0 fields":
            continue  # placeholder row, not a real field
        bm_lines.append(_col_sql(*entry) + ",")
        if _is_fk(desc):
            bm_fk.append(_fk_sql(name, ""))
    for fk in bm_fk:
        bm_lines.append(fk + ",")
    bm_lines[-1] = bm_lines[-1].rstrip(",")
    bm_lines.append(");")
    base_models_sql = "\n".join(bm_lines)

    # ── base_model_extensions: read all fields from AGV-type sheets ───────────
    ext_fields   = []   # list of (name, sqlite_type)
    ext_seen     = {"extension_id", "base_model_id", "agv_type", "extra_fields"}
    bool_fields  = []
    int_fields   = []
    float_fields = []

    for sheet in DATA_SHEETS:
        if sheet not in wb.sheetnames:
            continue
        rows = _rows(wb[sheet])
        hi, cols = _find_header(rows)
        if hi is None:
            continue
        c_dt   = cols.get("Data Type")
        c_mand = cols.get("Mand.")
        if c_dt is None:
            continue
        for row in rows[hi + 1:]:
            if not row or not row[0]:
                continue
            fname = str(row[0]).strip()
            if fname.startswith("──") or fname in ext_seen:
                continue
            ext_seen.add(fname)
            raw_dt = str(row[c_dt]).strip() if c_dt < len(row) and row[c_dt] else "Text"
            sql_t  = SQLITE_TYPE_MAP.get(raw_dt, "TEXT")
            ext_fields.append((fname, sql_t))
            if raw_dt in ("Boolean", "Boolean (derived)"):
                bool_fields.append(fname)
            elif raw_dt in ("Integer",):
                int_fields.append(fname)
            elif raw_dt in ("Real", "Float"):
                float_fields.append(fname)

    ext_lines = [
        "CREATE TABLE IF NOT EXISTS base_model_extensions (",
        "    extension_id                    TEXT PRIMARY KEY,",
        "    base_model_id                   TEXT NOT NULL,",
        "    agv_type                        TEXT NOT NULL,",
    ]
    for fname, sql_t in ext_fields:
        ext_lines.append(f"    {fname:<45} {sql_t},")
    ext_lines.append("    extra_fields                    TEXT,")
    ext_lines.append("    FOREIGN KEY (base_model_id) REFERENCES base_models(base_model_id)")
    ext_lines.append(");")
    extensions_sql = "\n".join(ext_lines)

    return {
        "companies":             companies_sql,
        "products":              products_sql,
        "base_models":           base_models_sql,
        "base_model_extensions": extensions_sql,
        "bool_fields":           sorted(bool_fields),
        "int_fields":            sorted(int_fields),
        "float_fields":          sorted(float_fields),
    }


def build_plausibility_config() -> dict:
    """Return plausibility config from the module-level PLAUSIBILITY_RANGES dict.
    Written to config/plausibility.json so app.py reads it from config, not hardcoded.
    Format per key: {min, max, unit, label, mm_to_m}
    """
    result = {}
    for key, (lo, hi, unit, label, mm_to_m) in PLAUSIBILITY_RANGES.items():
        result[key] = {
            "min":     lo,
            "max":     hi,
            "unit":    unit,
            "label":   label,
            "mm_to_m": mm_to_m,
        }
    return result


def read_platform(platform_path: Path) -> dict:
    """Read platform_config.xlsx — cross-industry: NACE, basic schema, scope."""
    if not platform_path.exists():
        print(f"  [WARN] platform_config not found: {platform_path}")
        return {"scope_in": "", "scope_out": "", "codes": [], "basic_schema": []}

    wb = openpyxl.load_workbook(str(platform_path), read_only=True, data_only=True)

    # Platform scope
    scope_in = scope_out = ""
    if "Platform Scope" in wb.sheetnames:
        for row in _rows(wb["Platform Scope"]):
            if not row: continue
            if row[0] and "In Scope" in str(row[0]):
                scope_in = str(row[1]).strip() if len(row) > 1 and row[1] else ""
            if row[0] and "Out of Scope" in str(row[0]):
                scope_out = str(row[1]).strip() if len(row) > 1 and row[1] else ""

    # NACE codes
    codes = []
    if "NACE Codes" in wb.sheetnames:
        header_found = False
        for row in _rows(wb["NACE Codes"]):
            if not row: continue
            if row[0] == "NACE Code": header_found = True; continue
            if not header_found: continue
            code = str(row[0]).strip() if row[0] else ""
            name = str(row[1]).strip() if len(row) > 1 and row[1] else ""
            prio = str(row[2]).strip() if len(row) > 2 and row[2] else ""
            hint = str(row[3]).strip() if len(row) > 3 and row[3] else ""
            if code and name and "Prio 1" in prio:
                entry = f"{code}: {name}"
                if hint and hint != "nan": entry += f" | {hint[:70]}"
                codes.append(entry)

    # Basic extraction schema
    basic_schema = []
    if "Basic Extraction Schema" in wb.sheetnames:
        rows = _rows(wb["Basic Extraction Schema"], min_row=2)
        hi, cols = _find_header(rows, "JSON Key")
        if hi is not None:
            c_key  = cols.get("JSON Key", 0)
            c_type = cols.get("Data Type", 1)
            c_mand = cols.get("Mandatory?", 2)
            c_hint = cols.get("LLM Extraction Hint", 3)
            c_def  = cols.get("JSON Default", 4)
            for row in rows[hi+1:]:
                if not row or not row[c_key]: continue
                key  = str(row[c_key]).strip()
                hint = str(row[c_hint]).strip() if c_hint < len(row) and row[c_hint] else ""
                mand = str(row[c_mand]).strip().lower() == "yes" if c_mand < len(row) and row[c_mand] else False
                dflt = str(row[c_def]).strip() if c_def < len(row) and row[c_def] else "null"
                basic_schema.append({"key": key, "mandatory": mand, "hint": hint, "default": dflt})

    return {"scope_in": scope_in, "scope_out": scope_out, "codes": codes, "basic_schema": basic_schema}


# ── Prompt builders ───────────────────────────────────────────────────────────

def build_extraction_template(vehicle_types: dict, extraction_schema: list) -> str:
    lines = ["Extract AGV/AMR technical requirements from this tender. Values may appear in running text OR in tables — extract from both.",
             ""]

    # Vehicle type classification guide (from Vehicle Types sheet)
    # BUG-A/F fix: add explicit Chain-of-Thought ordering to prevent LLM defaulting to Counterbalanced
    guide = vehicle_types.get("llm_guide", [])
    if guide:
        lines += ["Vehicle type classification guide (for required_vehicle_type):"]
        seen_names = set()
        for vt in guide:
            if vt["name"] in seen_names: continue
            seen_names.add(vt["name"])
            line = f'  * "{vt["name"]}" → {vt["description"]}'
            if vt.get("key_indicators"):
                line += f'. Signals: {vt["key_indicators"]}'
            lines.append(line)
        lines.append("  Key: PRODUCTION/FILLING LINES/MANUFACTURING → Mobile AMR. WAREHOUSE/RACKING/SHIPPING → Forklift AGV type.")
        lines.append("")
        lines.append("  THINK STEP BY STEP when classifying required_vehicle_type:")
        lines.append("  (1) Is this a PRODUCTION/MANUFACTURING/FILLING LINE environment? → required_vehicle_type='Mobile AMR'.")
        lines.append("  (2) Does the doc mention VNA / very narrow aisle / aisle<2m / high-bay racking? → required_vehicle_type='VNA', required_vna=true, required_drive_type='VNA Turret'.")
        lines.append("  (3) Does the doc mention towing / tugger / milk run / trailer train? → required_vehicle_type='Tugger'.")
        lines.append("  (4) Only if none of the above apply: use Counterbalanced or Reach Truck based on aisle width.")
        lines.append("  Do NOT default to Counterbalanced when VNA or Production/AMR signals are present.")
        lines.append("")

    lines.append("Field definitions:")
    for field in extraction_schema:
        if not field["hint"]:
            continue
        mand = " MANDATORY —" if field["mandatory"] else ""
        hint = field["hint"]
        # BUG-C fix: augment aisle width field with explicit warning about height confusion
        if field["key"] == "required_min_aisle_width_m":
            hint += (" WARNING: Do NOT confuse aisle width with transfer station height,"
                     " rack height, or lift height."
                     " Source terms: 'Gangbreite', 'aisle width', 'working aisle'."
                     " If no explicit aisle width is stated → output null.")
        # BUG-G fix: augment station_types field with explicit warning against defaulting to examples
        if field["key"] == "required_station_types":
            hint += (" Output null if not explicitly stated in document."
                     " DO NOT default to example values.")
        lines.append(f'- {field["key"]}:{mand} {hint}')

    lines += ["",
              "Use null only when a field genuinely cannot be determined from the document.",
              "",
              "DOCUMENT:",
              "{text}",
              "",
              "JSON:"]

    # JSON schema line — generated from Extraction Schema, no duplicates
    seen_keys = set()
    json_fields = []
    for field in extraction_schema:
        if field["key"] not in seen_keys:
            seen_keys.add(field["key"])
            json_fields.append(f'"{field["key"]}":null')
    lines.append("{" + ",".join(json_fields) + "}")

    return "\n".join(lines)


def build_retry_template(extraction_schema: list) -> str:
    seen_keys = set()
    json_fields = []
    for field in extraction_schema:
        if field["key"] not in seen_keys:
            seen_keys.add(field["key"])
            json_fields.append(f'"{field["key"]}":null')
    json_schema = "{" + ",".join(json_fields) + "}"

    return "\n".join([
        "IMPORTANT: Output ONLY the JSON object below, nothing else. No prose, no explanation.",
        "",
        "Extract AGV/AMR requirements from this tender. Use null for values not explicitly stated.",
        "",
        "Key interpretation rules:",
        "- If a handling point table lists \"Conveyor belt picking/delivery\" as the handling method, set required_conveyor_integration to \"yes\".",
        "- Tugger AGVs tow trailer trains and CANNOT interface with conveyor belts without manual reloading — if conveyors are present, required_vehicle_type should NOT be Tugger.",
        "- If most stations use floor delivery but at least one uses conveyor belt, the system needs BOTH floor transport AND conveyor integration.",
        "",
        "DOCUMENT:",
        "{text}",
        "",
        "Output ONLY this JSON:",
        json_schema,
    ])


def build_nace_template(nace: dict) -> str:
    return "\n".join([
        'A tender is for: "{tender_category}"',
        "",
        "SCOPE RULE: Evaluate ONLY what is being PROCURED (the tendered service/product).",
        "The buyer's industry is IRRELEVANT — an AGV system tender from a beverage company",
        "is IN SCOPE just as much as one from a logistics company.",
        "",
        f'IN SCOPE: {nace["scope_in"]}.',
        "",
        f'OUT OF SCOPE: {nace["scope_out"]}.',
        "",
        "If OUT OF SCOPE, output the not-in-scope JSON.",
        "Otherwise, pick the single best matching NACE code from this list:",
        "{category_list}",
        "",
        "Output ONLY one of these two JSON options — use exactly these field names:",
        "",
        'If in scope:',
        '{"nace_tender":"[code]","nace_tender_name":"[name from list]","nace_buyer":null,"priority":"TOP|GUT|NIEDRIG","confidence":"HOCH|MITTEL|NIEDRIG","in_scope":true}',
        "",
        "If out of scope:",
        '{"nace_tender":null,"nace_tender_name":null,"nace_buyer":null,"priority":"UNBEKANNT","confidence":"NIEDRIG","in_scope":false}',
    ])


def build_basic_template() -> str:
    return "\n".join([
        "Extract these facts from the tender document. Output ONLY valid JSON.",
        "Use JSON null (not the string \"null\") if a value is not found.",
        "Dates: extract in ANY format found; normalize output to DD.MM.YYYY.",
        "",
        "Rules:",
        "- buyer_industry: infer from the buyer's name/description if not explicitly stated",
        "  (e.g. \"Technische Universität\" → \"Higher Education\", a hospital → \"Healthcare\").",
        "  Never leave null if the buyer name gives a clear hint.",
        "- tender_category: describe what is being procured in 3-6 words",
        "  (e.g. \"Website Redesign\", \"Warehouse Automation System\", \"Security Consulting\").",
        "  Never leave null if the project name is present.",
        "- is_agv_amr: set to true if the document requests Automated Guided Vehicles (AGV),",
        "  Autonomous Mobile Robots (AMR), automated intralogistics vehicles, VNA robots,",
        "  or any self-driving warehouse/factory transport robot.",
        "  If the words AGV, AMR, or VNA appear in the document, set this to true.",
        "",
        "DOCUMENT:",
        "{text}",
        "",
        "JSON:",
        '{"buyer":null,"project_name":null,"project_location":null,"tender_date":null,"deadline":null,"contact_name":null,"contact_email":null,"contact_phone":null,"buyer_industry":null,"tender_category":null,"is_agv_amr":false,"summary":null,"missing_info":[]}',
    ])


# ── Validators ────────────────────────────────────────────────────────────────

def validate_vs_sqlite(field_levels: dict, db_path: Path) -> list:
    if not db_path.exists():
        return ["SQLite DB not found — schema validation skipped"]
    conn = sqlite3.connect(str(db_path))
    db_cols = set()
    for table in ("companies", "products", "base_model_extensions"):
        db_cols.update(r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall())
    conn.close()
    db_cols -= SQLITE_SKIP
    warnings = []
    for f in sorted(set(field_levels) - db_cols):
        warnings.append(f"AP0 defines '{f}' ({field_levels[f]['level']}) but missing from SQLite")
    for f in sorted(db_cols - set(field_levels)):
        warnings.append(f"SQLite has '{f}' with no AP0 classification")
    return warnings


# ── Main ──────────────────────────────────────────────────────────────────────

def generate(xlsx_path: Path, db_path: Path, dry_run: bool = False,
             platform_path: Path = DEFAULT_PLATFORM) -> int:
    print(f"Reading AP0 xlsx:      {xlsx_path.name}")
    print(f"Reading platform config: {platform_path.name if platform_path.exists() else '(not found)'}")
    wb = openpyxl.load_workbook(str(xlsx_path), read_only=True, data_only=True)

    field_levels      = read_field_levels(wb)
    vehicle_types     = read_vehicle_types(wb)
    scoring_weights   = read_scoring_weights(wb)
    extraction_schema = read_extraction_schema(wb)
    sqlite_schema     = read_sqlite_schema(wb)
    plausibility      = build_plausibility_config()
    platform          = read_platform(platform_path)
    nace              = platform  # nace data is inside platform dict

    # Enrich vehicle_types with vna_drive_type resolved from field_levels.
    # This avoids any substring-matching at runtime — app.py reads vehicle_types["vna_drive_type"].
    # The value comes from AP0 field_levels["drive_type"]["allowed_values"] — the entry flagged VNA.
    # Convention: the VNA drive type is the single allowed_value for drive_type whose name
    # contains "VNA" (case-insensitive). If AP0 renames it, generate_all.py warns explicitly.
    _dt_allowed = field_levels.get("drive_type", {}).get("allowed_values", [])
    _vna_drive  = next((v for v in _dt_allowed if "vna" in v.lower()), None)
    if _vna_drive:
        vehicle_types["vna_drive_type"] = _vna_drive
    else:
        print("  [WARN] No VNA drive type found in drive_type allowed_values — vna_drive_type not set")

    print(f"  Fields: {len(field_levels)} ({sum(1 for v in field_levels.values() if v['level']=='KO')} KO, {sum(1 for v in field_levels.values() if v['level']=='COND_KO')} COND_KO)")
    print(f"  Vehicle types: {len(vehicle_types.get('vt_map', {}))} mappings, {len(vehicle_types.get('llm_guide',[]))} with LLM guide")
    print(f"  Scoring weights: {sum(len(v) for v in scoring_weights.values())} entries")
    print(f"  NACE codes (Prio 1): {len(platform['codes'])}")
    print(f"  Extraction fields: {len(extraction_schema)}")
    print(f"  SQLite schema: {sum(1 for s in sqlite_schema.values() if isinstance(s, str))} tables generated")
    print(f"  Plausibility ranges: {len(plausibility)} fields")

    # Build prompts
    extraction_template = build_extraction_template(vehicle_types, extraction_schema)
    retry_template      = build_retry_template(extraction_schema)
    nace_template       = build_nace_template(nace)
    basic_template      = build_basic_template()

    # Checksums & validation
    xlsx_md5 = hashlib.md5(xlsx_path.read_bytes()).hexdigest()
    warnings = validate_vs_sqlite(field_levels, db_path)

    if dry_run:
        print("\n[DRY RUN] Would write:")
        print("  config/field_levels.json, vehicle_types.json, scoring_weights.json, nace_codes.json")
        print("  config/sqlite_schema.json, config/plausibility.json")
        print("  config/prompts/extraction_template.txt (and others)")
        print(f"\nExtraction template preview (first 400 chars):\n{extraction_template[:400]}")
        print(f"\nSQLite companies preview:\n{sqlite_schema['companies'][:400]}")
    else:
        PROMPTS_DIR.mkdir(parents=True, exist_ok=True)

        (CONFIG_DIR / "field_levels.json").write_text(
            json.dumps(field_levels, indent=2, ensure_ascii=False) + "\n")
        (CONFIG_DIR / "vehicle_types.json").write_text(
            json.dumps(vehicle_types, indent=2, ensure_ascii=False) + "\n")
        (CONFIG_DIR / "scoring_weights.json").write_text(
            json.dumps(scoring_weights, indent=2, ensure_ascii=False) + "\n")
        (CONFIG_DIR / "nace_codes.json").write_text(
            json.dumps(nace, indent=2, ensure_ascii=False) + "\n")
        (CONFIG_DIR / "sqlite_schema.json").write_text(
            json.dumps(sqlite_schema, indent=2, ensure_ascii=False) + "\n")
        (CONFIG_DIR / "plausibility.json").write_text(
            json.dumps(plausibility, indent=2, ensure_ascii=False) + "\n")

        (PROMPTS_DIR / "extraction_system.txt").write_text(
            "You are a warehouse automation specialist. Extract technical AGV/AMR requirements. Output ONLY valid JSON. No markdown, no explanation.")
        (PROMPTS_DIR / "extraction_template.txt").write_text(extraction_template)
        (PROMPTS_DIR / "extraction_retry_system.txt").write_text(
            "You are a data extraction assistant. Extract facts from tender documents into JSON. Output ONLY valid JSON. No markdown fences, no explanations.")
        (PROMPTS_DIR / "extraction_retry_template.txt").write_text(retry_template)
        (PROMPTS_DIR / "basic_system.txt").write_text(
            "You are a data extraction assistant. Extract facts from tender documents into JSON. Output ONLY valid JSON. No markdown fences, no explanations.")
        (PROMPTS_DIR / "basic_template.txt").write_text(basic_template)
        (PROMPTS_DIR / "contact_system.txt").write_text(
            "You are a contact-data extraction assistant. Extract contact details from the document excerpt. Output ONLY valid JSON. No markdown, no explanation.")
        (PROMPTS_DIR / "contact_template.txt").write_text(
            'Extract contact details from this document excerpt. Use null if not found.\n\nDOCUMENT EXCERPT (last pages):\n{text}\n\nOutput ONLY this JSON:\n{"contact_name":null,"contact_email":null,"contact_phone":null,"deadline":null,"tender_date":null}')
        (PROMPTS_DIR / "nace_system.txt").write_text(
            "You are an industrial classification specialist. Pick the single best NACE code from the provided list. Output ONLY valid JSON with exactly the field names shown.")
        (PROMPTS_DIR / "nace_template.txt").write_text(nace_template)

        # Sync README from Synology if mounted and newer
        readme_remote = Path.home() / "Library" / "CloudStorage" / "SynologyDrive-homeDrive" / "Haystacked" / "Specs" / "haystacked_industry_readme.md"
        readme_local  = CONFIG_DIR / "industry_readme.md"
        if readme_remote.exists():
            if not readme_local.exists() or readme_remote.stat().st_mtime > readme_local.stat().st_mtime:
                readme_local.write_bytes(readme_remote.read_bytes())
                print("  Industry README synced from Synology Drive")

        (CONFIG_DIR / "ap0_checksum.txt").write_text(xlsx_md5)

        print(f"\nWrote all config files. AP0 checksum: {xlsx_md5[:8]}…")

    if warnings:
        print(f"\nCONSISTENCY WARNINGS ({len(warnings)}):")
        for w in warnings: print(f"  [WARN] {w}")
        return 1
    print("\nAll consistency checks passed.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate all runtime config from AP0 xlsx")
    parser.add_argument("--xlsx",     default=str(DEFAULT_XLSX))
    parser.add_argument("--platform", default=str(DEFAULT_PLATFORM))
    parser.add_argument("--db",       default=str(DEFAULT_DB))
    parser.add_argument("--dry-run",  action="store_true")
    args = parser.parse_args()
    sys.exit(generate(Path(args.xlsx), Path(args.db), args.dry_run, Path(args.platform)))
