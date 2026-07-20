#!/usr/bin/env python3
"""
One-shot migration: add IK (Industriekälteanlagen) suppliers to Airtable.

Steps:
  1. Add 'Process Cooling', 'Cold Store', 'Deep Freeze' to agv_type singleSelect
     in Base Models, Products, and Base Model Extensions tables
  2. Add 11 IK-specific fields to Base Model Extensions
  3. Create 3 company records (GEA, Güntner, Bitzer)
  4. Create 3 base model records
  5. Create 3 product records (linked to companies)
  6. Create 3 extension records (linked to base models) with IK field values

Run once. Idempotent: checks for existing names before creating.
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TOKEN   = os.environ.get("AIRTABLE_TOKEN", "")
BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "")
if not TOKEN or not BASE_ID:
    sys.exit("ERROR: AIRTABLE_TOKEN and AIRTABLE_BASE_ID must be set in .env")

HEADERS      = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
META_URL     = f"https://api.airtable.com/v0/meta/bases/{BASE_ID}/tables"
DATA_URL     = f"https://api.airtable.com/v0/{BASE_ID}"

TABLE_IDS = {
    "companies":   "tblxZNhyTlfd1c5Po",
    "base_models": "tblsaCzUQUrC4m7lj",
    "products":    "tblgizCLjKYcCAbwp",
    "extensions":  "tblinb1Zn0Ihc977M",
}

NEW_AGV_TYPES = ["Process Cooling", "Cold Store", "Deep Freeze"]

IK_FIELD_SPECS = [
    {"name": "cooling_capacity_kw",     "type": "number",         "options": {"precision": 8}},
    {"name": "temperature_min_celsius", "type": "number",         "options": {"precision": 8}},
    {"name": "refrigerant_types",       "type": "multipleSelects",
     "options": {"choices": [{"name": n} for n in ["R744", "R290", "R717", "R134a", "R32"]]}},
    {"name": "certifications_ik",       "type": "multipleSelects",
     "options": {"choices": [{"name": n} for n in ["PED", "ATEX", "EN 378", "F-Gas"]]}},
    {"name": "cop_efficiency",          "type": "number",         "options": {"precision": 8}},
    {"name": "cooling_medium",          "type": "singleSelect",
     "options": {"choices": [{"name": n} for n in ["glycol", "water", "direct"]]}},
    {"name": "temperature_stability_k", "type": "number",         "options": {"precision": 8}},
    {"name": "room_volume_m3_max",      "type": "number",         "options": {"precision": 8}},
    {"name": "humidity_control_capable","type": "checkbox",       "options": {"icon": "check", "color": "greenBright"}},
    {"name": "blast_freeze_capacity_kg_h","type": "number",       "options": {"precision": 8}},
    {"name": "pulldown_time_h",         "type": "number",         "options": {"precision": 8}},
]

def _get(url, **kwargs):
    r = requests.get(url, headers=HEADERS, **kwargs)
    r.raise_for_status()
    return r.json()

def _post(url, data):
    r = requests.post(url, headers=HEADERS, json=data)
    if not r.ok:
        print(f"  POST error {r.status_code}: {r.text[:400]}")
    r.raise_for_status()
    time.sleep(0.3)
    return r.json()

def _patch(url, data):
    r = requests.patch(url, headers=HEADERS, json=data)
    if not r.ok:
        print(f"  PATCH error {r.status_code}: {r.text[:400]}")
    r.raise_for_status()
    time.sleep(0.3)
    return r.json()


def get_table_schema():
    data = _get(META_URL)
    return {t["name"]: t for t in data["tables"]}


def step1_extend_agv_type(schema):
    """New agv_type choices are added automatically via typecast=True during record creation.
    This step verifies the current state and reports — no API call needed."""
    print("\nStep 1: agv_type choices — auto-extended via typecast=True during record creation.")
    target_tables = ["Base Models", "Products", "Base Model Extensions"]
    for tname in target_tables:
        t = schema[tname]
        agv_field = next(f for f in t["fields"] if f["name"] == "agv_type")
        existing  = {c["name"] for c in agv_field["options"]["choices"]}
        missing   = [n for n in NEW_AGV_TYPES if n not in existing]
        if not missing:
            print(f"  {tname}: all IK choices already present")
        else:
            print(f"  {tname}: will auto-add {missing} via typecast when records are created")


def step2_add_ik_fields(schema):
    """Add 11 IK-specific fields to Base Model Extensions if missing."""
    print("\nStep 2: Adding IK fields to Base Model Extensions...")
    t    = schema["Base Model Extensions"]
    tid  = t["id"]
    existing = {f["name"] for f in t["fields"]}
    url  = f"{META_URL}/{tid}/fields"
    for spec in IK_FIELD_SPECS:
        if spec["name"] in existing:
            print(f"  {spec['name']}: already exists — skip")
            continue
        payload = {"name": spec["name"], "type": spec["type"]}
        if spec.get("options"):
            payload["options"] = spec["options"]
        _post(url, payload)
        print(f"  {spec['name']}: created ({spec['type']})")


def _fetch_all(table_key):
    """Fetch all records from a table."""
    records = []
    params  = {}
    url     = f"{DATA_URL}/{TABLE_IDS[table_key]}"
    while True:
        data = _get(url, params=params)
        records.extend(data.get("records", []))
        if not data.get("offset"):
            break
        params = {"offset": data["offset"]}
        time.sleep(0.25)
    return records


def _create_record(table_key, fields):
    url = f"{DATA_URL}/{TABLE_IDS[table_key]}"
    # typecast=True auto-extends singleSelect choices for new values (e.g. agv_type)
    result = _post(url, {"fields": fields, "typecast": True})
    return result["id"]  # Airtable record ID


def step3_create_companies():
    """Create 3 IK company records. Returns {name: airtable_rec_id}."""
    print("\nStep 3: Creating company records...")
    existing = {r["fields"].get("company_name"): r["id"] for r in _fetch_all("companies")}

    companies = [
        {
            "company_name": "GEA Refrigeration Technologies",
            "company_id":   str(uuid.uuid4()),
            "country":      "DE",
            "hq_city":      "Düsseldorf",
            "website":      "https://www.gea.com",
            "employee_count_range": "10000+",
            "languages_spoken": ["DE", "EN"],
            "export_capable": True,
            "last_updated": "2026-07-14",
        },
        {
            "company_name": "Güntner GmbH & Co. KG",
            "company_id":   str(uuid.uuid4()),
            "country":      "DE",
            "hq_city":      "Fürstenfeldbruck",
            "website":      "https://www.guentner.de",
            "employee_count_range": "1000–10000",
            "languages_spoken": ["DE", "EN"],
            "export_capable": True,
            "last_updated": "2026-07-14",
        },
        {
            "company_name": "BITZER SE",
            "company_id":   str(uuid.uuid4()),
            "country":      "DE",
            "hq_city":      "Sindelfingen",
            "website":      "https://www.bitzer.de",
            "employee_count_range": "1000–10000",
            "languages_spoken": ["DE", "EN"],
            "export_capable": True,
            "last_updated": "2026-07-14",
        },
    ]

    result = {}
    for co in companies:
        name = co["company_name"]
        if name in existing:
            print(f"  {name}: already exists (rec={existing[name]}) — skip")
            result[name] = existing[name]
        else:
            rec_id = _create_record("companies", co)
            print(f"  {name}: created (rec={rec_id})")
            result[name] = rec_id
    return result


def step4_create_base_models():
    """Create 3 base model records. Returns {name: airtable_rec_id}."""
    print("\nStep 4: Creating base model records...")
    existing = {r["fields"].get("base_model_name"): r["id"] for r in _fetch_all("base_models")}

    models = [
        {"base_model_name": "GEA BluAstrum NH3 Chiller Plant",      "base_model_id": str(uuid.uuid4()), "agv_type": "Process Cooling"},
        {"base_model_name": "Güntner GASC-AHE Cold Store Unit",     "base_model_id": str(uuid.uuid4()), "agv_type": "Cold Store"},
        {"base_model_name": "BITZER COSS Transcritical CO2 System",  "base_model_id": str(uuid.uuid4()), "agv_type": "Deep Freeze"},
    ]

    result = {}
    for m in models:
        name = m["base_model_name"]
        if name in existing:
            print(f"  {name}: already exists — skip")
            result[name] = existing[name]
        else:
            rec_id = _create_record("base_models", m)
            print(f"  {name}: created (rec={rec_id})")
            result[name] = rec_id
    return result


def step5_create_products(co_ids, bm_ids):
    """Create 3 product records linked to companies and base models."""
    print("\nStep 5: Creating product records...")
    existing = {r["fields"].get("product_name"): r["id"] for r in _fetch_all("products")}

    products = [
        {
            "product_name":        "GEA BluAstrum Ammonia Chiller",
            "product_id":          str(uuid.uuid4()),
            "agv_type":            "Process Cooling",
            "active":              True,
            "reference_count":     0,
            "product_description": "Industrial ammonia (R717) chiller plant for process cooling in F&B production environments. Designed for dairy, brewing, and food processing applications.",
            "company_id":          [co_ids["GEA Refrigeration Technologies"]],
            "base_model_id":       [bm_ids["GEA BluAstrum NH3 Chiller Plant"]],
        },
        {
            "product_name":        "Güntner GASC Cold Store Cooler",
            "product_id":          str(uuid.uuid4()),
            "agv_type":            "Cold Store",
            "active":              True,
            "reference_count":     0,
            "product_description": "Air cooler unit for refrigerated cold store rooms and warehouses. Multi-refrigerant capable (R744/R134a). Designed for fresh produce and food logistics applications.",
            "company_id":          [co_ids["Güntner GmbH & Co. KG"]],
            "base_model_id":       [bm_ids["Güntner GASC-AHE Cold Store Unit"]],
        },
        {
            "product_name":        "BITZER COSS Deep-Freeze System",
            "product_id":          str(uuid.uuid4()),
            "agv_type":            "Deep Freeze",
            "active":              True,
            "reference_count":     0,
            "product_description": "Transcritical CO2 (R744) booster system for deep-freeze storage and blast freezing in industrial food production and frozen logistics.",
            "company_id":          [co_ids["BITZER SE"]],
            "base_model_id":       [bm_ids["BITZER COSS Transcritical CO2 System"]],
        },
    ]

    result = {}
    for p in products:
        name = p["product_name"]
        if name in existing:
            print(f"  {name}: already exists — skip")
            result[name] = existing[name]
        else:
            rec_id = _create_record("products", p)
            print(f"  {name}: created (rec={rec_id})")
            result[name] = rec_id
    return result


def step6_create_extensions(bm_ids):
    """Create 3 extension records with IK field values."""
    print("\nStep 6: Creating base model extension records...")
    existing = {r["fields"].get("model_name"): r["id"] for r in _fetch_all("extensions")}

    extensions = [
        {
            "model_name":               "GEA BluAstrum NH3 Chiller Plant",
            "extension_id":             str(uuid.uuid4()),
            "base_model_id":            [bm_ids["GEA BluAstrum NH3 Chiller Plant"]],
            "agv_type":                 "Process Cooling",
            # IK fields
            "cooling_capacity_kw":      500.0,
            "temperature_min_celsius":  2.0,
            "refrigerant_types":        ["R717"],
            "certifications_ik":        ["PED", "EN 378"],
            "cop_efficiency":           4.8,
            "cooling_medium":           "glycol",
            "humidity_control_capable": False,
            # General
            "outdoor_capable":          True,
            "industries_served":        "Food & Beverage, Brewing, Dairy",
        },
        {
            "model_name":               "Güntner GASC-AHE Cold Store Unit",
            "extension_id":             str(uuid.uuid4()),
            "base_model_id":            [bm_ids["Güntner GASC-AHE Cold Store Unit"]],
            "agv_type":                 "Cold Store",
            # IK fields
            "cooling_capacity_kw":      120.0,
            "temperature_min_celsius":  0.0,
            "refrigerant_types":        ["R744", "R134a"],
            "certifications_ik":        ["PED", "F-Gas"],
            "cop_efficiency":           3.5,
            "cooling_medium":           "direct",
            "temperature_stability_k":  0.5,
            "room_volume_m3_max":       5000.0,
            "humidity_control_capable": True,
            # General
            "outdoor_capable":          False,
            "industries_served":        "Food Logistics, Fresh Produce, Retail Cold Store",
        },
        {
            "model_name":               "BITZER COSS Transcritical CO2 System",
            "extension_id":             str(uuid.uuid4()),
            "base_model_id":            [bm_ids["BITZER COSS Transcritical CO2 System"]],
            "agv_type":                 "Deep Freeze",
            # IK fields
            "cooling_capacity_kw":              350.0,
            "temperature_min_celsius":          -25.0,
            "refrigerant_types":                ["R744", "R290"],
            "certifications_ik":                ["PED", "F-Gas", "EN 378"],
            "cop_efficiency":                   2.8,
            "cooling_medium":                   "direct",
            "blast_freeze_capacity_kg_h":       800.0,
            "pulldown_time_h":                  3.5,
            "humidity_control_capable":         False,
            # General
            "outdoor_capable":                  False,
            "industries_served":                "Frozen Food, Ice Cream, Blast Freezing, Food Production",
        },
    ]

    for ext in extensions:
        name = ext["model_name"]
        if name in existing:
            print(f"  {name}: already exists — skip")
        else:
            rec_id = _create_record("extensions", ext)
            print(f"  {name}: created (rec={rec_id})")


def main():
    print("=" * 60)
    print("haystacked — IK Supplier Migration to Airtable")
    print("=" * 60)

    schema  = get_table_schema()

    step1_extend_agv_type(schema)
    step2_add_ik_fields(schema)

    co_ids  = step3_create_companies()
    bm_ids  = step4_create_base_models()
    step5_create_products(co_ids, bm_ids)
    step6_create_extensions(bm_ids)

    print("\n" + "=" * 60)
    print("Migration complete. Now run:")
    print("  python3 sync_airtable.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
