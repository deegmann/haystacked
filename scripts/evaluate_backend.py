#!/usr/bin/env python3
"""
AP-E1 -- Backend Evaluation Script
Runs tender test cases against the matching engine and prints a structured report.
Usage: python3 scripts/evaluate_backend.py [--tender tender_001]
"""
import sys
import json
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.data_loader import load_suppliers
from src.matching import TenderRequirements, Matcher

TENDER_DIR = BASE_DIR / "tests" / "tenders"


def load_tender(name: str) -> dict:
    p = TENDER_DIR / f"{name}.json"
    if not p.exists():
        sys.exit(f"Tender not found: {p}")
    with open(p) as f:
        return json.load(f)


def run_tender(tender: dict, suppliers, matcher: Matcher):
    tid  = tender["tender_id"]
    desc = tender.get("description", tid)

    print(f"\nTender: {tid}")
    print("=" * 50)
    print(f"  {desc}")

    if not tender.get("in_scope", True):
        print("\n  [OUT OF SCOPE] -- no AGV matching performed.")
        return

    req_dict = tender.get("requirements", {})
    req      = TenderRequirements(req_dict)

    t0 = time.time()
    matcher_inst = Matcher()
    top, all_results = matcher_inst.match(suppliers, req, top_n=10)
    elapsed = time.time() - t0

    qualified    = [r for r in all_results if not r.disqualified]
    disqualified = [r for r in all_results if r.disqualified]

    print(f"\n  K.O. Exclusions ({len(disqualified)}):")
    if disqualified:
        for r in disqualified:
            for reason in r.disqualified_by:
                print(f"    FAIL {r.product_name}: {reason}")
    else:
        print("    (none)")

    print(f"\n  Ranking ({len(qualified)} qualified suppliers):")
    for r in top[:5]:
        if r.disqualified:
            print(f"    {r.rank:2d}. [DISQUALIFIED] {r.product_name} ({r.company_name})")
            continue
        score_pct = int(r.score / r.max_score * 100) if r.max_score > 0 else 0
        print(f"    {r.rank:2d}. {r.product_name} ({r.company_name}): {r.score}/{r.max_score} ({score_pct}%)")
        for detail in r.score_details[:3]:
            val_str = f"= {detail['value']}" if detail.get("value") is not None else ""
            print(f"         {detail['field']} {val_str}  +{detail['points']} pts")

    print(f"\n  Performance: {elapsed*1000:.0f} ms (matching only, no LLM)")

    # Acceptance criteria
    print("\n  Acceptance criteria:")
    _check(len(qualified) >= 3, f"At least 3 qualified suppliers: {len(qualified)}")
    _check(elapsed < 1.0, f"Matching < 1 second: {elapsed*1000:.0f} ms")
    _check(len(disqualified) >= 0, "K.O. exclusions computed without crash")

    # Check NULL fields do not trigger K.O. (LL-06).
    # Exception: KO_BOOL_EXCLUSIVE (vna_capable) intentionally K.O.s NULL when required (LL-10).
    non_exclusive_null_kos = [
        r for r in disqualified
        if any(
            ("none" in reason.lower() or "null" in reason.lower())
            and "vna_capable" not in reason.lower()
            for reason in r.disqualified_by
        )
    ]
    _check(len(non_exclusive_null_kos) == 0,
           f"NULL fields never trigger K.O. (except KO_BOOL_EXCLUSIVE): {len(non_exclusive_null_kos)} violations")


def _check(cond: bool, msg: str):
    sym = "PASS" if cond else "FAIL"
    print(f"    [{sym}] {msg}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--tender", default=None, help="e.g. tender_001 (default: run all)")
    args = parser.parse_args()

    print("haystacked -- Backend Evaluation")
    print("-" * 50)

    try:
        suppliers = load_suppliers()
        print(f"Loaded {len(suppliers)} active supplier records from SQLite.")
    except FileNotFoundError as e:
        print(f"\nWARNING: {e}")
        print("Running with empty supplier list -- run sync_airtable.py first.\n")
        suppliers = []

    matcher = Matcher()

    if args.tender:
        tenders = [load_tender(args.tender)]
    else:
        tenders = []
        for p in sorted(TENDER_DIR.glob("tender_*.json")):
            with open(p) as f:
                tenders.append(json.load(f))

    for tender in tenders:
        run_tender(tender, suppliers, matcher)

    print("\n" + "=" * 50)
    print("Evaluation complete.")


if __name__ == "__main__":
    main()
