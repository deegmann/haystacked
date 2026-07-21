"""Step 6 Golden Refresh: re-runs matching (no LLM) against current DB + config.

For each golden_run_tender_*.json file:
1. Reads existing agv_criteria (extraction unchanged)
2. Re-runs matching with current matching engine + supplier DB
3. Updates match_results and matches_all in-place
4. Adds step6_refreshed_at timestamp

Run: python3 scripts/refresh_golden_step6.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from app import _criteria_to_uuid_keyed, _to_match_units
from src.matching import match_suppliers_new, TenderRequirements, validate_tender_values
from src.data_loader import load_suppliers

GOLDEN_DIR = ROOT / "tests" / "tenders"


def refresh_golden(path: Path, suppliers) -> dict:
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)

    agv_criteria = doc.get("agv_criteria", {})
    vehicle_type = doc.get("vehicle_type", "")
    is_vna = doc.get("is_vna", False)
    detected_domain = doc.get("detected_domain") or "Logistics:AGV"  # default: AGV (all golden files are extractable)
    in_scope = doc.get("in_scope", True)

    # Out-of-scope tenders have no match results — preserve empty state
    if not in_scope:
        old_matches = doc.get("match_results", [])
        doc["match_results"] = []
        doc["matches_all"] = []
        doc["step6_refreshed_at"] = datetime.now().isoformat(timespec="seconds")
        return doc, old_matches != [], 0, 0, [], []

    # Inject vehicle type and VNA flag into criteria (same as app.py does)
    criteria_with_vt = dict(agv_criteria)
    if vehicle_type:
        criteria_with_vt["required_product_type"] = vehicle_type
    if is_vna:
        criteria_with_vt["required_vna_capable"] = "required"

    # Re-validate through current AP0 allowed_values (catches OI-61 slash-compound
    # values stored in pre-OI-61 golden files, and removes 'OPC UA' post-Step-6)
    criteria_validated, _ = validate_tender_values(criteria_with_vt)

    # Convert stored units (m) back to match-engine units (mm) — mirrors app.py pipeline
    criteria_match_units = _to_match_units(criteria_validated)
    uuid_criteria = _criteria_to_uuid_keyed(criteria_match_units)
    req = TenderRequirements.from_dict(uuid_criteria)

    top_raw, all_raw = match_suppliers_new(req, suppliers)

    new_matches = [r.to_dict() for r in top_raw]
    new_matches_all = [r.to_dict() for r in all_raw]

    # Summary of changes
    old_matches = doc.get("match_results", [])
    old_top_products = [r.get("product", "") for r in old_matches]
    new_top_products = [r.get("product", "") for r in new_matches]

    changed = old_top_products != new_top_products
    disq_before = sum(1 for r in old_matches if r.get("disqualified"))
    disq_after = sum(1 for r in new_matches if r.get("disqualified"))

    doc["match_results"] = new_matches
    doc["matches_all"] = new_matches_all
    doc["step6_refreshed_at"] = datetime.now().isoformat(timespec="seconds")

    return doc, changed, disq_before, disq_after, old_top_products, new_top_products


def main():
    print("Loading suppliers from DB...")
    suppliers = load_suppliers()
    print(f"  {len(suppliers)} active supplier records")
    print()

    golden_files = sorted(GOLDEN_DIR.glob("golden_run_tender_*.json"))
    if not golden_files:
        print("No golden run files found.")
        return

    for path in golden_files:
        print(f"Processing: {path.name}")
        doc, changed, disq_before, disq_after, old_tops, new_tops = refresh_golden(path, suppliers)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
            f.write("\n")

        if changed:
            print(f"  ⚠ Match results CHANGED:")
            print(f"    Before: {old_tops}")
            print(f"    After:  {new_tops}")
            print(f"    Disqualified: {disq_before} → {disq_after}")
        else:
            print(f"  ✓ Match results unchanged (disq: {disq_before} → {disq_after})")


if __name__ == "__main__":
    main()
