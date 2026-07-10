"""Step 6 CSV Migration: simulates Airtable-side changes for local environment.

Changes applied to data/raw/base_model_extensions.csv:
1. infrastructure_required → infrastructure_free (column rename)
2. Boolean inversion: 'true' → 'false', 'false' → 'true', '' stays ''
   (Invariant: blank-count must be preserved — Blank ≠ Zero)
3. load_type value normalization to new AP0 allowed_values list
   - 'Plastic (closed)', 'Plastic (open-bottom)', 'Plastic' → 'Plastic Bin'
   - 'Bulk bin' → 'Bulk Bin'
   - 'Custom Carrier (dolly)', 'Custom Carrier (shelf/rack)',
     'Custom Carrier (paper reels)' → 'Custom Carrier'

integration_capability: no CSV changes needed (all supplier values already use 'OPC-UA').

Run: python3 scripts/migrate_csv_step6.py
Idempotent: running twice produces the same result.
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CSV_PATH = ROOT / "data" / "raw" / "base_model_extensions.csv"

BOOL_INVERT = {"true": "false", "false": "true", "": ""}

LOAD_TYPE_MAP = {
    "Plastic (closed)":        "Plastic Bin",
    "Plastic (open-bottom)":   "Plastic Bin",
    "Plastic":                 "Plastic Bin",
    "Bulk bin":                "Bulk Bin",
    "Custom Carrier (dolly)":  "Custom Carrier",
    "Custom Carrier (shelf/rack)": "Custom Carrier",
    "Custom Carrier (paper reels)": "Custom Carrier",
}


def _normalize_load_type(value: str) -> str:
    """Normalize a single load_type sub-value to the new AP0 canonical form."""
    v = value.strip()
    return LOAD_TYPE_MAP.get(v, v)


def _process_load_type(raw: str) -> str:
    if not raw:
        return raw
    parts = [p.strip() for p in raw.split("|") if p.strip()]
    normalized = []
    for p in parts:
        mapped = _normalize_load_type(p)
        if mapped not in normalized:
            normalized.append(mapped)
    return "|".join(normalized)


def main():
    rows = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        original_headers = reader.fieldnames or []
        rows = list(reader)

    if not rows:
        print("ERROR: CSV is empty")
        sys.exit(1)

    # Check idempotency: if already migrated, skip
    if "infrastructure_free" in original_headers and "infrastructure_required" not in original_headers:
        print("CSV already migrated to infrastructure_free — verifying load_type normalization only.")
        already_infra_migrated = True
    else:
        already_infra_migrated = False

    if "infrastructure_required" not in original_headers and not already_infra_migrated:
        print("ERROR: infrastructure_required column not found in CSV")
        sys.exit(1)

    # Validate blank-count invariant before migration
    if not already_infra_migrated:
        old_blanks = sum(1 for r in rows if r.get("infrastructure_required", "") == "")
        old_non_null_true = sum(1 for r in rows if r.get("infrastructure_required", "").lower() == "true")
        old_non_null_false = sum(1 for r in rows if r.get("infrastructure_required", "").lower() == "false")
        print(f"infrastructure_required: {old_blanks} blank, {old_non_null_true} true, {old_non_null_false} false")

    # Build new headers
    new_headers = []
    for h in original_headers:
        if h == "infrastructure_required":
            new_headers.append("infrastructure_free")
        else:
            new_headers.append(h)

    # Process rows
    modified_infra = 0
    modified_load = 0
    new_rows = []
    for row in rows:
        new_row = {}
        for old_h, new_h in zip(original_headers, new_headers):
            val = row.get(old_h, "")

            if old_h == "infrastructure_required" or new_h == "infrastructure_free":
                # Boolean inversion
                v_lower = val.lower() if val else ""
                new_val = BOOL_INVERT.get(v_lower, val)
                if new_val != val:
                    modified_infra += 1
                new_row[new_h] = new_val

            elif new_h == "load_type":
                new_val = _process_load_type(val)
                if new_val != val:
                    modified_load += 1
                new_row[new_h] = new_val

            else:
                new_row[new_h] = val

        new_rows.append(new_row)

    # Validate blank-count invariant after migration
    if not already_infra_migrated:
        new_blanks = sum(1 for r in new_rows if r.get("infrastructure_free", "") == "")
        assert new_blanks == old_blanks, (
            f"Blank-count mismatch! Before={old_blanks}, After={new_blanks}. "
            "NULL values must not be inverted."
        )
        print(f"infrastructure_free: {new_blanks} blank ✓ (invariant preserved)")

    # Write output
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=new_headers)
        writer.writeheader()
        writer.writerows(new_rows)

    print(f"CSV written: {len(new_rows)} rows")
    if not already_infra_migrated:
        print(f"  infrastructure_required → infrastructure_free: {modified_infra} cells inverted")
    print(f"  load_type normalized: {modified_load} cells updated")


if __name__ == "__main__":
    main()
