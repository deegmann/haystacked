"""migrate_ik_csv_phase3.py — Phase 3 IK Sprint: CSV data migration.

Corrects IK records in local CSVs from pre-Option-D (product_type = sub-type)
to Option-D (product_type = "Industrial Refrigeration" + served_categories).

Changes:
  base_model_extensions.csv:
    - IK records: product_type → "Industrial Refrigeration"
    - adds served_categories column (maps from old product_type value)
    - BITZER COSS record: served_categories = "Cold Store|Deep Freeze"

  products.csv:
    - IK records: product_type → "Industrial Refrigeration"

  base_models.csv:
    - IK records: product_type → "Industrial Refrigeration"
"""

import csv
from pathlib import Path

ROOT     = Path(__file__).parent.parent
DATA_RAW = ROOT / "data" / "raw"

IK_SUB_TYPES = {"Process Cooling", "Cold Store", "Deep Freeze"}
NEW_AGV_TYPE  = "Industrial Refrigeration"


def _read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]):
    with open(path, encoding="utf-8", newline="") as f:
        pass  # just to verify it opens
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _is_bitzer(row: dict) -> bool:
    """Identify BITZER COSS record by cooling_capacity_kw or model_name substring."""
    cap = row.get("cooling_capacity_kw", "")
    name = row.get("model_name", "").upper()
    try:
        if float(cap) == 350.0:
            return True
    except (ValueError, TypeError):
        pass
    return "BITZER" in name or "COSS" in name


def migrate_base_model_extensions():
    path = DATA_RAW / "base_model_extensions.csv"
    print(f"\n[base_model_extensions.csv]")
    fieldnames, rows = _read_csv(path)

    # Add served_categories column if not present
    if "served_categories" not in fieldnames:
        fieldnames.append("served_categories")
        print(f"  Added 'served_categories' column to header")

    updated = 0
    for row in rows:
        old_type = row.get("product_type", "")
        if old_type not in IK_SUB_TYPES:
            continue

        # Determine served_categories
        if _is_bitzer(row):
            served = "Cold Store|Deep Freeze"
            print(f"  BITZER record (cooling_capacity_kw={row.get('cooling_capacity_kw')}): "
                  f"product_type '{old_type}' → '{NEW_AGV_TYPE}', served_categories='{served}'")
        else:
            served = old_type  # e.g. "Process Cooling" stays as-is
            print(f"  product_type '{old_type}' → '{NEW_AGV_TYPE}', served_categories='{served}'")

        row["product_type"] = NEW_AGV_TYPE
        row["served_categories"] = served
        updated += 1

    print(f"  Updated {updated} IK records in base_model_extensions.csv")
    _write_csv(path, fieldnames, rows)
    print(f"  Written: {path}")


def migrate_products():
    path = DATA_RAW / "products.csv"
    print(f"\n[products.csv]")
    fieldnames, rows = _read_csv(path)

    updated = 0
    for row in rows:
        old_type = row.get("product_type", "")
        if old_type in IK_SUB_TYPES:
            print(f"  product_type '{old_type}' → '{NEW_AGV_TYPE}' (product: {row.get('product_name', '?')})")
            row["product_type"] = NEW_AGV_TYPE
            updated += 1

    print(f"  Updated {updated} IK records in products.csv")
    _write_csv(path, fieldnames, rows)
    print(f"  Written: {path}")


def migrate_base_models():
    path = DATA_RAW / "base_models.csv"
    print(f"\n[base_models.csv]")
    fieldnames, rows = _read_csv(path)

    updated = 0
    for row in rows:
        old_type = row.get("product_type", "")
        if old_type in IK_SUB_TYPES:
            print(f"  product_type '{old_type}' → '{NEW_AGV_TYPE}' (model: {row.get('base_model_name', '?')})")
            row["product_type"] = NEW_AGV_TYPE
            updated += 1

    print(f"  Updated {updated} IK records in base_models.csv")
    _write_csv(path, fieldnames, rows)
    print(f"  Written: {path}")


def main():
    print("=" * 60)
    print("migrate_ik_csv_phase3.py — Phase 3 CSV data migration")
    print("=" * 60)

    for fname in ["base_model_extensions.csv", "products.csv", "base_models.csv"]:
        p = DATA_RAW / fname
        if not p.exists():
            raise SystemExit(f"[FEHLER] {p} not found")

    migrate_base_model_extensions()
    migrate_products()
    migrate_base_models()

    print("\nDone. Run 'python3 sync_airtable.py --local' next.")


if __name__ == "__main__":
    main()
