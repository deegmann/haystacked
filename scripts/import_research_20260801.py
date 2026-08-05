#!/usr/bin/env python3
"""Import 8-supplier research batch (docs/research_findings_20260801_*.json) into Airtable.

INSERT-ONLY by construction: creates new Companies / Base Models / Products /
Base Model Extensions records. Never issues PATCH or DELETE against any
existing record — existing data (including manually-edited Balyo records)
cannot be touched by this script.

Usage:
    python3 scripts/import_research_20260801.py --company gideon_brothers   # single company test
    python3 scripts/import_research_20260801.py --all                       # full batch
"""
import argparse
import json
import time
import urllib.request
import urllib.error
import uuid
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
DOCS = ROOT / "docs"
SCHEMA_PATH = Path(
    "/private/tmp/claude-501/-Users-christiandeeg-haystacked-platform-Local-test/"
    "5bd7246f-8369-476e-a678-9236e47fe907/scratchpad/live_schema.json"
)
AUDIT_PATH = ROOT / "docs" / "import_20260801_audit.jsonl"

RATE_LIMIT_SLEEP = 0.25  # ~4 req/s, under Airtable's 5 req/s cap

SLUGS = [
    "gideon_brothers",
    "youibot",
    "magazino",
    "vecna",
    "seegrid",
    "addverb",
    "rocla",
    "hai_robotics",
]

# Manually verified company-level facts (from researcher_notes in each JSON file).
# Fields left out entirely where the research did not state a confirmed current value
# (Blank != Zero -- never guess).
COMPANY_INFO = {
    "gideon_brothers": {
        "company_name": "Gideon Brothers",
        "country": "HR",
        "hq_city": "Osijek",
        "hq_address": "Samacka 7, 31000 Osijek, Croatia",
        "founding_year": 2017,
        "website": "https://www.gideon.ai",
    },
    "youibot": {
        "company_name": "Youibot",
        "country": "CN",
        "hq_city": "Shenzhen",
        "founding_year": 2017,
        "website": "https://en.youibot.com",
        "employee_count_range": "250–1000",
    },
    "magazino": {
        "company_name": "Magazino",
        "country": "DE",
        "hq_city": "Munich",
        "hq_address": "Landsberger Str. 234, 80687 Munich, Germany",
        "founding_year": 2014,
        "website": "https://www.magazino.eu",
        "employee_count_range": "50–250",
    },
    "vecna": {
        "company_name": "Vecna Robotics",
        "country": "US",
        "hq_city": "Waltham",
        "hq_address": "425 Waverley Oaks Road, Waltham, MA 02452, USA",
        "founding_year": 2018,
        "website": "https://vecnarobotics.com",
    },
    "seegrid": {
        "company_name": "Seegrid",
        "country": "US",
        "hq_city": "Pittsburgh",
        "hq_address": "216 RIDC Park West Drive, Pittsburgh, PA 15275, USA",
        "founding_year": 2003,
        "website": "https://seegrid.com",
    },
    "addverb": {
        "company_name": "Addverb",
        "country": "IN",
        "hq_city": "Noida",
        "hq_address": "Addverb Bot-Valley, Plot No. 5, Sector-156, Phase-II, Noida, Uttar Pradesh 201310, India",
        "founding_year": 2016,
        "website": "https://addverb.com",
        "employee_count_range": ">1000",
    },
    "rocla": {
        "company_name": "Rocla",
        "country": "FI",
        "hq_city": "Järvenpää",
        "website": "https://rocla-agv.com",
        "employee_count_range": "250–1000",
    },
    "hai_robotics": {
        "company_name": "HAI Robotics",
        "country": "CN",
        "hq_city": "Shenzhen",
        "founding_year": 2016,
        "website": "https://www.hairobotics.com",
    },
}


def load_env():
    env = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()
TOKEN = ENV["AIRTABLE_TOKEN"]
BASE_ID = ENV["AIRTABLE_BASE_ID"]

LIVE_SCHEMA = json.loads(SCHEMA_PATH.read_text())
TABLES = {t["name"]: t for t in LIVE_SCHEMA["tables"]}


def field_types(table_name):
    return {f["name"]: f["type"] for f in TABLES[table_name]["fields"]}


TABLE_IDS = {
    "Companies": TABLES["Companies"]["id"],
    "Base Models": TABLES["Base Models"]["id"],
    "Products": TABLES["Products"]["id"],
    "Base Model Extensions": TABLES["Base Model Extensions"]["id"],
}
FIELD_TYPES = {name: field_types(name) for name in TABLE_IDS}


def airtable_request(method, table_id, payload=None):
    url = f"https://api.airtable.com/v0/{BASE_ID}/{table_id}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Airtable {method} {table_id} failed: {e.code} {body}") from e


def create_record(table_name, fields):
    payload = {"records": [{"fields": fields}], "typecast": True}
    resp = airtable_request("POST", TABLE_IDS[table_name], payload)
    time.sleep(RATE_LIMIT_SLEEP)
    return resp["records"][0]


def company_exists(company_name):
    """Safety check: never create a duplicate company record."""
    import urllib.parse
    formula = urllib.parse.quote(f"{{company_name}}='{company_name}'")
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_IDS['Companies']}?filterByFormula={formula}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    time.sleep(RATE_LIMIT_SLEEP)
    return data.get("records", [])


def convert_value(airtable_type, value):
    if value is None:
        return None
    if airtable_type == "checkbox":
        return bool(value)
    if airtable_type == "multipleSelects":
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return [str(value)]
    if airtable_type == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if airtable_type == "singleSelect" and isinstance(value, bool):
        # Some AP0 Boolean fields (e.g. vna_capable) are stored as True/False singleSelect, not checkbox
        return "True" if value else "False"
    if airtable_type == "singleSelect" and isinstance(value, list):
        # A few AP0 Multi-Select fields (e.g. storage_system_type) are stored as singleSelect
        # in Airtable, with compound "A|B" choices representing multi-value cases.
        return "|".join(str(v) for v in value)
    # singleSelect, singleLineText, multilineText, url, email, etc.
    return value


def build_extension_fields(product_fields, notes_extra=""):
    bme_types = FIELD_TYPES["Base Model Extensions"]
    out = {}
    skipped = []
    for key, value in product_fields.items():
        if key not in bme_types:
            skipped.append(key)
            continue
        conv = convert_value(bme_types[key], value)
        if conv is not None:
            out[key] = conv
    if notes_extra:
        out["source_notes"] = notes_extra
    return out, skipped


def audit(entry):
    with AUDIT_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def import_company(slug, dry_run=False, skip_products=0, resume_company_rec_id=None):
    info = COMPANY_INFO[slug]
    data = json.loads((DOCS / f"research_findings_20260801_{slug}.json").read_text())
    products = data.get("products", [])
    if not products:
        print(f"[{slug}] 0 products -- skipping per feedback_only_vehicles.md convention")
        return

    if resume_company_rec_id:
        company_rec_id = resume_company_rec_id
        print(f"[{slug}] Resuming with existing company {company_rec_id}, skipping first {skip_products} product(s)")
    else:
        existing = company_exists(info["company_name"])
        if existing:
            print(f"[{slug}] Company '{info['company_name']}' already exists ({existing[0]['id']}) -- ABORTING to avoid duplicate")
            return

        company_fields = {k: v for k, v in info.items()}
        company_fields["company_id"] = str(uuid.uuid4())
        company_fields["last_updated"] = date.today().isoformat()

        print(f"[{slug}] Creating Company: {info['company_name']}")
        if dry_run:
            print("  DRY RUN company_fields:", json.dumps(company_fields, ensure_ascii=False))
            company_rec_id = "rec_DRYRUN_company"
        else:
            co_rec = create_record("Companies", company_fields)
            company_rec_id = co_rec["id"]
            audit({"type": "company", "slug": slug, "airtable_id": company_rec_id, "company_id": company_fields["company_id"], "name": info["company_name"]})
            print(f"  -> {company_rec_id}")

    for p in products[skip_products:]:
        product_name = p["product_name"]
        product_type = p["product_type"]
        confidence = p.get("confidence", "")
        source_url = p.get("source_url", "")
        notes = p.get("notes", "")
        source_notes = f"[{confidence} confidence] {notes} Source: {source_url}".strip()

        base_model_id_uuid = str(uuid.uuid4())
        bm_fields = {
            "base_model_name": product_name,
            "base_model_id": base_model_id_uuid,
            "product_type": product_type,
            "oem_link_public": True,
            "last_updated": date.today().isoformat(),
            "oem_company_id": [company_rec_id],
        }
        print(f"  [{product_name}] Creating Base Model")
        if dry_run:
            print("    DRY RUN bm_fields:", json.dumps(bm_fields, ensure_ascii=False)[:300])
            bm_rec_id = "rec_DRYRUN_bm"
        else:
            bm_rec = create_record("Base Models", bm_fields)
            bm_rec_id = bm_rec["id"]
            audit({"type": "base_model", "slug": slug, "airtable_id": bm_rec_id, "base_model_id": base_model_id_uuid, "name": product_name})
            print(f"    -> {bm_rec_id}")

        product_id_uuid = str(uuid.uuid4())
        prod_fields = {
            "product_name": product_name,
            "product_id": product_id_uuid,
            "product_type": product_type,
            "is_oem_product": True,
            "active": True,
            "source_notes": source_notes[:9000],
            "company_id": [company_rec_id],
            "base_model_id": [bm_rec_id],
        }
        print(f"  [{product_name}] Creating Product")
        if dry_run:
            print("    DRY RUN prod_fields:", json.dumps(prod_fields, ensure_ascii=False)[:300])
            prod_rec_id = "rec_DRYRUN_product"
        else:
            prod_rec = create_record("Products", prod_fields)
            prod_rec_id = prod_rec["id"]
            audit({"type": "product", "slug": slug, "airtable_id": prod_rec_id, "product_id": product_id_uuid, "name": product_name})
            print(f"    -> {prod_rec_id}")

        ext_fields, skipped_keys = build_extension_fields(p.get("fields", {}), source_notes[:9000])
        ext_fields["model_name"] = product_name
        ext_fields["extension_id"] = str(uuid.uuid4())
        ext_fields["product_type"] = product_type
        ext_fields["base_model_id"] = [bm_rec_id]
        if skipped_keys:
            print(f"    (skipped unknown fields: {skipped_keys})")
        print(f"  [{product_name}] Creating Base Model Extension ({len(ext_fields)} fields)")
        if dry_run:
            print("    DRY RUN ext_fields:", json.dumps(ext_fields, ensure_ascii=False)[:400])
        else:
            ext_rec = create_record("Base Model Extensions", ext_fields)
            audit({"type": "extension", "slug": slug, "airtable_id": ext_rec["id"], "extension_id": ext_fields["extension_id"], "name": product_name})
            print(f"    -> {ext_rec['id']}")

    print(f"[{slug}] DONE ({len(products)} products)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", help="single company slug to import")
    ap.add_argument("--all", action="store_true", help="import all 8 companies")
    ap.add_argument("--dry-run", action="store_true", help="print what would be created, no writes")
    ap.add_argument("--skip-products", type=int, default=0, help="skip first N products (resume)")
    ap.add_argument("--company-rec-id", help="existing company Airtable record id (resume)")
    args = ap.parse_args()

    if args.company:
        import_company(args.company, dry_run=args.dry_run, skip_products=args.skip_products, resume_company_rec_id=args.company_rec_id)
    elif args.all:
        for slug in SLUGS:
            import_company(slug, dry_run=args.dry_run)
    else:
        print("Specify --company <slug> or --all (add --dry-run to preview)")


if __name__ == "__main__":
    main()
