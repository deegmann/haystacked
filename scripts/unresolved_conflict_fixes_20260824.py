"""Apply the 7 confirmed resolutions from the 13-item UNRESOLVED-conflict backlog
(docs/datasheet_final_conflicts_20260821.md), resolved by directly re-reading the cited
source PDFs (each PDF was extracted as page images via the Read tool, not just the earlier
text-layer pass, which is what let several of these resolve cleanly this time).

Each resolution and its exact citation is documented in the Tech Lead's report for this
session; not re-derived here. 3 items from the original 13 are intentionally NOT included:
- ek robotics COMPACT MOVE CB 25 lifting_height, Toyota Reflex RAE250 vehicle_length,
  VisionNav VNE40 max_payload: resolved as "keep the current DB value", so no write needed.
- Linde L-MATIC max_payload: NOT resolved -- the source document's own footnote supports a
  third candidate (2000kg) that neither the DB (1600) nor the extracted value (1200)
  proposed; left for a separate Tech Lead decision.
- Linde L-MATIC AC k / HD k lifting_height: blocked on the pre-existing open AP0 policy
  question (Hub vs Einlagerungshöhe convention), not a data question -- out of scope here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

import import_datasheet_project_20260822 as base  # noqa: E402

DOCS = Path(__file__).parent.parent / "docs"
AUDIT_PATH = DOCS / "unresolved_conflict_fixes_20260824_audit.jsonl"
base.AUDIT_PATH = AUDIT_PATH

# (company, product_name, field, new_value, citation)
FIXES = [
    ("Balyo", "VEENY", "max_speed", 2.0,
     "Veeny_-_VNA_Datasheet_-_11112021.pdf p.1 stat table: 'Forward speed (with 360° Safety): "
     "2 / 4.47' and 'Backward speed: 2 / 4.47' (m/s / mph)"),
    ("Balyo", "LOWY CB", "min_aisle_width", 3400,
     "'LOWY CB, Robotic Counterbalanced Stacker, AGV:AMR | BALYO.pdf' page header stat block: "
     "'FROM 3.4m / 11.4ft — Aisle width'"),
    ("Hikrobot", "Hikrobot F3-1500", "min_aisle_width", 2213,
     "AGV_Brochure_(Full_Version)_ENG_2026Q2-V1...pdf p.47 Specification table, F3-1500 column, "
     "'Min aisle width (Ast): 2213mm'"),
    ("Hikrobot", "Hikrobot F3-1500", "max_speed", 1.5,
     "F3-1500_flyer_eng_cemat_v2.pdf p.2 Specification table 'Running Speed: 1.5/1.2m/s' and "
     "p.1 Key Feature 'max. running speed 1.5m/s'; confirmed by "
     "AGV_Brochure_(Full_Version)...pdf p.47 'Rated running speed (empty): 1.5'"),
    ("Linde Material Handling", "Linde L-MATIC", "lifting_height", 1924,
     "DE_tb_l_matic_br133_de_a_0516.pdf p.2 VDI row 4.4 'Hub h3 (mm) 1924' and p.3 "
     "Serienausstattung 'Standard Hubmast 1924mm' -- stated twice, DB's 2900 appears nowhere"),
    ("Toyota Material Handling Europe", "Toyota Reflex RAE250 Autopilot", "load_detection",
     ["Mechanical/Tactile", "Barcode/DataMatrix", "Camera/Vision"],
     "747505-040.pdf p.5 'Truck features': 'Barcode scanner (optional)', 'Advanced vision "
     "aided load handling (optional)', and 'Load presence and push detection' are all listed "
     "as real, non-exclusive options -- union, not a single value"),
    ("Toyota Material Handling Europe", "Toyota Autopilot SAI125CB", "load_type",
     ["Half-Euro", "Pallet EUR", "Pallet ISO"],
     "tmha_sai125cb_brochure.pdf p.3 'Aisle width Auto mode' table: load length/width columns "
     "600x800 / 800x1200 / 1000x1200mm exactly match Half-Euro / EUR-pallet / ISO-pallet "
     "footprints; no roll-container attachment is mentioned anywhere in this fork-stacker sheet"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="Execute live writes (default: dry-run)")
    args = ap.parse_args()
    base.DRY = not args.run

    print(f"MODE: {'LIVE RUN' if args.run else 'DRY RUN'}\n")

    base.load_env()
    base.fetch_live_schema()

    print(f"Applying {len(FIXES)} confirmed resolutions\n")

    for company, product_name, field, new_value, citation in FIXES:
        ext = base.resolve_extension(company, product_name)
        if ext is None:
            print(f"  ! SKIP {company} / {product_name}: no extension record found live in Airtable")
            continue
        rec_id = ext["airtable_id"]
        old_value = ext.get(field)
        print(f"  {company} / {product_name} / {field}: {old_value!r} -> {new_value!r} ({rec_id})")
        base.patch_record("extensions", rec_id, {field: new_value},
                           context=f"unresolved-conflict-fix:{product_name}:{field}")
        base.audit({
            "op": "patch", "bucket": "UNRESOLVED CONFLICT RESOLUTION", "company": company,
            "db_row": product_name, "entity": "Base Model", "field": field,
            "old": old_value, "new": new_value, "citation": citation,
        })

    print("\nDone." if args.run else "\nDRY RUN complete -- no Airtable calls were made.")


if __name__ == "__main__":
    main()
