#!/usr/bin/env python3
"""
Patch lifting_height_mm (and corrections to max_payload_kg / min_aisle_width_mm)
for 8 Forklift AGV products researched 2026-06-30.

No new records — all patches apply to existing extensions.

Sources (HIGH confidence unless noted):
  Alstef GL          — alstefgroup.com: 1000–3000 mm range → ceiling 3000 mm
  Geek+ F12ML        — geekplus.com F-Series page: 120 mm low-lift transport
  GreyOrange RF-AP   — mobile-robots.com directory: 200 mm (7.8 in) floor transport
  KIVNON K50         — neetwk.com + search snippets: 1000 kg / 150 mm (MEDIUM-HIGH)
  Linde L-MATIC core — linde-mh.com OEM page: 1200 kg (was 1600!) / 1844 mm
  Stäubli FL1500     — staubli.com OEM: 3205 mm duplex mast
  STILL AXV 12 iGo  — still.de OEM: 1844 mm / 2480 mm aisle
  VisionNav VNP20    — visionnav.com OEM: 2000 kg (was 1900!) / 3000 mm

Run:
  python3 scripts/patch_lifting_heights_20260630.py
  python3 sync_airtable.py
"""
import json, os, time
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TOKEN   = os.environ["AIRTABLE_TOKEN"]
BASE_ID = os.environ["AIRTABLE_BASE_ID"]
schema  = json.loads((Path(__file__).parent.parent / "airtable/airtable_schema_ids.json").read_text())
TABLES  = {k: schema["table_ids"][k] for k in ["companies", "base_models", "products", "extensions"]}
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


PATCHES = [
    {
        "name": "Alstef GL",
        "fields": {"lifting_height_mm": 3000},
        "note": "OEM: configurable 1000–3000 mm; ceiling = 3000 for KO_IF_LT matching",
    },
    {
        "name": "Geek+ F12ML",
        "fields": {"lifting_height_mm": 120},
        "note": "Low-lift pallet transport robot (distinct from F20MT stacker at 3244 mm)",
    },
    {
        "name": "GreyOrange Ranger Forklift (RF-AP)",
        "fields": {"lifting_height_mm": 200},
        "note": "AnyPallet floor-transport AMR, 200 mm (7.8 in) — no racking capability",
    },
    {
        "name": "KIVNON K50 Pallet Truck",
        "fields": {"max_payload_kg": 1000, "lifting_height_mm": 150},
        "note": "Low-lift pallet truck; MEDIUM-HIGH confidence (kivnon.com 404, 2 corroborating sources)",
    },
    {
        "name": "Linde L-MATIC core",
        "fields": {"max_payload_kg": 1200, "lifting_height_mm": 1844},
        "note": "CORRECTION: payload was 1600 (taken from L-MATIC base). Core is distinct: 1200 kg / 1844 mm entry-level. OEM linde-mh.com",
    },
    {
        "name": "Stäubli FL1500",
        "fields": {"lifting_height_mm": 3205},
        "note": "Duplex mast max. OEM staubli.com product page (datasheet PDF still 403)",
    },
    {
        "name": "STILL AXV 12 iGo",
        "fields": {"lifting_height_mm": 1844, "min_aisle_width_mm": 2480},
        "note": "OEM still.de — identical entry-stacker spec to Linde L-MATIC core (independent confirmation)",
    },
    {
        "name": "VisionNav VNP20",
        "fields": {"max_payload_kg": 2000, "lifting_height_mm": 3000},
        "note": "CORRECTION: payload was 1900 (aggregator variant VNP20(V)-07 derated config). OEM: 2000 kg / 3000 mm standard mast",
    },
]


def find_ext(name: str):
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES['extensions']}"
    r = requests.get(url, headers=HEADERS,
                     params={"filterByFormula": f'{{model_name}}="{name}"', "maxRecords": 1},
                     timeout=30)
    r.raise_for_status()
    recs = r.json().get("records", [])
    return recs[0] if recs else None


def patch_ext(rec_id: str, fields: dict) -> None:
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLES['extensions']}/{rec_id}"
    r = requests.patch(url, headers=HEADERS, json={"fields": fields}, timeout=30)
    if not r.ok:
        print(f"    HTTP {r.status_code}: {r.text[:300]}")
    r.raise_for_status()


if __name__ == "__main__":
    ok, errors = 0, []

    print("Patching lifting heights + corrections — 8 products")
    print("=" * 60)

    for p in PATCHES:
        name = p["name"]
        print(f"\n→ {name}")
        print(f"   {p['note']}")
        ext = find_ext(name)
        if not ext:
            print(f"   ✗ Extension not found")
            errors.append(name)
            time.sleep(0.2)
            continue
        patch_ext(ext["id"], p["fields"])
        print(f"   ✓ {p['fields']}")
        ok += 1
        time.sleep(0.3)

    print(f"\n{'='*60}")
    print(f"Done: {ok}/8 patched")
    if errors:
        print(f"Not found: {errors}")
    print("Next: python3 sync_airtable.py")
