#!/usr/bin/env python3
"""Import the 11-day datasheet-ingestion project (2026-08-11..21) into Airtable.

Follows the conventions of scripts/import_research_20260801.py and
scripts/import_manual_notes_20260806.py:
  - Company -> Base Model -> Product -> Base Model Extension linked-record inserts
  - typecast=True so new select options are created automatically
  - rate-limited API calls, persistent jsonl audit log
  - --dry-run (default) / --run flags

Primary data sources:
  docs/datasheet_db_status_final.json      -- 276 products, db_status_final + conflicts[]
  docs/sonnet_opus_merged_dataset.json     -- actual field VALUES per product (keyed identically)
  docs/sonnet_opus_cwc_challenge_results.json -- 22 reconciled company-wide-context verdicts
  docs/research_findings_opus_20260808_*.json -- company_wide_context blocks for companies
                                                  NOT covered by the challenge file
  data/raw/{companies,base_models,products,base_model_extensions}.csv -- live DB snapshot,
                                                  used as ground truth for "is this NULL?"
                                                  and for Airtable record-id resolution.
                                                  NO Airtable API calls are made in --dry-run.

Category handling (see Tech Lead brief for full rationale):
  1. db_status_final == "new"      -> full insert chain (Company/Base Model/Product/Extension)
  2. db_status_final == "enrich"   -> PATCH, fill NULL fields only, never overwrite
  3. db_status_final == "conflict" -> RESOLVED conflicts overwrite (logged old->new);
                                       UNRESOLVED/VARIANT-SPLIT-NEEDED/DB-CLEANUP are skipped;
                                       ordinary NULL fields on conflict-products are filled
                                       the same conservative way as (2).
  4. VARIANT-SPLIT-NEEDED entries  -> collected into docs/datasheet_import_variant_splits_needed.md,
                                       never auto-split.
  5. Company-wide context fan-out  -> PATCH every Base-Model/Product/Company row of that company,
                                       NULL-fill only.

Usage:
    python3 scripts/import_datasheet_project_20260822.py --dry-run   # (default) preview only
    python3 scripts/import_datasheet_project_20260822.py --run       # actually write to Airtable
"""
import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA_RAW = ROOT / "data" / "raw"
AUDIT_PATH = DOCS / "import_datasheet_project_20260822_audit.jsonl"
VARIANT_REPORT_PATH = DOCS / "datasheet_import_variant_splits_needed.md"
RATE_LIMIT_SLEEP = 0.25
TODAY = date.today().isoformat()

DRY = True  # flipped in main()

# ─────────────────────────────────────────────────────────────────── loaders
def load_env():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()
TOKEN = ENV.get("AIRTABLE_TOKEN", "")
BASE_ID = ENV.get("AIRTABLE_BASE_ID", "")

TBL_NAMES = {
    "companies": "Companies",
    "base_models": "Base Models",
    "products": "Products",
    "extensions": "Base Model Extensions",
}

FIELDS = json.loads((ROOT / "config" / "fields.json").read_text())
FIELD_BY_NAME = {f["field_name"]: f for f in FIELDS.values()}


def read_csv(name):
    with open(DATA_RAW / f"{name}.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


COMPANIES = read_csv("companies")
PRODUCTS = read_csv("products")
BASE_MODELS = read_csv("base_models")
EXTENSIONS = read_csv("base_model_extensions")

CO_BY_NAME = {r["company_name"]: r for r in COMPANIES}
PROD_BY_CO_AND_NAME = defaultdict(dict)
for r in PRODUCTS:
    PROD_BY_CO_AND_NAME[r["company_id"]][r["product_name"]] = r
PRODUCTS_BY_CO = defaultdict(list)
for r in PRODUCTS:
    PRODUCTS_BY_CO[r["company_id"]].append(r)
EXT_BY_BM_AIRTABLE_ID = {r["base_model_id"]: r for r in EXTENSIONS}


def resolve_product(company, product_name):
    co = CO_BY_NAME.get(company)
    if not co:
        return None
    return PROD_BY_CO_AND_NAME.get(co["airtable_id"], {}).get(product_name)


def resolve_extension(company, product_name):
    prod = resolve_product(company, product_name)
    if not prod:
        return None
    return EXT_BY_BM_AIRTABLE_ID.get(prod["base_model_id"])


STATUS = json.loads((DOCS / "datasheet_db_status_final.json").read_text())
MERGED = json.loads((DOCS / "sonnet_opus_merged_dataset.json").read_text())
CHALLENGE = json.loads((DOCS / "sonnet_opus_cwc_challenge_results.json").read_text())

_source_cache = {}


def load_source_file(rel_path):
    if not rel_path:
        return None
    if rel_path not in _source_cache:
        try:
            _source_cache[rel_path] = json.loads((ROOT / rel_path).read_text())
        except Exception:
            _source_cache[rel_path] = None
    return _source_cache[rel_path]


def lookup_product_type_from_source(rel_path, product_name):
    data = load_source_file(rel_path)
    if not data:
        return None
    for p in data.get("products", []):
        if p.get("product_name") == product_name:
            return p.get("product_type")
    return None


# ───────────────────────────────────────────────────────────── value helpers
def is_empty_csv(v):
    return v is None or v == ""


def coerce_current(field_name, raw):
    """CSV string -> python-typed value, per AP0 data_type. Empty -> None (Blank != Zero)."""
    if is_empty_csv(raw):
        return None
    spec = FIELD_BY_NAME.get(field_name)
    dtype = spec["data_type"] if spec else "Text"
    if dtype == "Multi-Select":
        return [v for v in raw.split("|") if v]
    if dtype == "Boolean":
        return raw.strip().lower() == "true"
    if dtype == "Integer":
        try:
            return int(float(raw))
        except ValueError:
            return raw
    if dtype == "Float":
        try:
            return float(raw)
        except ValueError:
            return raw
    return raw


def values_equal(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, list) or isinstance(b, list):
        la = a if isinstance(a, list) else [a]
        lb = b if isinstance(b, list) else [b]
        return set(str(x) for x in la) == set(str(x) for x in lb)
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def check_allowed(field_name, value):
    """Soft AP0 allowed_values check -- returns a warning string or None. Never blocks."""
    spec = FIELD_BY_NAME.get(field_name)
    if not spec or not spec.get("allowed_values") or value is None:
        return None
    allowed = set(spec["allowed_values"])
    vals = value if isinstance(value, list) else [value]
    bad = [v for v in vals if str(v) not in allowed]
    if bad:
        return f"{field_name}={value!r} not in AP0 allowed_values {sorted(allowed)}"
    return None


# ─────────────────────────────────────────────────────── conflict classifier
NOOP_PATTERNS = [
    r"\bkeep db\b", r"\bdo not import\b", r"\bdo not overwrite\b",
    r"\balready correct\b", r"\bdb is correct\b", r"\bdb is\b.*\bright\b",
    r"\bdb\s+[\d.]+\s+stands\b", r"\bimmaterial\b", r"\bdb is\b.*\bbelongs to\b",
]
NOOP_RE = re.compile("|".join(NOOP_PATTERNS), re.I)
FANOUT_RE = re.compile(r"do not fan out to (\w[\w\s]*?)(?:[.;]|$)", re.I)
LEADING_NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?")
LEADING_BOOL_RE = re.compile(r"^(True|False)\b")


def _strip_paren(s):
    m = re.match(r"^(.*?)\s*\([^)]*\)\s*$", s)
    return m.group(1).strip() if m else s


def classify_conflict(conflict):
    """RESOLVED conflict -> (action, value). action in:
    NOOP, NOOP-FANOUT, WRITE-num, WRITE-bool, WRITE-num-fallback, WRITE-union,
    WRITE-categorical, AMBIGUOUS.
    """
    text = conflict["triage_correct_value"].strip()
    db_row = conflict.get("db_row", "")
    field = conflict["field"]
    spec = FIELD_BY_NAME.get(field, {})
    unit = spec.get("unit") or ""

    m = FANOUT_RE.search(text)
    if m and m.group(1).strip().lower() in db_row.lower():
        return ("NOOP-FANOUT", None)

    mb = LEADING_BOOL_RE.match(text)
    if mb:
        return ("WRITE-bool", mb.group(1) == "True")
    mn = LEADING_NUM_RE.match(text)
    if mn:
        return ("WRITE-num", float(mn.group(0)))

    if NOOP_RE.search(text):
        return ("NOOP", None)

    if unit and not isinstance(conflict["db_value"], list):
        mu = re.search(r"(-?\d+(?:\.\d+)?)\s*" + re.escape(unit) + r"\b", text)
        if mu:
            return ("WRITE-num-fallback", float(mu.group(1)))

    first_part = re.split(r"\s+—", text)[0].strip()
    bare = _strip_paren(first_part)
    if isinstance(conflict["db_value"], list):
        if text.lower().startswith("union"):
            union = list(dict.fromkeys(
                conflict["db_value"] + [v for v in conflict["datasheet_value"] if v not in conflict["db_value"]]
            ))
            return ("WRITE-union", union)
        if isinstance(conflict["datasheet_value"], list):
            if first_part in conflict["datasheet_value"]:
                return ("WRITE-categorical", first_part)
            if bare in conflict["datasheet_value"]:
                return ("WRITE-categorical", bare)
        return ("AMBIGUOUS", text)

    if first_part == str(conflict["datasheet_value"]):
        return ("WRITE-categorical", first_part)
    if bare == str(conflict["datasheet_value"]):
        return ("WRITE-categorical", bare)
    return ("AMBIGUOUS", text)


# ───────────────────────────────────────────────────── company-wide context
CHALLENGE_COMPANIES = {r["company"] for r in CHALLENGE["results"]}

CWC_RAW_FILES_EXCLUDE_SUBSTR = None  # placeholder, unused


def load_company_wide_context():
    """Returns (cwc: {company: {field: value}}, sources: {company: {field: str}}, internal_conflicts: [str])."""
    cwc = defaultdict(dict)
    sources = defaultdict(dict)
    internal_conflicts = []

    # 1) raw opus company_wide_context blocks, for companies NOT in the challenge file
    for path in sorted(DOCS.glob("research_findings_opus_20260808_*.json")):
        data = json.loads(path.read_text())
        block = data.get("company_wide_context")
        company = data.get("company")
        if not block or not company or company in CHALLENGE_COMPANIES:
            continue
        for field, value in block.get("fields", {}).items():
            if value is None:
                continue
            if field not in FIELD_BY_NAME:
                internal_conflicts.append(f"{company}: unknown field '{field}' in {path.name}, skipped")
                continue
            existing = cwc[company].get(field)
            if existing is None:
                cwc[company][field] = value
                sources[company][field] = f"opus_raw:{path.name}"
            elif isinstance(existing, list) and isinstance(value, list):
                union = list(dict.fromkeys(existing + [v for v in value if v not in existing]))
                if union != existing:
                    cwc[company][field] = union
                    sources[company][field] += f" + union-merged:{path.name}"
            elif not values_equal(existing, value):
                internal_conflicts.append(
                    f"{company}.{field}: '{existing}' (from {sources[company][field]}) vs "
                    f"'{value}' (from {path.name}) -- kept first, FLAGGED"
                )

    # 2) reconciled challenge verdicts, for the 4 challenge companies (authoritative, overrides raw opus)
    for r in CHALLENGE["results"]:
        company = r["company"]
        field = r["field"]
        value = r["correct_value"]
        if value is None:
            continue
        if field not in FIELD_BY_NAME:
            internal_conflicts.append(f"{company}: unknown field '{field}' in challenge results, skipped")
            continue
        cwc[company][field] = value
        sources[company][field] = f"challenge:{r['verdict']}"

    return dict(cwc), dict(sources), internal_conflicts


CWC, CWC_SOURCES, CWC_INTERNAL_CONFLICTS = load_company_wide_context()


# ──────────────────────────────────────────────────────────────────── plan
def new_plan():
    return {
        "new_companies": [],       # {name, fields}
        "new_inserts": [],         # {company, base_model_name, product_name, product_type,
                                    #  bm_fields, prod_fields, ext_fields, base_model_airtable_id (shared, optional), notes}
        "enrich_fills": [],        # {company, db_row, entity, field, new, table_hint}
        "conflict_overwrites": [], # {company, db_row, field, old, new, raw_triage, level}
        "multiselect_extend_patches": [],  # {company, db_row, field, old, new}
        "cwc_patches": [],         # {company, entity, target_label, field, new}
        "deactivate": [],         # {company, db_row, product_id, field, old, new, reason}
        "variant_split_needed": [],  # raw conflict rows
        "skipped_unresolved": [],
        "skipped_db_cleanup": [],
        "skipped_ambiguous": [],
        "flags": [],
        "allowed_value_warnings": [],
        "confirmed_noop_mismatches": [],  # Tech Lead-confirmed "DB is correct" -- not a flag
        "new_company_cwc_folded": [],     # CWC fields folded into a same-run new company/product
    }


PLAN = new_plan()


def _flag(msg):
    PLAN["flags"].append(msg)


def _record_value_check(field, value):
    w = check_allowed(field, value)
    if w:
        PLAN["allowed_value_warnings"].append(w)


# ---- (1) NEW products ------------------------------------------------------
_STANDALONE_DUP_SKIP_KEYS = {
    # standalone flat duplicate of a variant already covered inside a nested
    # "A / B" composite key for the same company -- see Flags in the report.
    "ek robotics||ek robotics VNA MOVE 1500",
}

_SHARED_BASE_MODEL_OVERRIDES = {
    # Standing Tech Lead decision: Magazino SOTO's Jungheinrich-brand counterpart
    # creates a NEW Jungheinrich-company Product row sharing the EXISTING SOTO
    # base model (OEM-rebadge pattern) -- not a new base model, not a duplicate.
    "Magazino||Jungheinrich SOTO": {
        "company": "Jungheinrich AG",
        "product_name": "Jungheinrich SOTO",
        "shared_base_model_company": "Magazino",
        "shared_base_model_product_name": "SOTO",
    },
}

_CONFIRMED_NOOP_MISMATCHES = {
    # Standing Tech Lead decision (2026-08-23 review round): DB value confirmed correct,
    # dataset's ['CE'] is an incomplete simplification -- keep DB, resolved not skipped.
    ("Geek+ (Geekplus Technology Co.)", "Geek+ F12ML", "certifications_generic"),
    ("Geek+ (Geekplus Technology Co.)", "Geek+ F-Series (F20MT Smart Forklift)", "certifications_generic"),
}

_VARIANT_SPLIT_PLAN = {
    # Standing Tech Lead decision (2026-08-23 review round): "Zwei/drei Zeilen bitte" -- these
    # blended single DB rows carry a per-sub-config value map (on vehicle_length and, for
    # K-MATIC, also vehicle_width) that cannot be resolved onto one row. Split into N new
    # Product/Base Model/Extension rows, one per sub-config. The existing blended DB row is
    # DEACTIVATED (active=False, soft-delete per OI-118 convention) by this same script run --
    # see the VARIANT-SPLIT flag and the "deactivate" plan bucket for each key. Any other
    # patches already planned for that same row (enrich-fill / conflict-overwrite /
    # multiselect-extend) are retracted -- see plan_variant_splits().
    "Linde Material Handling||Linde L-MATIC AC": {
        "splits": [
            {"dict_key": "L-MATIC AC 1,2 t", "product_name": "Linde L-MATIC AC 1.2t"},
            {"dict_key": "L-MATIC AC 1,6 t", "product_name": "Linde L-MATIC AC 1.6t"},
        ],
    },
    "Linde Material Handling||Linde L-MATIC AC k": {
        "splits": [
            {"dict_key": "L-MATIC 12 AC k", "product_name": "Linde L-MATIC AC k 12"},
            {"dict_key": "L-MATIC 16 AC k", "product_name": "Linde L-MATIC AC k 16"},
        ],
    },
    "Linde Material Handling||Linde K-MATIC": {
        "splits": [
            {"dict_key": "7.2 m mast config", "product_name": "Linde K-MATIC (low lift, 7.2m mast)"},
            {"dict_key": "11.55 m mast config", "product_name": "Linde K-MATIC (medium lift, 11.55m mast)"},
            {"dict_key": "14.35 m mast config", "product_name": "Linde K-MATIC (high lift, 14.35m mast)"},
        ],
    },
}


def _route_fields_by_entity(fields_dict):
    """Split a flat {field_name: value} dict by AP0 entity."""
    bm, prod, co, unknown = {}, {}, {}, {}
    for k, v in fields_dict.items():
        spec = FIELD_BY_NAME.get(k)
        if not spec:
            unknown[k] = v
            continue
        if spec["entity"] == "Base Model":
            bm[k] = v
        elif spec["entity"] == "Product":
            prod[k] = v
        elif spec["entity"] == "Company":
            co[k] = v
        else:
            unknown[k] = v
    return bm, prod, co, unknown


def _resolve_product_type(status_entry, fields_dict):
    if fields_dict.get("product_type") is not None:
        return fields_dict["product_type"], "dataset"
    pt = lookup_product_type_from_source(status_entry.get("sonnet_source_file"), status_entry["product_name"])
    if not pt:
        pt = lookup_product_type_from_source(status_entry.get("opus_source_file"), status_entry["product_name"])
    return pt, "source_file_fallback" if pt else None


def _source_note(status_entry, provenance):
    return (
        f"Datasheet ingestion project (2026-08-11..21). "
        f"sonnet_source={status_entry.get('sonnet_source_file')}; "
        f"opus_source={status_entry.get('opus_source_file')}. "
        f"Field provenance: {json.dumps(provenance, ensure_ascii=False)}"
    )[:9000]


def plan_new_products():
    for p in STATUS["products"]:
        if p["db_status_final"] != "new":
            continue
        key = p["key"]
        if key in _STANDALONE_DUP_SKIP_KEYS:
            _flag(f"NEW-SKIP (duplicate): '{key}' looks like a standalone duplicate of a variant "
                  f"already covered by a nested composite entry for the same company -- skipped, "
                  f"needs Tech Lead confirmation before --run.")
            continue

        entry = MERGED.get(key, {})
        fields_dict = entry.get("fields", {})
        # nested per-variant dict? (any top-level key is not a known AP0 field_name)
        unknown_keys = [k for k in fields_dict if k not in FIELD_BY_NAME]
        if unknown_keys:
            for variant_name in unknown_keys:
                variant_fields = fields_dict[variant_name]
                _plan_one_new_product(p, variant_name, variant_fields, entry.get("provenance", {}).get(variant_name, {}))
            continue

        override = _SHARED_BASE_MODEL_OVERRIDES.get(key)
        if override:
            _plan_shared_base_model_new_product(p, override, fields_dict, entry.get("provenance", {}))
            continue

        _plan_one_new_product(p, p["product_name"], fields_dict, entry.get("provenance", {}))


def _plan_one_new_product(status_entry, product_name, fields_dict, provenance):
    company = status_entry["company"]
    bm_fields, prod_fields, co_fields, unknown = _route_fields_by_entity(fields_dict)
    if unknown:
        _flag(f"NEW '{company}||{product_name}': unrouted fields (not in fields.json), skipped: {unknown}")

    product_type, pt_source = _resolve_product_type(status_entry, fields_dict)
    if not product_type:
        _flag(f"NEW-SKIP (no product_type): '{company}||{product_name}' has no product_type in "
              f"the merged dataset nor in its original source files -- cannot create Base Model / "
              f"Product without a type. Skipped, needs manual product_type before --run.")
        return
    if pt_source == "source_file_fallback":
        _flag(f"NEW '{company}||{product_name}': product_type '{product_type}' recovered from "
              f"original per-company research file (not present in merged dataset).")

    company_is_new = company not in CO_BY_NAME
    if company_is_new:
        existing = [c for c in PLAN["new_companies"] if c["name"] == company]
        if not existing:
            PLAN["new_companies"].append({"name": company, "fields": {}})

    for k, v in co_fields.items():
        # Company-entity field on a "new" product: route to a company-level enrich-fill,
        # never bundled into the product/extension payload. Existing company only here
        # (a brand-new company's fields would need separate research -- none supplied).
        if v is None:
            continue  # dataset explicitly has no information for this field -- nothing to act on
        if company_is_new:
            _flag(f"NEW '{company}||{product_name}': Company-entity field '{k}'={v!r} found for a "
                  f"NOT-YET-existing company -- no company research data supplied for this batch, "
                  f"left unset, flagged for manual follow-up.")
            continue
        current = coerce_current(k, CO_BY_NAME[company].get(k, ""))
        if current is None:
            _record_value_check(k, v)
            PLAN["enrich_fills"].append({
                "company": company, "db_row": f"(company record) {company}", "entity": "Company",
                "field": k, "new": v, "table_hint": "companies",
            })

    for k, v in co_fields.items():
        pass  # already handled above

    _record_value_check("product_type", product_type)
    for k, v in bm_fields.items():
        _record_value_check(k, v)
    for k, v in prod_fields.items():
        _record_value_check(k, v)

    PLAN["new_inserts"].append({
        "company": company,
        "company_is_new": company_is_new,
        "base_model_name": product_name,
        "product_name": product_name,
        "product_type": product_type,
        "bm_fields": bm_fields,
        "prod_fields": prod_fields,
        "ext_fields": {**bm_fields},
        "shared_base_model": None,
        "notes": _source_note(status_entry, provenance),
    })


def _plan_shared_base_model_new_product(status_entry, override, fields_dict, provenance):
    company = override["company"]
    product_name = override["product_name"]
    shared_bm_company = override["shared_base_model_company"]
    shared_bm_product = override["shared_base_model_product_name"]

    if company not in CO_BY_NAME:
        _flag(f"NEW-SKIP (shared base model): target company '{company}' does not exist -- cannot "
              f"attach '{product_name}' to it.")
        return
    shared_prod = resolve_product(shared_bm_company, shared_bm_product)
    if not shared_prod:
        _flag(f"NEW-SKIP (shared base model): could not resolve existing '{shared_bm_company}||"
              f"{shared_bm_product}' to share a base model with -- '{product_name}' skipped.")
        return

    bm_fields, prod_fields, co_fields, unknown = _route_fields_by_entity(fields_dict)
    if co_fields or unknown:
        _flag(f"NEW '{company}||{product_name}' (shared base model): unexpected non-Base-Model "
              f"fields ignored for this special-cased insert: co={co_fields} unknown={unknown}")

    product_type = fields_dict.get("product_type") or shared_prod.get("product_type")

    PLAN["new_inserts"].append({
        "company": company,
        "company_is_new": False,
        "base_model_name": None,  # no new base model -- shares the existing one
        "product_name": product_name,
        "product_type": product_type,
        "bm_fields": {},
        "prod_fields": prod_fields,
        "ext_fields": {},  # extension already exists (shared), nothing new to write (0 fields in this batch)
        "shared_base_model": {
            "via": f"{shared_bm_company}||{shared_bm_product}",
            "base_model_airtable_id": shared_prod["base_model_id"],
        },
        "notes": _source_note(status_entry, provenance) + " OEM-rebadge: shares base model with "
                 f"'{shared_bm_company}||{shared_bm_product}' per standing Tech Lead decision.",
    })


# ---- (2)+(3) matched products: enrich + conflict ---------------------------
def plan_matched_products():
    for p in STATUS["products"]:
        if p["db_status_final"] not in ("enrich", "conflict"):
            continue
        key = p["key"]
        entry = MERGED.get(key, {})
        fields_dict = entry.get("fields", {})
        unknown_keys = [k for k in fields_dict if k not in FIELD_BY_NAME]

        conflicts_by_row = defaultdict(list)
        for c in p.get("conflicts", []):
            conflicts_by_row[c["db_row"]].append(c)
        extends_by_row = defaultdict(list)
        for e in p.get("multiselect_extends", []):
            extends_by_row[e["db_row"]].append(e)
        subset_by_row = defaultdict(list)
        for s in p.get("multiselect_subset_of_db", []):
            subset_by_row[s["db_row"]].append(s)

        if unknown_keys:
            # nested per-variant dict (e.g. ek robotics X MOVE 600/1200): each variant name IS a db_row
            for variant_name in unknown_keys:
                matched_row = variant_name if variant_name in p["db_product_rows"] else None
                if matched_row is None:
                    # dataset variant label sometimes drops a company/brand prefix the DB row keeps
                    # (e.g. dataset 'X MOVE 600' vs DB row 'ek robotics X MOVE 600') -- only resolve
                    # via substring containment when exactly one DB row qualifies; never guess.
                    candidates = [r for r in p["db_product_rows"] if variant_name in r or r in variant_name]
                    if len(candidates) == 1:
                        matched_row = candidates[0]
                if matched_row is None:
                    _flag(f"'{key}': nested variant '{variant_name}' not found in db_product_rows "
                          f"{p['db_product_rows']} -- skipped.")
                    continue
                _plan_one_matched_row(
                    p, matched_row, fields_dict[variant_name],
                    conflicts_by_row.get(matched_row, []),
                    extends_by_row.get(matched_row, []),
                    subset_by_row.get(matched_row, []),
                )
            continue

        for db_row in p["db_product_rows"]:
            _plan_one_matched_row(
                p, db_row, fields_dict,
                conflicts_by_row.get(db_row, []),
                extends_by_row.get(db_row, []),
                subset_by_row.get(db_row, []),
            )


def _plan_one_matched_row(status_entry, db_row, fields_dict, conflicts, extends, subsets):
    company = status_entry["company"]
    ext = resolve_extension(company, db_row)
    prod = resolve_product(company, db_row)
    if not ext or not prod:
        _flag(f"'{status_entry['key']}' db_row '{db_row}': could not resolve extension/product "
              f"record -- skipped.")
        return

    handled_fields = set()

    # -- conflicts --
    for c in conflicts:
        field = c["field"]
        handled_fields.add(field)
        verdict = c["triage_verdict"]
        if verdict == "UNRESOLVED":
            PLAN["skipped_unresolved"].append({"company": company, "db_row": db_row, "field": field,
                                                "reasoning": c.get("triage_reasoning", "")})
            continue
        if verdict == "VARIANT-SPLIT-NEEDED":
            PLAN["variant_split_needed"].append({"company": company, "db_row": db_row, "field": field,
                                                  "db_value": c["db_value"], "datasheet_value": c["datasheet_value"],
                                                  "note": c.get("triage_correct_value", "")})
            continue
        if verdict == "DB-CLEANUP":
            PLAN["skipped_db_cleanup"].append({"company": company, "db_row": db_row, "field": field,
                                                "note": c.get("triage_correct_value", "")})
            continue
        if verdict != "RESOLVED":
            _flag(f"'{status_entry['key']}' db_row '{db_row}' field '{field}': unknown triage_verdict "
                  f"'{verdict}' -- skipped.")
            continue

        action, value = classify_conflict(c)
        if action in ("NOOP", "NOOP-FANOUT"):
            continue
        if action == "AMBIGUOUS":
            PLAN["skipped_ambiguous"].append({"company": company, "db_row": db_row, "field": field,
                                               "raw_triage": c["triage_correct_value"]})
            continue

        # normalize WRITE-* values to python types matching current-field's data_type
        spec = FIELD_BY_NAME.get(field, {})
        if action in ("WRITE-num", "WRITE-num-fallback") and spec.get("data_type") == "Integer":
            value = int(round(value))

        current = coerce_current(field, ext.get(field, ""))
        if values_equal(current, value):
            continue  # already matches (e.g. "Keep DB X" cases that leaked past NOOP, or exact re-confirmation)

        _record_value_check(field, value)
        PLAN["conflict_overwrites"].append({
            "company": company, "db_row": db_row, "field": field,
            "old": current, "new": value, "level": c.get("level"),
            "raw_triage": c["triage_correct_value"],
        })

    # -- multiselect extends (union, non-destructive per method definition) --
    for e in extends:
        field = e["field"]
        handled_fields.add(field)
        current = coerce_current(field, ext.get(field, ""))
        db_value = current if current is not None else []
        union = list(dict.fromkeys((db_value or []) + [v for v in e["datasheet_value"] if v not in (db_value or [])]))
        if values_equal(current, union):
            continue
        _record_value_check(field, union)
        PLAN["multiselect_extend_patches"].append({
            "company": company, "db_row": db_row, "field": field, "old": current, "new": union,
        })

    # -- multiselect subset of DB: DB already dominates, no action --
    for s in subsets:
        handled_fields.add(s["field"])

    # -- ordinary NULL-fill fields (remaining flat dataset fields not already handled) --
    for field, value in fields_dict.items():
        if field in handled_fields:
            continue
        if value is None:
            continue  # dataset explicitly has no information for this field -- nothing to act on
        if isinstance(value, dict):
            # per-sub-config value map (e.g. max_payload varying by ARNY variant). Resolve if the
            # dict is keyed by this exact db_row name; otherwise it's a sub-model-config split
            # (e.g. Linde mast configs) that the single DB row cannot hold -- do not guess.
            if db_row in value:
                value = value[db_row]
                if value is None:
                    continue
            elif status_entry["key"] in _VARIANT_SPLIT_PLAN:
                # Handled by plan_variant_splits() instead: new per-sub-config Product/Base
                # Model/Extension rows are created there, each with its own resolved slice of
                # this map. Nothing to do for the existing blended row's own field.
                continue
            else:
                _flag(f"'{status_entry['key']}' db_row '{db_row}' field '{field}': dataset value is "
                      f"a per-sub-config map {value!r} that does not key on this db_row, and this "
                      f"product resolves to only {len(status_entry['db_product_rows'])} DB row(s) "
                      f"-- cannot resolve without a variant split. SKIPPED, needs Tech Lead decision.")
                continue
        spec = FIELD_BY_NAME.get(field)
        if not spec:
            _flag(f"'{status_entry['key']}' db_row '{db_row}': field '{field}' not in fields.json, skipped.")
            continue
        target_table = {"Base Model": "extensions", "Product": "products", "Company": "companies"}.get(spec["entity"])
        if target_table == "extensions":
            current = coerce_current(field, ext.get(field, ""))
        elif target_table == "products":
            current = coerce_current(field, prod.get(field, ""))
        elif target_table == "companies":
            current = coerce_current(field, CO_BY_NAME.get(company, {}).get(field, ""))
        else:
            _flag(f"'{status_entry['key']}' db_row '{db_row}': field '{field}' has unroutable entity "
                  f"'{spec['entity']}', skipped.")
            continue

        if current is None:
            _record_value_check(field, value)
            PLAN["enrich_fills"].append({
                "company": company, "db_row": db_row, "entity": spec["entity"],
                "field": field, "new": value, "table_hint": target_table,
            })
        elif values_equal(current, value):
            continue  # already matches, no action needed
        else:
            if (company, db_row, field) in _CONFIRMED_NOOP_MISMATCHES:
                PLAN["confirmed_noop_mismatches"].append({
                    "company": company, "db_row": db_row, "field": field,
                    "db_value": current, "dataset_value": value,
                    "note": "Tech Lead confirmed DB value correct (2026-08-23 review round) -- "
                            "no-op, dataset value not applied.",
                })
                continue
            _flag(f"UNEXPECTED MISMATCH (not in conflicts list): '{status_entry['key']}' db_row "
                  f"'{db_row}' field '{field}': live DB={current!r} vs dataset={value!r} -- SKIPPED, "
                  f"needs manual review (frozen status report may be stale, or this needs its own "
                  f"conflict-triage entry).")


# ---- (4) variant splits (blended DB row -> N new per-sub-config rows) ------
def _pop_matching(bucket, company, db_row):
    """Remove and return all PLAN[bucket] entries matching (company, db_row). Used to retract
    already-planned enrich/conflict/multiselect patches for a blended row that is about to be
    deactivated in this same run -- no point patching a row that's being retired."""
    keep, removed = [], []
    for it in PLAN[bucket]:
        if it["company"] == company and it.get("db_row") == db_row:
            removed.append(it)
        else:
            keep.append(it)
    PLAN[bucket] = keep
    return removed


def _resolved_field_state(company, db_row):
    """Final 'correct' field state for an existing matched DB row: current live-DB values,
    overridden by any patch already planned for this exact (company, db_row) by
    plan_matched_products() (conflict resolutions / NULL-fills / multiselect unions). Used only
    to seed variant-split new rows with the blended row's own already-resolved values -- never
    touches Airtable, purely reads from PLAN + the CSV snapshot.
    """
    prod = resolve_product(company, db_row)
    ext = resolve_extension(company, db_row)
    co = CO_BY_NAME.get(company, {})
    state = {}
    for field_name, spec in FIELD_BY_NAME.items():
        entity = spec["entity"]
        if entity == "Base Model":
            raw = ext.get(field_name, "") if ext else ""
        elif entity == "Product":
            raw = prod.get(field_name, "") if prod else ""
        elif entity == "Company":
            raw = co.get(field_name, "")
        else:
            continue
        val = coerce_current(field_name, raw)
        if val is not None:
            state[field_name] = val
    for it in PLAN["conflict_overwrites"] + PLAN["enrich_fills"] + PLAN["multiselect_extend_patches"]:
        if it["company"] == company and it.get("db_row") == db_row:
            state[it["field"]] = it["new"]
    return state


def plan_variant_splits():
    for key, cfg in _VARIANT_SPLIT_PLAN.items():
        status_entry = next((p for p in STATUS["products"] if p["key"] == key), None)
        if not status_entry:
            _flag(f"VARIANT-SPLIT: status entry for '{key}' not found -- skipped.")
            continue
        company = status_entry["company"]
        db_rows = status_entry.get("db_product_rows") or []
        if len(db_rows) != 1:
            _flag(f"VARIANT-SPLIT: '{key}' does not resolve to exactly one existing DB row "
                  f"({db_rows!r}) -- skipped, needs manual handling.")
            continue
        db_row = db_rows[0]

        entry = MERGED.get(key, {})
        fields_dict = entry.get("fields", {})
        provenance = entry.get("provenance", {})
        dict_fields = {k: v for k, v in fields_dict.items() if isinstance(v, dict)}

        base_state = _resolved_field_state(company, db_row)

        removed_enrich = _pop_matching("enrich_fills", company, db_row)
        removed_conflict = _pop_matching("conflict_overwrites", company, db_row)
        removed_ms = _pop_matching("multiselect_extend_patches", company, db_row)
        n_retracted = len(removed_enrich) + len(removed_conflict) + len(removed_ms)

        for split in cfg["splits"]:
            variant_state = dict(base_state)
            for field, valmap in dict_fields.items():
                if split["dict_key"] in valmap:
                    v = valmap[split["dict_key"]]
                    if v is None:
                        variant_state.pop(field, None)
                    else:
                        variant_state[field] = v
                else:
                    _flag(f"VARIANT-SPLIT '{key}': field '{field}' per-sub-config map has no entry "
                          f"for split label '{split['dict_key']}' -- left at blended-row value "
                          f"for '{split['product_name']}'.")

            bm_fields, prod_fields, co_fields, unknown = _route_fields_by_entity(variant_state)
            if unknown:
                _flag(f"VARIANT-SPLIT '{key}' -> '{split['product_name']}': unrouted fields "
                      f"(not in fields.json) skipped: {unknown}")
            # co_fields (e.g. country, hq_city) are expected here -- they're the company's own
            # already-set fields read by _resolved_field_state(); company-wide, not duplicated
            # onto the split row. Not flagged: this happens for every split by design, not an
            # anomaly needing Tech Lead review.

            product_type = prod_fields.get("product_type")
            if not product_type:
                _flag(f"VARIANT-SPLIT '{key}' -> '{split['product_name']}': no product_type in "
                      f"resolved state -- cannot create row. SKIPPED.")
                continue

            for k, v in prod_fields.items():
                _record_value_check(k, v)
            for k, v in bm_fields.items():
                _record_value_check(k, v)

            PLAN["new_inserts"].append({
                "company": company,
                "company_is_new": False,
                "base_model_name": split["product_name"],
                "product_name": split["product_name"],
                "product_type": product_type,
                "bm_fields": bm_fields,
                "prod_fields": prod_fields,
                "ext_fields": {**bm_fields},
                "shared_base_model": None,
                "notes": _source_note(status_entry, provenance) + " VARIANT SPLIT (Tech Lead "
                         f"decision, 2026-08-23 review round): one of {len(cfg['splits'])} new "
                         f"rows split out of the existing blended DB row '{db_row}', which the "
                         "single-row schema could not represent (per-sub-config vehicle_length"
                         + ("/vehicle_width" if len(dict_fields) > 1 else "")
                         + " map). Non-variant-specific fields carried over from the blended "
                         "row's own resolved state (current DB values + this batch's own "
                         "conflict resolutions / NULL-fills).",
            })

        old_prod = resolve_product(company, db_row)
        old_active = None
        if old_prod is not None:
            old_active = str(old_prod.get("active", "")).strip().lower() == "true"
        PLAN["deactivate"].append({
            "company": company, "db_row": db_row,
            "product_id": old_prod.get("product_id") if old_prod else None,
            "field": "active", "old": old_active, "new": False,
            "reason": f"superseded by VARIANT-SPLIT '{key}' into {len(cfg['splits'])} new rows",
        })

        retracted_note = (f"{n_retracted} previously-planned patch(es) for this row "
                           f"(enrich-fill/conflict-overwrite/multiselect-extend) were retracted."
                           if n_retracted else "no other patches were planned for this row.")
        _flag(f"VARIANT-SPLIT '{key}': created {len(cfg['splits'])} new product rows "
              f"({', '.join(s['product_name'] for s in cfg['splits'])}) to replace the blended "
              f"per-sub-config data. The EXISTING DB row '{db_row}' is DEACTIVATED "
              f"(active=False, see 'deactivate' plan bucket) by this same script run -- "
              f"{retracted_note}")


# ---- (5) company-wide context fan-out --------------------------------------
_NEW_COMPANY_CWC_APPLIED = set()


def apply_new_company_cwc():
    """A company created in THIS SAME run is invisible to CO_BY_NAME (built once from the live-DB
    CSV snapshot at import time), so the ordinary plan_cwc_fanout() post-hoc pass below always
    skips it. Fold that company's company_wide_context fields directly into the initial
    company/base-model/product creation payloads instead -- NULL-fill only, same semantics as
    plan_cwc_fanout(), just applied at creation-time against this batch's own new_inserts rather
    than against a live DB record."""
    for co_entry in PLAN["new_companies"]:
        company = co_entry["name"]
        field_values = CWC.get(company)
        if not field_values:
            continue
        company_inserts = [it for it in PLAN["new_inserts"]
                            if it["company"] == company and it["company_is_new"]]
        if not company_inserts:
            continue
        _NEW_COMPANY_CWC_APPLIED.add(company)
        for field, value in field_values.items():
            spec = FIELD_BY_NAME.get(field)
            if not spec:
                continue
            entity = spec["entity"]
            source = CWC_SOURCES[company][field]
            if entity == "Company":
                if field not in co_entry["fields"]:
                    _record_value_check(field, value)
                    co_entry["fields"][field] = value
                    PLAN["new_company_cwc_folded"].append({
                        "company": company, "target": f"(company record) {company}",
                        "field": field, "new": value, "source": source,
                    })
                continue
            target_dict_key = {"Base Model": "bm_fields", "Product": "prod_fields"}.get(entity)
            if target_dict_key is None:
                continue
            for it in company_inserts:
                target_dict = it[target_dict_key]
                if field in target_dict:
                    if not values_equal(target_dict[field], value):
                        _flag(f"CWC (new-company fold-in) '{company}'.{field} on new "
                              f"'{it['product_name']}': product's own datasheet value "
                              f"{target_dict[field]!r} kept, CWC value {value!r} NOT applied "
                              f"(fold-in is NULL-fill only, same as the ordinary fan-out pass).")
                    continue
                _record_value_check(field, value)
                target_dict[field] = value
                if target_dict_key == "bm_fields":
                    it["ext_fields"][field] = value
                PLAN["new_company_cwc_folded"].append({
                    "company": company, "target": it["product_name"],
                    "field": field, "new": value, "source": source,
                })


def plan_cwc_fanout():
    for company, field_values in CWC.items():
        if company in _NEW_COMPANY_CWC_APPLIED:
            continue  # already folded into this batch's own new-company creation payload
        co = CO_BY_NAME.get(company)
        if not co:
            _flag(f"CWC: company '{company}' not found in DB -- skipped entirely.")
            continue
        for field, value in field_values.items():
            spec = FIELD_BY_NAME.get(field)
            if not spec:
                continue
            entity = spec["entity"]
            if entity == "Company":
                current = coerce_current(field, co.get(field, ""))
                if current is None:
                    _record_value_check(field, value)
                    PLAN["cwc_patches"].append({
                        "company": company, "entity": "Company", "target_label": company,
                        "field": field, "new": value, "source": CWC_SOURCES[company][field],
                    })
                elif not values_equal(current, value):
                    _flag(f"CWC '{company}'.{field}: company record already has non-null "
                          f"{current!r}, dataset says {value!r} -- NOT overwritten (fan-out is "
                          f"NULL-fill only).")
            elif entity == "Product":
                for prod in PRODUCTS_BY_CO.get(co["airtable_id"], []):
                    current = coerce_current(field, prod.get(field, ""))
                    if current is None:
                        _record_value_check(field, value)
                        PLAN["cwc_patches"].append({
                            "company": company, "entity": "Product",
                            "target_label": prod["product_name"], "field": field, "new": value,
                            "source": CWC_SOURCES[company][field],
                        })
                    elif not values_equal(current, value):
                        _flag(f"CWC '{company}'.{field} on product '{prod['product_name']}': "
                              f"already has non-null {current!r} -- NOT overwritten.")
            elif entity == "Base Model":
                seen_bm = set()
                for prod in PRODUCTS_BY_CO.get(co["airtable_id"], []):
                    bm_id = prod["base_model_id"]
                    if bm_id in seen_bm:
                        continue
                    seen_bm.add(bm_id)
                    ext = EXT_BY_BM_AIRTABLE_ID.get(bm_id)
                    if not ext:
                        continue
                    current = coerce_current(field, ext.get(field, ""))
                    if current is None:
                        _record_value_check(field, value)
                        PLAN["cwc_patches"].append({
                            "company": company, "entity": "Base Model",
                            "target_label": ext.get("model_name", prod["product_name"]),
                            "field": field, "new": value, "source": CWC_SOURCES[company][field],
                        })
                    elif not values_equal(current, value):
                        _flag(f"CWC '{company}'.{field} on base model "
                              f"'{ext.get('model_name', prod['product_name'])}': already has "
                              f"non-null {current!r} -- NOT overwritten.")


# ─────────────────────────────────────────────────────────── variant report
def write_variant_split_report():
    lines = [
        "# Datasheet Import -- Variant-Split-Needed Products",
        "",
        f"Generated by scripts/import_datasheet_project_20260822.py on {TODAY}.",
        "",
        "These conflict entries were triaged VARIANT-SPLIT-NEEDED: the source datasheet "
        "describes multiple sub-variants of a product that the DB currently represents as a "
        "single (blended/wrong) row. The import script does NOT attempt to auto-split these -- "
        "they require a manual Tech Lead decision on how to model the split "
        "(new Product rows? new Base Models? which variant keeps the existing row?).",
        "",
        f"Total entries: {len(PLAN['variant_split_needed'])}",
        "",
    ]
    by_product = defaultdict(list)
    for v in PLAN["variant_split_needed"]:
        by_product[(v["company"], v["db_row"])].append(v)
    for (company, db_row), items in sorted(by_product.items()):
        lines.append(f"## {company} -- {db_row}")
        for it in items:
            lines.append(f"- **{it['field']}**: DB={it['db_value']!r} vs datasheet={it['datasheet_value']!r}")
            lines.append(f"  - {it['note']}")
        lines.append("")
    VARIANT_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


# ───────────────────────────────────────────────────────────── Airtable IO
_LIVE_SCHEMA = None
_TABLE_IDS = None
_FIELD_TYPES = None


def fetch_live_schema():
    global _LIVE_SCHEMA, _TABLE_IDS, _FIELD_TYPES
    url = f"https://api.airtable.com/v0/meta/bases/{BASE_ID}/tables"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req) as resp:
        _LIVE_SCHEMA = json.loads(resp.read())
    tables = {t["name"]: t for t in _LIVE_SCHEMA["tables"]}
    _TABLE_IDS = {k: tables[v]["id"] for k, v in TBL_NAMES.items()}
    _FIELD_TYPES = {k: {f["name"]: f["type"] for f in tables[v]["fields"]} for k, v in TBL_NAMES.items()}


def to_airtable_value(table_key, field_name, value):
    if value is None:
        return None
    if not _FIELD_TYPES:
        return value
    at_type = _FIELD_TYPES.get(table_key, {}).get(field_name)
    if at_type == "checkbox":
        return bool(value)
    if at_type == "singleSelect" and isinstance(value, bool):
        return "True" if value else "False"
    if at_type == "singleSelect" and isinstance(value, list):
        return "|".join(str(v) for v in value)
    if at_type == "multipleSelects" and isinstance(value, list):
        return [str(v) for v in value]
    if at_type == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return value


def _airtable_request(method, url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    })
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req) as resp:
                out = json.loads(resp.read())
            time.sleep(RATE_LIMIT_SLEEP)
            return out
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if e.code == 429:
                time.sleep(2)
                continue
            raise RuntimeError(f"{method} {url} -> {e.code} {body}") from e
    raise RuntimeError(f"retries exhausted: {method} {url}")


_UNKNOWN_FIELD_RE = re.compile(r'Unknown field name: "([^"]+)"')


def _filter_known_fields(table_key, encoded, context):
    """Drop any outgoing field not present in the real live Airtable schema (fetched via
    fetch_live_schema()). Prevents a stale/AP0-only field (e.g. a fields.json entry that was
    never actually added as an Airtable column) from crashing the whole run with a 422
    UNKNOWN_FIELD_NAME. Every drop is printed and written to the audit trail -- never silent."""
    if not _FIELD_TYPES or table_key not in _FIELD_TYPES:
        return encoded
    known = _FIELD_TYPES[table_key]
    kept, dropped = {}, {}
    for k, v in encoded.items():
        (kept if k in known else dropped)[k] = v
    for k, v in dropped.items():
        msg = (f"DROPPED unknown field '{k}'={v!r} for table '{table_key}' ({context}) -- "
               f"not present in live Airtable schema (fields.json/AP0 drift)")
        print(f"    ! {msg}")
        audit({"op": "dropped_unknown_field", "table": table_key, "field": k,
               "value": v, "context": context})
    return kept


def _write_with_retry(method, url, payload, table_key, context):
    """Second line of defense on top of _filter_known_fields(): if Airtable still rejects the
    write with UNKNOWN_FIELD_NAME (e.g. schema drifted after fetch_live_schema() ran, or a field
    was missed), strip exactly that one field and retry once instead of crashing the run."""
    try:
        return _airtable_request(method, url, payload)
    except RuntimeError as e:
        msg = str(e)
        if "UNKNOWN_FIELD_NAME" not in msg:
            raise
        m = _UNKNOWN_FIELD_RE.search(msg)
        rec = payload["records"][0]
        if not m or m.group(1) not in rec["fields"]:
            raise
        bad_field = m.group(1)
        dropped_val = rec["fields"].pop(bad_field)
        warn = (f"UNKNOWN_FIELD_NAME on live write: '{bad_field}'={dropped_val!r} for table "
                f"'{table_key}' ({context}) -- stripped and retried once")
        print(f"    ! {warn}")
        audit({"op": "dropped_unknown_field_retry", "table": table_key, "field": bad_field,
               "value": dropped_val, "context": context})
        return _airtable_request(method, url, payload)


def create_record(table_key, fields, context=""):
    encoded = {k: to_airtable_value(table_key, k, v) for k, v in fields.items()}
    encoded = {k: v for k, v in encoded.items() if v is not None}
    encoded = _filter_known_fields(table_key, encoded, context)
    if DRY:
        print(f"    DRY create {table_key}: {json.dumps(encoded, ensure_ascii=False)[:300]}")
        return {"id": f"rec_DRY_{table_key}_{uuid.uuid4().hex[:8]}"}
    resp = _write_with_retry("POST", f"https://api.airtable.com/v0/{BASE_ID}/{_TABLE_IDS[table_key]}",
                              {"records": [{"fields": encoded}], "typecast": True}, table_key, context)
    return resp["records"][0]


def patch_record(table_key, rec_id, fields, context=""):
    encoded = {k: to_airtable_value(table_key, k, v) for k, v in fields.items()}
    encoded = _filter_known_fields(table_key, encoded, context)
    if DRY:
        print(f"    DRY patch {table_key} {rec_id}: {json.dumps(encoded, ensure_ascii=False)[:300]}")
        return {"id": rec_id}
    resp = _write_with_retry("PATCH", f"https://api.airtable.com/v0/{BASE_ID}/{_TABLE_IDS[table_key]}",
                              {"records": [{"id": rec_id, "fields": encoded}], "typecast": True}, table_key, context)
    return resp["records"][0]


def audit(entry):
    entry = {"ts": TODAY, **entry}
    if not DRY:
        with AUDIT_PATH.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _escape_formula_str(s):
    return s.replace("\\", "\\\\").replace("'", "\\'")


def find_existing_company(name):
    """Live Airtable lookup by exact company_name. Used to make new-company creation resumable
    after a partial/crashed run -- never trust the pre-run CSV snapshot for this, it predates
    whatever this run itself may have already created."""
    formula = f"{{company_name}} = '{_escape_formula_str(name)}'"
    url = (f"https://api.airtable.com/v0/{BASE_ID}/{_TABLE_IDS['companies']}"
           f"?filterByFormula={urllib.parse.quote(formula)}")
    resp = _airtable_request("GET", url)
    recs = resp.get("records", [])
    return recs[0] if recs else None


def find_existing_product(product_name, co_rec_id):
    """Live Airtable lookup by exact product_name + linked company record id. Used to make
    new-product creation resumable -- skips products already created by a prior (crashed) run of
    this same script instead of re-creating duplicates."""
    formula = f"{{product_name}} = '{_escape_formula_str(product_name)}'"
    url = (f"https://api.airtable.com/v0/{BASE_ID}/{_TABLE_IDS['products']}"
           f"?filterByFormula={urllib.parse.quote(formula)}")
    resp = _airtable_request("GET", url)
    for rec in resp.get("records", []):
        if co_rec_id in (rec.get("fields", {}).get("company_id") or []):
            return rec
    return None


def get_base_model_record(bm_rec_id):
    url = f"https://api.airtable.com/v0/{BASE_ID}/{_TABLE_IDS['base_models']}/{bm_rec_id}"
    return _airtable_request("GET", url)


# ──────────────────────────────────────────────────────────────── execution
def execute_new_inserts():
    print("\n== NEW INSERTS ==")
    company_rec_cache = {}
    n_skipped_done, n_resumed_orphan, n_created = 0, 0, 0
    for item in PLAN["new_inserts"]:
        company = item["company"]
        print(f"  [{item['product_name']}] company={company}")
        if company not in company_rec_cache:
            co = CO_BY_NAME.get(company)
            if co:
                company_rec_cache[company] = co["airtable_id"]
            else:
                existing_co = None
                try:
                    existing_co = find_existing_company(company)
                except Exception as e:
                    print(f"    ! company existence lookup failed ({e}) -- proceeding to create "
                          f"(may duplicate if it already exists, needs manual check)")
                    audit({"op": "company_lookup_failed", "name": company, "error": str(e)})
                if existing_co:
                    company_rec_cache[company] = existing_co["id"]
                    print(f"    -> company already exists (resumed run): {existing_co['id']}")
                    audit({"op": "skip_existing_company", "name": company,
                           "airtable_id": existing_co["id"]})
                else:
                    folded = next((c["fields"] for c in PLAN["new_companies"] if c["name"] == company), {})
                    co_fields = {"company_name": company, "company_id": str(uuid.uuid4()),
                                 "last_updated": TODAY, **folded}
                    co_rec = create_record("companies", co_fields, context=f"company:{company}")
                    company_rec_cache[company] = co_rec["id"]
                    audit({"op": "create_company", "name": company, "airtable_id": co_rec["id"]})
                    print(f"    -> new company {co_rec['id']}")
        co_rec_id = company_rec_cache[company]

        # -- resumability: has a prior (possibly crashed) run already created this product? --
        existing_prod = None
        try:
            existing_prod = find_existing_product(item["product_name"], co_rec_id)
        except Exception as e:
            print(f"    ! product existence lookup failed ({e}) -- proceeding to create "
                  f"(may duplicate if it already exists, needs manual check)")
            audit({"op": "product_lookup_failed", "name": item["product_name"], "error": str(e)})

        if existing_prod:
            should_have_own_ext = bool(item["ext_fields"]) or not item["shared_base_model"]
            if not should_have_own_ext:
                print(f"    -> product already exists (resumed run, shared base model, no own "
                      f"extension expected) -- SKIPPING")
                audit({"op": "skip_existing_product", "name": item["product_name"],
                       "company": company, "airtable_id": existing_prod["id"]})
                n_skipped_done += 1
                continue

            bm_ids = existing_prod.get("fields", {}).get("base_model_id") or []
            bm_rec_id = bm_ids[0] if bm_ids else None
            has_ext = False
            if bm_rec_id:
                bm_rec = get_base_model_record(bm_rec_id)
                has_ext = bool(bm_rec.get("fields", {}).get("Base Model Extensions"))

            if has_ext:
                print(f"    -> product + extension already exist (resumed run) -- SKIPPING")
                audit({"op": "skip_existing_product", "name": item["product_name"],
                       "company": company, "airtable_id": existing_prod["id"]})
                n_skipped_done += 1
                continue

            if not bm_rec_id:
                print(f"    ! product exists but has no linked base_model_id -- cannot resume "
                      f"extension creation, SKIPPING, needs manual review")
                audit({"op": "skip_existing_product_no_base_model", "name": item["product_name"],
                       "company": company, "airtable_id": existing_prod["id"]})
                n_skipped_done += 1
                continue

            print(f"    -> product already exists but has NO linked extension (orphan from a "
                  f"prior crashed run) -- creating the missing extension only")
            ext_uuid = str(uuid.uuid4())
            ext_fields = {
                "model_name": item["base_model_name"] or item["product_name"],
                "extension_id": ext_uuid,
                "product_type": item["product_type"],
                "base_model_id": [bm_rec_id],
                "source_notes": item["notes"],
                **item["ext_fields"],
            }
            ext_rec = create_record("extensions", ext_fields,
                                     context=f"extension(orphan-resume):{item['product_name']}")
            audit({"op": "create_extension_resume_orphan", "name": item["base_model_name"],
                   "extension_id": ext_uuid, "airtable_id": ext_rec["id"],
                   "base_model_airtable_id": bm_rec_id, "product_airtable_id": existing_prod["id"]})
            print(f"    -> extension {ext_rec['id']} (orphan fixed)")
            n_resumed_orphan += 1
            continue

        if item["shared_base_model"]:
            bm_rec_id = item["shared_base_model"]["base_model_airtable_id"]
        else:
            bm_uuid = str(uuid.uuid4())
            bm_fields = {
                "base_model_name": item["base_model_name"],
                "base_model_id": bm_uuid,
                "product_type": item["product_type"],
                "oem_link_public": True,
                "last_updated": TODAY,
                "oem_company_id": [co_rec_id],
            }
            bm_rec = create_record("base_models", bm_fields, context=f"base_model:{item['base_model_name']}")
            bm_rec_id = bm_rec["id"]
            audit({"op": "create_base_model", "name": item["base_model_name"],
                   "base_model_id": bm_uuid, "airtable_id": bm_rec_id})
            print(f"    -> base model {bm_rec_id}")

        prod_uuid = str(uuid.uuid4())
        prod_fields = {
            "product_name": item["product_name"],
            "product_id": prod_uuid,
            "product_type": item["product_type"],
            "is_oem_product": True,
            "active": True,
            "source_notes": item["notes"],
            "company_id": [co_rec_id],
            "base_model_id": [bm_rec_id],
            **item["prod_fields"],
        }
        prod_rec = create_record("products", prod_fields, context=f"product:{item['product_name']}")
        audit({"op": "create_product", "name": item["product_name"], "product_id": prod_uuid,
               "airtable_id": prod_rec["id"]})
        print(f"    -> product {prod_rec['id']}")

        if item["ext_fields"] or not item["shared_base_model"]:
            ext_uuid = str(uuid.uuid4())
            ext_fields = {
                "model_name": item["base_model_name"] or item["product_name"],
                "extension_id": ext_uuid,
                "product_type": item["product_type"],
                "base_model_id": [bm_rec_id],
                "source_notes": item["notes"],
                **item["ext_fields"],
            }
            ext_rec = create_record("extensions", ext_fields, context=f"extension:{item['product_name']}")
            audit({"op": "create_extension", "name": item["base_model_name"], "extension_id": ext_uuid,
                   "airtable_id": ext_rec["id"]})
            print(f"    -> extension {ext_rec['id']}")
        else:
            print("    (shared base model, 0 new fields for this batch -- no new extension written)")
        n_created += 1

    print(f"\n  -- NEW INSERTS summary: {n_created} created, {n_resumed_orphan} orphan(s) resumed "
          f"(extension-only), {n_skipped_done} already fully done (skipped) --")


def execute_fills(bucket_name, items, table_key_fn, field_key="field", value_key="new"):
    print(f"\n== {bucket_name} ({len(items)}) ==")
    for it in items:
        table_key = table_key_fn(it)
        rec_id = it.get("_rec_id")
        if rec_id is None:
            continue
        old = it.get("old")
        row_label = it.get('db_row', it.get('target_label', ''))
        print(f"  [{it['company']} / {row_label}] "
              f"{it[field_key]}: {old!r} -> {it[value_key]!r}")
        patch_record(table_key, rec_id, {it[field_key]: it[value_key]},
                     context=f"{bucket_name}:{it['company']}/{row_label}")
        audit({"op": "patch", "bucket": bucket_name, **{k: v for k, v in it.items() if k != "_rec_id"}})


def _attach_rec_ids():
    """Resolve Airtable record ids for every planned patch, for --run execution."""
    for it in PLAN["enrich_fills"]:
        if it["table_hint"] == "extensions":
            row = resolve_extension(it["company"], it["db_row"])
        elif it["table_hint"] == "products":
            row = resolve_product(it["company"], it["db_row"])
        elif it["table_hint"] == "companies":
            row = CO_BY_NAME.get(it["company"])
        else:
            row = None
        it["_rec_id"] = row["airtable_id"] if row else None
    for it in PLAN["conflict_overwrites"] + PLAN["multiselect_extend_patches"]:
        row = resolve_extension(it["company"], it["db_row"])
        it["_rec_id"] = row["airtable_id"] if row else None
    for it in PLAN["deactivate"]:
        row = resolve_product(it["company"], it["db_row"])
        it["_rec_id"] = row["airtable_id"] if row else None
    for it in PLAN["cwc_patches"]:
        if it["entity"] == "Company":
            row = CO_BY_NAME.get(it["company"])
        elif it["entity"] == "Product":
            row = resolve_product(it["company"], it["target_label"])
        else:
            row = None
            for prod in PRODUCTS_BY_CO.get(CO_BY_NAME.get(it["company"], {}).get("airtable_id"), []):
                ext = EXT_BY_BM_AIRTABLE_ID.get(prod["base_model_id"])
                if ext and ext.get("model_name", prod["product_name"]) == it["target_label"]:
                    row = ext
                    break
        it["_rec_id"] = (row.get("airtable_id") if row else None)


# ───────────────────────────────────────────────────────────────── summary
def print_summary():
    p = PLAN
    n_new_companies = len(p["new_companies"])
    n_new_inserts = len(p["new_inserts"])
    n_enrich = len(p["enrich_fills"])
    n_conflict_ow = len(p["conflict_overwrites"])
    n_ms_extend = len(p["multiselect_extend_patches"])
    n_cwc = len(p["cwc_patches"])
    n_deactivate = len(p["deactivate"])
    n_variant = len(p["variant_split_needed"])
    n_unresolved = len(p["skipped_unresolved"])
    n_dbcleanup = len(p["skipped_db_cleanup"])
    n_ambiguous = len(p["skipped_ambiguous"])
    n_confirmed_noop = len(p["confirmed_noop_mismatches"])
    n_cwc_folded = len(p["new_company_cwc_folded"])

    print("\n" + "=" * 78)
    print("PRE-RUN SUMMARY")
    print("=" * 78)
    print(f"New companies to create:            {n_new_companies}")
    print(f"New Base Model/Product/Ext inserts:  {n_new_inserts}")
    print(f"Enrich (NULL-fill) patches:          {n_enrich}")
    print(f"Multi-select extend (union) patches: {n_ms_extend}")
    print(f"Conflict OVERWRITE patches:          {n_conflict_ow}")
    print(f"Company-wide context fan-out patches:{n_cwc}")
    print(f"New-company CWC fold-in fields:      {n_cwc_folded}")
    print(f"Product deactivations (variant-split supersession): {n_deactivate}")
    print(f"Variant-split-needed entries:        {n_variant}  (see {VARIANT_REPORT_PATH.relative_to(ROOT)})")
    print(f"Skipped UNRESOLVED conflicts:         {n_unresolved}")
    print(f"Skipped DB-CLEANUP conflicts:         {n_dbcleanup}")
    print(f"Skipped AMBIGUOUS conflicts:           {n_ambiguous}")
    print(f"Confirmed-correct no-op mismatches:    {n_confirmed_noop}")
    print(f"AP0 allowed_values warnings:          {len(p['allowed_value_warnings'])}")
    print(f"Flags for Tech Lead review:            {len(p['flags'])}")

    if p["new_companies"]:
        print("\n--- New companies ---")
        for c in p["new_companies"]:
            print(f"  {c['name']}" + (f"  ({len(c['fields'])} CWC fields folded in: "
                                       f"{sorted(c['fields'])})" if c["fields"] else ""))

    print("\n--- New product inserts (first 20 of {}) ---".format(n_new_inserts))
    for it in p["new_inserts"][:20]:
        shared = f" [shares base model with {it['shared_base_model']['via']}]" if it["shared_base_model"] else ""
        print(f"  {it['company']} :: {it['product_name']} ({it['product_type']}){shared} "
              f"-- {len(it['ext_fields'])} ext fields, {len(it['prod_fields'])} product fields")
    if n_new_inserts > 20:
        print(f"  ... and {n_new_inserts - 20} more")

    print(f"\n--- CONFLICT OVERWRITES -- FULL LIST ({n_conflict_ow}) ---")
    for it in p["conflict_overwrites"]:
        print(f"  {it['company']} / {it['db_row']} :: {it['field']} [{it['level']}]: "
              f"{it['old']!r} -> {it['new']!r}   (triage: {it['raw_triage']})")

    print(f"\n--- PRODUCT DEACTIVATIONS -- FULL LIST ({n_deactivate}) ---")
    for it in p["deactivate"]:
        print(f"  {it['company']} / {it['db_row']} (product_id={it['product_id']}) :: "
              f"{it['field']}: {it['old']!r} -> {it['new']!r}   ({it['reason']})")

    print(f"\n--- Multi-select extend patches (first 20 of {n_ms_extend}) ---")
    for it in p["multiselect_extend_patches"][:20]:
        print(f"  {it['company']} / {it['db_row']} :: {it['field']}: {it['old']!r} -> {it['new']!r}")

    print(f"\n--- Enrich (NULL-fill) patches (first 20 of {n_enrich}) ---")
    for it in p["enrich_fills"][:20]:
        print(f"  {it['company']} / {it['db_row']} :: {it['field']}=({it['entity']}) -> {it['new']!r}")

    print(f"\n--- Company-wide context fan-out (first 20 of {n_cwc}) ---")
    for it in p["cwc_patches"][:20]:
        print(f"  {it['company']} / {it['target_label']} ({it['entity']}) :: {it['field']} -> "
              f"{it['new']!r}  [{it['source']}]")

    if p["new_company_cwc_folded"]:
        print(f"\n--- New-company CWC fold-in (full list, {n_cwc_folded}) ---")
        for it in p["new_company_cwc_folded"]:
            print(f"  {it['company']} / {it['target']} :: {it['field']} -> {it['new']!r}  "
                  f"[{it['source']}]")

    if p["confirmed_noop_mismatches"]:
        print(f"\n--- Confirmed-correct no-op mismatches (full list, {n_confirmed_noop}) ---")
        for it in p["confirmed_noop_mismatches"]:
            print(f"  {it['company']} / {it['db_row']} :: {it['field']}: DB={it['db_value']!r} "
                  f"(kept) vs dataset={it['dataset_value']!r} (rejected) -- {it['note']}")

    if p["allowed_value_warnings"]:
        print(f"\n--- AP0 allowed_values WARNINGS ({len(p['allowed_value_warnings'])}) ---")
        for w in p["allowed_value_warnings"]:
            print(f"  ! {w}")

    if CWC_INTERNAL_CONFLICTS:
        print(f"\n--- CWC internal source conflicts ({len(CWC_INTERNAL_CONFLICTS)}) ---")
        for c in CWC_INTERNAL_CONFLICTS:
            print(f"  ! {c}")

    print(f"\n--- Flags for Tech Lead ({len(p['flags'])}) ---")
    for f in p["flags"]:
        print(f"  ! {f}")

    print("\nExplicitly OUT OF SCOPE for this script (logged, not acted on):")
    print(f"  - {STATUS['summary'].get('db_cleanup_wrong_scope_values', '?')} wrong-scope DB cells")
    print("  - non-conforming allowed_values tokens")
    print("  - AGILOX min_aisle_width (both candidates rejected by Tech Lead ruling) -- see NOOP log")
    print("  - K10P One-Way (sonnet-only, thinner verification) -- imported as a normal enrich case")


# ──────────────────────────────────────────────────────────────────── main
def main():
    global DRY
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="actually write to Airtable")
    ap.add_argument("--dry-run", action="store_true", help="preview only (default)")
    args = ap.parse_args()
    DRY = not args.run
    print(f"MODE: {'LIVE' if args.run else 'DRY RUN'}")

    plan_new_products()
    apply_new_company_cwc()
    plan_matched_products()
    plan_variant_splits()
    plan_cwc_fanout()
    write_variant_split_report()

    if not DRY:
        if not TOKEN or not BASE_ID:
            sys.exit("ERROR: AIRTABLE_TOKEN / AIRTABLE_BASE_ID not set in .env")
        fetch_live_schema()
        _attach_rec_ids()

    print_summary()

    if not DRY:
        print("\n" + "=" * 78)
        print("EXECUTING LIVE WRITES")
        print("=" * 78)
        execute_new_inserts()
        execute_fills("ENRICH FILLS", PLAN["enrich_fills"],
                      lambda it: it["table_hint"])
        execute_fills("MULTISELECT EXTEND PATCHES", PLAN["multiselect_extend_patches"],
                      lambda it: "extensions")
        execute_fills("CONFLICT OVERWRITES", PLAN["conflict_overwrites"],
                      lambda it: "extensions")
        execute_fills("PRODUCT DEACTIVATIONS", PLAN["deactivate"],
                      lambda it: "products")
        execute_fills("COMPANY-WIDE CONTEXT FAN-OUT", PLAN["cwc_patches"],
                      lambda it: {"Company": "companies", "Product": "products",
                                  "Base Model": "extensions"}[it["entity"]])
        print("\nDONE.")
    else:
        print("\nDRY RUN complete -- no Airtable calls were made. Re-run with --run after "
              "Tech Lead sign-off (review the CONFLICT OVERWRITES list above especially).")


if __name__ == "__main__":
    main()
