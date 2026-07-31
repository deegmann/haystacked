"""OI-115c Phase 3B — behavioral tests for sync_airtable.py's header guard.

check_header_guard() prevents a silent, zero-exit-code data wipe: if
config/sqlite_schema.json's declared columns (generated from AP0 field_name)
ever diverge from the live CSV headers (which mirror Airtable field names
verbatim), the dynamic INSERT OR REPLACE in import_to_sqlite() would write
NULL for every existing row in that column. These tests exercise the real
guard function directly against real and synthetic inputs.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import sync_airtable  # noqa: E402


def _real_csv_headers(name: str) -> list[str]:
    path = BASE_DIR / "data" / "raw" / f"{name}.csv"
    with open(path, encoding="utf-8", newline="") as f:
        return next(csv.reader(f))


def test_real_committed_csvs_pass_cleanly():
    """The guard must pass with zero exceptions against the real, committed
    CSVs and the current sqlite_schema.json — i.e. no undocumented drift exists
    today."""
    sync_airtable.check_header_guard(
        "companies", sync_airtable._CO_COLUMNS, _real_csv_headers("companies")
    )
    sync_airtable.check_header_guard(
        "products", sync_airtable._PROD_COLUMNS, _real_csv_headers("products")
    )
    sync_airtable.check_header_guard(
        "base_model_extensions",
        sync_airtable._EXT_COLUMNS,
        _real_csv_headers("base_model_extensions"),
    )


def test_missing_business_column_triggers_system_exit():
    """A schema column that silently vanishes from the CSV headers (simulating
    an Airtable field rename/drift that is NOT in the known baseline gap list)
    must abort the import via SystemExit."""
    real_headers = _real_csv_headers("base_model_extensions")
    assert "max_payload" in real_headers
    assert "max_payload" not in sync_airtable._KNOWN_GAPS.get(
        "base_model_extensions", []
    )

    synthetic_headers = [h for h in real_headers if h != "max_payload"]

    with pytest.raises(SystemExit):
        sync_airtable.check_header_guard(
            "base_model_extensions",
            sync_airtable._EXT_COLUMNS,
            synthetic_headers,
        )


def test_renamed_business_column_triggers_system_exit():
    """A schema column renamed in the source CSV (e.g. 'max_payload' ->
    'max_payload_renamed') is functionally identical to a missing column from
    the guard's perspective — the old name disappears from the header set.
    Uses a synthetic, non-real post-OI-115c-rename name ('max_payload_renamed')
    rather than a real field_name — after OI-115c stripped unit suffixes from
    field_names, substituting one real field_name for another real field_name
    here would be a no-op identity transform (both sides already read
    'max_payload') and the guard would never fire."""
    real_headers = _real_csv_headers("base_model_extensions")
    synthetic_headers = [
        "max_payload_renamed" if h == "max_payload" else h for h in real_headers
    ]

    with pytest.raises(SystemExit):
        sync_airtable.check_header_guard(
            "base_model_extensions",
            sync_airtable._EXT_COLUMNS,
            synthetic_headers,
        )


def test_known_gap_column_does_not_trigger_system_exit():
    """A column absent from the CSV but present in the committed baseline
    allowlist must NOT raise — this is the expected, non-destructive case."""
    known_gaps = sync_airtable._KNOWN_GAPS.get("base_model_extensions", [])
    assert known_gaps, "expected a non-empty known_gaps baseline for base_model_extensions"

    synthetic_headers = [
        h for h in sync_airtable._EXT_COLUMNS if h not in known_gaps
    ]

    sync_airtable.check_header_guard(
        "base_model_extensions", sync_airtable._EXT_COLUMNS, synthetic_headers
    )


def test_extra_csv_header_warns_but_does_not_exit(capsys):
    """A CSV header present but not declared in the schema (excluding known
    non-field columns) is a WARN, not a SystemExit — the reverse-direction
    check must remain non-destructive."""
    synthetic_headers = list(sync_airtable._CO_COLUMNS) + ["some_new_airtable_field"]

    sync_airtable.check_header_guard("companies", sync_airtable._CO_COLUMNS, synthetic_headers)

    captured = capsys.readouterr()
    assert "some_new_airtable_field" in captured.out
    assert "WARN" in captured.out
