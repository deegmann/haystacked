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


def read_field_text_fallbacks(wb) -> list:
    """Read Field Fallbacks sheet → list of {tender_key, regex, value, only_if_null}."""
    if "Field Fallbacks" not in wb.sheetnames:
        return []
    rows = _rows(wb["Field Fallbacks"], min_row=2)
    hi, cols = _find_header(rows, "Tender Key")
    if hi is None:
        return []
    c_key   = cols.get("Tender Key", 0)
    c_regex = cols.get("Regex (applied to full PDF text)", 1)
    c_val   = cols.get("Fallback Value (AP0 allowed value)", 2)
    c_null  = cols.get("Only If Null", 3)
    result = []
    for row in rows[hi+1:]:
        if not row or not row[c_key]:
            continue
        tender_key = str(row[c_key]).strip()
        regex      = str(row[c_regex]).strip() if c_regex < len(row) and row[c_regex] else ""
        value      = str(row[c_val]).strip()   if c_val   < len(row) and row[c_val]   else ""
        only_null  = str(row[c_null]).strip().lower() != "no" if c_null < len(row) and row[c_null] else True
        if tender_key and regex and value:
            result.append({"tender_key": tender_key, "regex": regex, "value": value, "only_if_null": only_null})
    return result


def read_scoring_weights(wb) -> dict:
    """Read scoring weights + rules from AP0 xlsx.

    Reads: Scoring Weight, Scoring Rule, Threshold 1, Threshold 2.
    Output format per field: {"weight": int, "rule": str, "t1": num|None, "t2": num|None}
    """
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
    def _num(v):
        if v is None or v == '': return None
        try:
            f = float(v)
            return int(f) if f == int(f) else f
        except: return None

    for sheet, bucket in sheet_map.items():
        if sheet not in wb.sheetnames: continue
        rows = _rows(wb[sheet])
        hi, cols = _find_header(rows)
        if hi is None: continue
        c_field  = cols.get("Field Name", 0)
        c_weight = cols.get("Scoring Weight")
        c_rule   = cols.get("Scoring Rule")
        c_t1     = cols.get("Threshold 1")
        c_t2     = cols.get("Threshold 2")
        if c_weight is None: continue
        for row in rows[hi+1:]:
            if not row or not row[c_field]: continue
            fname = str(row[c_field]).strip()
            if fname.startswith("──"): continue
            w = _int(row[c_weight] if c_weight < len(row) else None)
            if not w: continue
            rule = (str(row[c_rule]).strip()
                    if c_rule is not None and c_rule < len(row) and row[c_rule] else "bool")
            t1   = _num(row[c_t1] if c_t1 is not None and c_t1 < len(row) else None)
            t2   = _num(row[c_t2] if c_t2 is not None and c_t2 < len(row) else None)
            entry: dict = {"weight": w, "rule": rule}
            if t1 is not None: entry["t1"] = t1
            if t2 is not None: entry["t2"] = t2
            result[bucket][fname] = entry
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
            schema.append({"key": jk, "db_field": fname, "mandatory": mand, "hint": hint, "sheet": sheet})

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

    # C-6: explicit column list for sync_airtable.py (derived from generated SQL,
    # so sync_airtable never hardcodes field names)
    extensions_columns = (
        ["extension_id", "base_model_id", "agv_type"]
        + [f for f, _ in ext_fields]
        + ["extra_fields"]
    )

    return {
        "companies":             companies_sql,
        "products":              products_sql,
        "base_models":           base_models_sql,
        "base_model_extensions": extensions_sql,
        "bool_fields":           sorted(bool_fields),
        "int_fields":            sorted(int_fields),
        "float_fields":          sorted(float_fields),
        "extensions_columns":    extensions_columns,
    }


def read_plausibility(wb) -> dict:
    """Read plausibility ranges from AP0 xlsx — tender_key → {min, max, unit, label}.

    Unit conversion rules are read separately from haystacked_platform_config.xlsx
    via read_unit_conversions(), then combined in build_plausibility_config().
    """
    plausibility: dict = {}

    for sheet_name in DATA_SHEETS:
        if sheet_name not in wb.sheetnames:
            continue
        rows = _rows(wb[sheet_name])
        hi, cols = _find_header(rows)
        if hi is None:
            continue

        col_tkey  = cols.get("Tender JSON Key")
        col_pmin  = cols.get("Plausibility Min")
        col_pmax  = cols.get("Plausibility Max")
        col_unit  = cols.get("Tender Unit")

        if None in (col_tkey, col_pmin, col_pmax, col_unit):
            print(f"  [WARN] Plausibility columns missing in {sheet_name} — run generate_all.py after adding them to xlsx")
            continue

        for row in rows[hi + 1:]:
            fname = row[0]
            if not fname or str(fname).startswith("──"):
                continue
            tkey = row[col_tkey] if col_tkey < len(row) else None
            pmin = row[col_pmin] if col_pmin < len(row) else None
            pmax = row[col_pmax] if col_pmax < len(row) else None
            unit = row[col_unit] if col_unit < len(row) else None

            if tkey and pmin is not None and pmax is not None:
                if tkey not in plausibility:  # first occurrence wins (SHARED before type-specific)
                    plausibility[tkey] = {
                        "min":   float(pmin),
                        "max":   float(pmax),
                        "unit":  str(unit) if unit else "",
                        "label": str(fname),
                    }

    return plausibility


def read_unit_conversions(wb_platform) -> dict:
    """Read unit conversion rules from haystacked_platform_config.xlsx — Unit Conversions sheet.

    Cross-industry rules (e.g. m ↔ mm) live in the platform config, not in the AGV AP0.
    Returns: tender_unit → {llm_alias, factor, threshold}
    """
    unit_conversions: dict = {}
    if "Unit Conversions" not in wb_platform.sheetnames:
        print("  [WARN] Unit Conversions sheet missing from platform config")
        return unit_conversions
    uc_rows = _rows(wb_platform["Unit Conversions"], min_row=3)  # row 1 = description, row 2 = header
    for row in uc_rows:
        if row and row[0] and row[1]:
            unit_conversions[str(row[0])] = {
                "llm_alias": str(row[1]),
                "factor":    float(row[2]),
                "threshold": float(row[3]),
            }
    return unit_conversions


def build_plausibility_config(plausibility: dict, unit_conversions: dict) -> dict:
    """Combine plausibility ranges with unit conversion rules into config/plausibility.json format.

    Conversion block is added when the field's Tender Unit has a matching rule in the
    Unit Conversions sheet — no field-specific flags, no hardcoded factors.
    """
    result = {}
    for key, data in plausibility.items():
        entry = dict(data)
        conv = unit_conversions.get(data.get("unit"))
        entry["conversion"] = {
            "llm_alias": conv["llm_alias"],
            "factor":    conv["factor"],
            "threshold": conv["threshold"],
        } if conv else None
        result[key] = entry
    return result


def read_platform(wb, platform_path: Path) -> dict:
    """Read platform_config.xlsx — cross-industry: NACE, basic schema, scope.

    Accepts an already-opened workbook (wb) to avoid double-loading.
    platform_path is used only for the not-found warning message.
    """
    if wb is None:
        print(f"  [WARN] platform_config not found: {platform_path}")
        return {"scope_in": "", "scope_out": "", "codes": [], "basic_schema": []}

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

def build_vehicle_type_template(vehicle_types: dict) -> str:
    """Pass 4a template — classify vehicle type and VNA flag only."""
    lines = [
        "Classify the required AGV/AMR vehicle type from this tender document.",
        "Output ONLY the JSON object shown below — nothing else.",
        "",
    ]
    guide = vehicle_types.get("llm_guide", [])
    if guide:
        lines.append("Vehicle type classification guide:")
        seen_names = set()
        for vt in guide:
            if vt["name"] in seen_names: continue
            seen_names.add(vt["name"])
            line = f'  * "{vt["name"]}" → {vt["description"]}'
            if vt.get("key_indicators"):
                line += f'. Signals: {vt["key_indicators"]}'
            lines.append(line)
        lines.append("  Key: PAYLOAD AND LOAD TYPE determine the vehicle — not the environment alone.")
        lines.append("")
        lines.append("  THINK STEP BY STEP:")
        lines.append("  IMPORTANT: Only three values are valid: 'Forklift AGV', 'Tugger AGV', 'Mobile AMR'.")
        lines.append("  Sub-variants (Counterbalanced, Reach Truck, VNA) are NOT valid outputs — they are internal properties, not types.")
        lines.append("  (1) Towing / tugger / milk run / trailer train / Routenzug? → required_vehicle_type='Tugger AGV'.")
        lines.append("  (2) Light load (<1000 kg) + flexible SLAM navigation + no standard floor-pallet pickup? → required_vehicle_type='Mobile AMR'.")
        lines.append("  (3) Everything else (pallets, IBCs, forks required, racking, heavy load) → required_vehicle_type='Forklift AGV'.")
        lines.append("      Counterbalanced, Reach Truck, AND VNA are all 'Forklift AGV'.")
        lines.append("      If VNA / very narrow aisle / aisle<2m → required_vehicle_type='Forklift AGV' AND required_vna=true.")
        lines.append("")
    lines += [
        "Fields:",
        "- required_vehicle_type: MANDATORY — exactly one of: 'Forklift AGV', 'Tugger AGV', 'Mobile AMR'.",
        "- required_vna: true if VNA / Schmalgang / very narrow aisle / aisle<2m with high-bay racking. Only applicable when required_vehicle_type='Forklift AGV'. false otherwise.",
        "",
        "DOCUMENT:",
        "{text}",
        "",
        "JSON:",
        '{"required_vehicle_type":null,"required_vna":null}',
    ]
    return "\n".join(lines)


# Fields determined in Pass 4a — excluded from Pass 4b templates
_4A_FIELDS = {"required_vehicle_type", "required_vna"}


_OPERATOR_DIRECTION = {
    "KO_IF_LT": "CONSERVATIVE EXTRACTION: if multiple values are stated, extract the MAXIMUM — the supplier must meet or exceed this threshold.",
    "KO_IF_GT": "CONSERVATIVE EXTRACTION: if multiple values are stated, extract the MINIMUM — the supplier must not exceed this constraint.",
}
_NUMERIC_DTYPES = {"Float", "Integer"}


def build_extraction_template(vehicle_types: dict, extraction_schema: list,
                               sheet_filter: str = None, field_levels: dict = None) -> str:
    """Build LLM extraction template.

    sheet_filter=None  → full combined template (backward compat / JSON-retry fallback).
    sheet_filter=<sheet> → Pass 4b type-specific template; includes SHARED + that sheet only,
                           excludes fields already determined in Pass 4a.
                           Placeholders {vehicle_type} and {vna_context} filled by app.py at runtime.
    """
    if sheet_filter:
        # Pass 4b: only relevant fields for this vehicle type
        schema_to_use = [
            f for f in extraction_schema
            if f.get("sheet") in ("SHARED – All AGV Types", sheet_filter)
            and f["key"] not in _4A_FIELDS
        ]
        lines = [
            "The vehicle type for this tender has been determined: {vehicle_type}. {vna_context}",
            "Extract the technical requirements listed below from the tender document.",
            "Values may appear in running text OR in tables — extract from both.",
            "Output ONLY the JSON object shown at the end — nothing else.",
            "",
        ]
    else:
        # Full combined template (backward compat)
        schema_to_use = extraction_schema
        lines = ["Extract AGV/AMR technical requirements from this tender. Values may appear in running text OR in tables — extract from both.",
                 ""]
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
            lines.append("  Key: PAYLOAD AND LOAD TYPE determine the vehicle — not the environment alone.")
            lines.append("  Filling lines + pallet transport = Forklift AGV. Filling lines + light totes/boxes = Mobile AMR.")
            lines.append("")
            lines.append("  THINK STEP BY STEP when classifying required_vehicle_type:")
            lines.append("  IMPORTANT: Only three values are valid for required_vehicle_type: 'Forklift AGV', 'Tugger AGV', 'Mobile AMR'.")
            lines.append("  Sub-variants (Counterbalanced, Reach Truck, VNA) are NOT valid outputs — they are internal properties, not types.")
            lines.append("  (1) Does the doc mention towing / tugger / milk run / trailer train / Routenzug? → required_vehicle_type='Tugger AGV'.")
            lines.append("  (2) Is this light load (<1000 kg) with flexible SLAM navigation and no standard floor-pallet pickup? → required_vehicle_type='Mobile AMR'.")
            lines.append("  (3) Everything else (pallets, IBCs, drums, racking, forks required, heavy load) → required_vehicle_type='Forklift AGV'.")
            lines.append("      This includes Counterbalanced, Reach Truck, AND VNA applications — they are all 'Forklift AGV'.")
            lines.append("      If VNA / very narrow aisle / aisle<2m is detected → required_vehicle_type='Forklift AGV' AND required_vna=true.")
            lines.append("  Do NOT output 'Counterbalanced', 'Reach Truck', 'VNA', or any other sub-variant as the vehicle type.")
            lines.append("")

    lines.append("Field definitions:")
    _source_instrumented = set()  # numeric KO fields that get a _source companion
    for field in schema_to_use:
        if not field["hint"]:
            continue
        mand = " MANDATORY —" if field["mandatory"] else ""
        hint = field["hint"]
        needs_source = False
        if field_levels:
            fl  = field_levels.get(field["db_field"], {})
            op  = fl.get("operator", "")
            dt  = fl.get("data_type", "")
            if op in _OPERATOR_DIRECTION and dt in _NUMERIC_DTYPES:
                hint = hint + " " + _OPERATOR_DIRECTION[op]
                needs_source = True
        lines.append(f'- {field["key"]}:{mand} {hint}')
        if needs_source:
            _source_instrumented.add(field["key"])
            lines.append(
                f'- {field["key"]}_source: The EXACT verbatim sentence or phrase from the document '
                f'that contains the value above. null if the value was not found explicitly in the '
                f'document — in which case {field["key"]} MUST also be null.'
            )

    lines += ["",
              "Use null only when a field genuinely cannot be determined from the document.",
              "",
              "DOCUMENT:",
              "{text}",
              "",
              "JSON:"]

    seen_keys = set()
    json_fields = []
    for field in schema_to_use:
        if field["key"] not in seen_keys:
            seen_keys.add(field["key"])
            json_fields.append(f'"{field["key"]}":null')
            if field["key"] in _source_instrumented:
                json_fields.append(f'"{field["key"]}_source":null')
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

    field_levels         = read_field_levels(wb)
    vehicle_types        = read_vehicle_types(wb)
    field_text_fallbacks = read_field_text_fallbacks(wb)
    vehicle_types["field_text_fallbacks"] = field_text_fallbacks
    scoring_weights      = read_scoring_weights(wb)
    extraction_schema = read_extraction_schema(wb)
    sqlite_schema     = read_sqlite_schema(wb)
    plausibility_raw  = read_plausibility(wb)

    wb_platform       = openpyxl.load_workbook(str(platform_path), read_only=True, data_only=True) \
                        if platform_path.exists() else None
    unit_conversions  = read_unit_conversions(wb_platform) if wb_platform else {}
    plausibility      = build_plausibility_config(plausibility_raw, unit_conversions)

    # Assert all numeric KO fields (Float/Integer, KO_IF_LT/KO_IF_GT) have plausibility
    # ranges defined in the AP0 xlsx. Missing entries cause silent validation gaps.
    _numeric_ko_keys = {
        meta["tender_key"]
        for meta in field_levels.values()
        if meta.get("operator") in ("KO_IF_LT", "KO_IF_GT")
        and meta.get("data_type") in ("Float", "Integer")
        and "tender_key" in meta
    }
    _missing = _numeric_ko_keys - set(plausibility_raw)
    assert not _missing, (
        f"[FEHLER] Numeric KO-Felder ohne Plausibility-Daten in AP0 xlsx: {_missing}. "
        "Plausibility Min / Plausibility Max / Tender Unit in der AP0-Tabelle ergänzen."
    )

    platform          = read_platform(wb_platform, platform_path)
    nace              = platform  # nace data is inside platform dict

    # Additional runtime fields derived from AP0 — written to vehicle_types.json so
    # Python code never contains canonical type names or AGV-domain keywords.

    # C-2: canonical type → scoring_weights.json bucket name
    vehicle_types["scoring_bucket_map"] = {
        canon: bucket
        for canon, bucket in [("Forklift AGV", "forklift_specific"),
                               ("Tugger AGV",   "tugger_specific"),
                               ("Mobile AMR",   "amr_specific")]
        if canon in vehicle_types.get("vt_map", {}).values()
        or any(canon == v for v in vehicle_types.get("vt_map", {}).values())
    }
    # Ensure all three are always present (in case vt_map is incomplete)
    for _c, _b in [("Forklift AGV", "forklift_specific"),
                   ("Tugger AGV",   "tugger_specific"),
                   ("Mobile AMR",   "amr_specific")]:
        vehicle_types["scoring_bucket_map"].setdefault(_c, _b)

    # C-5: canonical types for which VNA logic applies
    vehicle_types["vna_applicable_types"] = ["Forklift AGV"]

    # C-6: name of the shared (cross-vehicle-type) AP0 sheet — consumed by Pass 4c in app.py
    # so the string never needs to be hardcoded in Python.
    vehicle_types["shared_sheet_name"] = DATA_SHEETS[0]

    # C-1: flat list of all keyword_map values for is_agv_amr detection
    _all_kws: list = []
    for _kws in vehicle_types.get("keyword_map", {}).values():
        _all_kws.extend(_kws)
    vehicle_types["agv_detection_keywords"] = list(dict.fromkeys(_all_kws))

    # M-1: ensure Schmalgangstapler text override sets vna=True
    _schmal_regex = "(?i)schmalgangstapler"
    _existing = {o.get("regex") for o in vehicle_types.get("text_overrides", [])}
    if _schmal_regex not in _existing:
        vehicle_types.setdefault("text_overrides", []).append(
            {"regex": _schmal_regex, "canonical": "Forklift AGV", "vna": True}
        )

    print(f"  Fields: {len(field_levels)} ({sum(1 for v in field_levels.values() if v['level']=='KO')} KO, {sum(1 for v in field_levels.values() if v['level']=='COND_KO')} COND_KO)")
    print(f"  Vehicle types: {len(vehicle_types.get('vt_map', {}))} mappings, {len(vehicle_types.get('llm_guide',[]))} with LLM guide")
    print(f"  Scoring weights: {sum(len(v) for v in scoring_weights.values())} entries")
    print(f"  NACE codes (Prio 1): {len(platform['codes'])}")
    print(f"  Extraction fields: {len(extraction_schema)}")
    print(f"  SQLite schema: {sum(1 for s in sqlite_schema.values() if isinstance(s, str))} tables generated")
    print(f"  Plausibility ranges: {len(plausibility)} fields")

    # Build prompts
    vehicle_type_template = build_vehicle_type_template(vehicle_types)
    extraction_template   = build_extraction_template(vehicle_types, extraction_schema, field_levels=field_levels)
    retry_template        = build_retry_template(extraction_schema)

    # Build type-specific Pass 4b templates — derived from DATA_SHEETS, no hardcoded type names
    # vt_prompt_map written to vehicle_types.json so app.py never needs to know canonical names.
    vt_prompt_map: dict = {}
    type_templates: dict = {}
    for _sheet in DATA_SHEETS:
        if _sheet == "SHARED – All AGV Types":
            continue
        _slug  = _sheet.lower().replace(" ", "_")          # e.g. "forklift_agv"
        _fname = f"extraction_template_{_slug}.txt"
        vt_prompt_map[_sheet] = _fname
        type_templates[_sheet] = build_extraction_template(vehicle_types, extraction_schema,
                                                            sheet_filter=_sheet, field_levels=field_levels)
    vehicle_types["vt_prompt_map"]     = vt_prompt_map
    vehicle_types["4a_fields"]         = list(_4A_FIELDS)   # fields owned by Pass 4a, excluded from 4b
    vehicle_types["vna_context_hint"]  = "VNA (very narrow aisle) operation is required."
    nace_template       = build_nace_template(nace)
    basic_template      = build_basic_template()

    # Checksums & validation
    xlsx_md5 = hashlib.md5(xlsx_path.read_bytes()).hexdigest()
    warnings = validate_vs_sqlite(field_levels, db_path)

    if dry_run:
        print("\n[DRY RUN] Would write:")
        print("  config/field_levels.json, vehicle_types.json, scoring_weights.json, nace_codes.json")
        print("  config/sqlite_schema.json, config/plausibility.json, config/extraction_hints.json")
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
            "You are a warehouse automation specialist. Extract technical AGV/AMR requirements from tender documents. Output ONLY valid JSON. No markdown, no explanation.\n\n"
            "ANTI-HALLUCINATION RULE — NULL IF NOT EXPLICITLY STATED:\n"
            "Before outputting any non-null value you must be able to identify the exact sentence in the document that states it.\n"
            "- Do NOT infer specifications from warehouse type or AGV type: a VNA warehouse does NOT imply IP65, cold-storage temperature, high humidity, ramp gradient, or VDA 5050 unless these are written in the document.\n"
            "- Do NOT read numbers from dates, filenames, revision codes, version strings, or project metadata as specification values.\n"
            "  Example: '25th May 2022' is a date — NOT a temperature. 'v1.3' is a version — NOT a floor flatness value.\n"
            "- If a field's value is not directly stated in the document text, output null — never apply 'typical' industry values.")
        (PROMPTS_DIR / "vehicle_type_template.txt").write_text(vehicle_type_template)
        (PROMPTS_DIR / "extraction_template.txt").write_text(extraction_template)
        for _sheet, _tmpl in type_templates.items():
            _slug = _sheet.lower().replace(" ", "_")
            (PROMPTS_DIR / f"extraction_template_{_slug}.txt").write_text(_tmpl)
        (PROMPTS_DIR / "extraction_retry_system.txt").write_text(
            "You are a data extraction assistant. Extract facts from tender documents into JSON. Output ONLY valid JSON. No markdown fences, no explanations.")
        (PROMPTS_DIR / "extraction_retry_template.txt").write_text(retry_template)

        # Prune stale extraction_template_*.txt files not in the current vt_prompt_map
        expected = set(vt_prompt_map.values()) | {
            "extraction_template.txt", "extraction_retry_template.txt",
            "extraction_retry_system.txt", "extraction_system.txt",
            "vehicle_type_template.txt", "basic_system.txt",
            "basic_template.txt", "nace_template.txt",
        }
        for stale in PROMPTS_DIR.glob("extraction_template_*.txt"):
            if stale.name not in expected:
                stale.unlink()
                print(f"  [PRUNE] Deleted stale prompt: {stale.name}")
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

        # extraction_hints.json — maps tender_key → {hint, sheet} for all extraction fields.
        # Consumed by Pass 4c per-field extraction in app.py.
        extraction_hints = {
            f["key"]: {"hint": f["hint"], "sheet": f["sheet"]}
            for f in extraction_schema
            if f.get("hint") and f.get("key") and f.get("sheet")
        }
        (CONFIG_DIR / "extraction_hints.json").write_text(
            json.dumps(extraction_hints, indent=2, ensure_ascii=False) + "\n"
        )

        # Sync README from Spec/ (single source of truth within repo) → config/
        # config/industry_readme.md is the runtime copy loaded by context_builder.py.
        readme_spec  = ROOT / "Spec" / "haystacked_industry_readme.md"
        readme_local = CONFIG_DIR / "industry_readme.md"
        if readme_spec.exists():
            if not readme_local.exists() or readme_spec.stat().st_mtime > readme_local.stat().st_mtime:
                readme_local.write_bytes(readme_spec.read_bytes())
                print("  Industry README synced from Spec/")

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
