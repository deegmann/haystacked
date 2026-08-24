"""Clear cross-variant contamination on the 6 VisionNav anchor rows left behind by the
2026-08-22 live import's ENRICH FILLS collision (see docs/variant_split_full_plan_20260824.md).

Background: scripts/variant_split_full_20260824.py corrected the anchor rows' fields where the
anchor variant's OWN source data had a value differing from the DB. It correctly left alone any
field the anchor's own source had no opinion on -- but for several fields, the DB's existing value
in that "no opinion" case wasn't blank, it was a value borrowed from a SIBLING variant during the
original 2026-08-22 collision (ENRICH FILLS bucket, confirmed via docs/import_datasheet_project_
20260822_audit.jsonl). Attributing e.g. VisionNav VNP15(V)-07's load_type to the separately-kept
"VisionNav VNP15" anchor row misrepresents that product. Per the "never invent a value" rule, these
71 fields (AGILOX ONE: 0, Linde C-MATIC: 0, VisionNav x6: 71) must be cleared to null, not left
holding another product's data.

Selection criteria (both must hold) -- computed once, by hand, by the Tech Lead, not re-derived
here: (1) audit log shows the field on this exact db_row was written via the ENRICH FILLS bucket
in the 2026-08-22 run, and (2) the anchor variant's own field data (opus first, sonnet fallback --
same source-priority as the parent migration) has NO value for that field. The list below is that
exact, manually-verified 71-item output -- this script's only job is to null them via the Airtable
API using the same conventions as the reference scripts (schema-safe write, retry-once, audit log).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

import import_datasheet_project_20260822 as base  # noqa: E402

DOCS = Path(__file__).parent.parent / "docs"
AUDIT_PATH = DOCS / "variant_split_clear_contamination_20260824_audit.jsonl"
base.AUDIT_PATH = AUDIT_PATH

# (product_name, [contaminated extension fields to null])
CONTAMINATION = {
    "VisionNav VNSL14": [
        "pick_req_accuracy_dep", "min_total_height", "load_detection", "drop_accuracy_angle",
        "manual_usage", "station_applications", "load_type", "safety_coverage",
        "forks_free_floating", "pick_req_accuracy_angle", "pick_req_accuracy_lat",
        "drop_accuracy_dep", "stop_accuracy", "drop_accuracy_lat", "mast_type",
    ],
    "VisionNav VNP15": [
        "pick_req_accuracy_dep", "min_total_height", "drop_accuracy_angle", "manual_usage",
        "fork_spread", "station_applications", "load_type", "safety_coverage",
        "trailer_unloading", "special_fork_option", "forks_free_floating",
        "pick_req_accuracy_angle", "pick_req_accuracy_lat", "drop_accuracy_dep", "stop_accuracy",
        "trailer_loading", "drop_accuracy_lat", "mast_type",
    ],
    "VisionNav VNQ50": [
        "outdoor_capable", "load_type", "safety_coverage", "route_type", "stop_accuracy",
        "trailer_steering_technology",
    ],
    "VisionNav VNE40": [
        "pick_req_accuracy_dep", "min_total_height", "load_detection", "station_applications",
        "load_type", "safety_coverage", "special_fork_option", "forks_free_floating",
        "pick_req_accuracy_angle", "pick_req_accuracy_lat", "stop_accuracy", "mast_type",
    ],
    "VisionNav VNE20": [
        "pick_req_accuracy_dep", "station_applications", "load_type", "special_fork_option",
        "forks_free_floating", "pick_req_accuracy_angle", "pick_req_accuracy_lat",
        "stop_accuracy", "mast_type",
    ],
    "VisionNav VNST20": [
        "manual_usage", "battery_type", "station_applications", "operating_temp_max",
        "load_type", "safety_coverage", "operating_humidity_max", "trailer_unloading",
        "operating_temp_min", "stop_accuracy", "trailer_loading",
    ],
}

COMPANY = "VisionNav Robotics"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="Execute live writes (default: dry-run)")
    args = ap.parse_args()
    base.DRY = not args.run

    print(f"MODE: {'LIVE RUN' if args.run else 'DRY RUN'}\n")

    base.load_env()
    base.fetch_live_schema()

    total_fields = sum(len(v) for v in CONTAMINATION.values())
    print(f"Clearing {total_fields} contaminated field(s) across {len(CONTAMINATION)} rows\n")

    for product_name, fields in CONTAMINATION.items():
        ext = base.resolve_extension(COMPANY, product_name)
        if ext is None:
            print(f"  ! SKIP {product_name}: no extension record found live in Airtable")
            continue
        rec_id = ext["airtable_id"]
        patch = {f: None for f in fields}
        print(f"  {product_name} ({rec_id}): nulling {fields}")
        base.patch_record("extensions", rec_id, patch, context=f"clear-contamination:{product_name}")
        for f in fields:
            base.audit({
                "op": "patch", "bucket": "CONTAMINATION CLEAR", "company": COMPANY,
                "db_row": product_name, "entity": "Base Model", "field": f,
                "old": ext.get(f), "new": None,
                "reason": "value borrowed from a sibling variant during the 2026-08-22 "
                          "ENRICH FILLS collision; anchor's own source has no value for this field",
            })

    print("\nDone." if args.run else "\nDRY RUN complete -- no Airtable calls were made.")


if __name__ == "__main__":
    main()
