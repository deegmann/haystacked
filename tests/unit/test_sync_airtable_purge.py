"""OI-118 / OI-119 — behavioral tests for import_to_sqlite()'s purge and
base_models insert logic.

sync_airtable.py previously only ever did INSERT OR REPLACE: a row deleted
in Airtable stayed active/present in the local DB forever (OI-118), and
base_models was never written to at all (OI-119) — see
project_manual_notes_20260806.md and feedback_verify_before_asserting.md for
how both were found, and how the OI-118 fix's first cut (products only) was
itself incomplete until a same-day senior-architect post-implementation
review caught that base_model_extensions purging was missing — the exact
same "a row deleted upstream lingers forever" bug, but more dangerous there:
an orphaned extension row silently drops its still-active product out of
src/data_loader.py's INNER JOIN entirely, with no error and no log line.

These tests exercise import_to_sqlite() directly against copies of the real
committed CSVs, with DB_PATH monkeypatched to a throwaway file —
import_to_sqlite() connects to the module-level DB_PATH directly, so running
it unpatched against these fixtures would write into production data.
"""

from __future__ import annotations

import csv
import json as _json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import sync_airtable  # noqa: E402

_RAW = BASE_DIR / "data" / "raw"
_CSV_NAMES = ["companies.csv", "products.csv", "base_model_extensions.csv", "base_models.csv"]


def _read_csv(path: Path):
    with open(path, encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        return list(r), r.fieldnames


def _write_csv(path: Path, fieldnames, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _copy_real_csvs(tmp_path: Path) -> dict[str, Path]:
    dest = {}
    for name in _CSV_NAMES:
        d = tmp_path / name
        shutil.copy(_RAW / name, d)
        dest[name] = d
    return dest


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(sync_airtable, "DB_PATH", db_path)
    return db_path


def _import(csvs, allow_large_purge=False):
    return sync_airtable.import_to_sqlite(
        csvs["companies.csv"],
        csvs["products.csv"],
        csvs["base_model_extensions.csv"],
        csvs["base_models.csv"],
        allow_large_purge=allow_large_purge,
    )


# ── Products purge ──────────────────────────────────────────────────────────


def test_purge_deactivates_product_removed_from_csv(tmp_db, tmp_path):
    csvs = _copy_real_csvs(tmp_path)
    rows, fieldnames = _read_csv(csvs["products.csv"])
    assert len(rows) > 1
    removed = rows[0]

    _import(csvs)  # seed sync: `removed` starts out active=1 in the DB

    _write_csv(csvs["products.csv"], fieldnames, rows[1:])  # simulate Airtable deletion
    purged = _import(csvs)  # purge sync: `removed` is no longer in the fresh CSV

    con = sqlite3.connect(tmp_db)
    row = con.execute(
        "SELECT active FROM products WHERE product_id=?", (removed["product_id"],)
    ).fetchone()
    con.close()
    assert row is not None, "purge must soft-delete (row stays), not hard-delete"
    assert row[0] == 0, "product removed from the fresh CSV must be deactivated"

    # import_to_sqlite() must report what it purged — this is what main() uses
    # to print the end-of-run banner and write purge_log.jsonl, so the user is
    # always told which data was deleted, not just left to notice via a
    # scrolled-past inline print.
    assert purged["products"] == [
        {"product_id": removed["product_id"], "product_name": removed["product_name"]}
    ]


def test_purge_leaves_present_products_active(tmp_db, tmp_path):
    csvs = _copy_real_csvs(tmp_path)
    rows, _ = _read_csv(csvs["products.csv"])
    kept_id = rows[1]["product_id"]

    _import(csvs)

    con = sqlite3.connect(tmp_db)
    row = con.execute("SELECT active FROM products WHERE product_id=?", (kept_id,)).fetchone()
    con.close()
    assert row[0] == 1


def test_purge_ignores_blank_product_id_rows_in_fresh_set(tmp_db, tmp_path):
    """A blank product_id in the fresh CSV must not poison the NOT IN predicate.

    SQLite: `x NOT IN (a, NULL)` matches zero rows regardless of x — without
    stripping None/"" from the fresh set first, a single blank product_id
    anywhere in products.csv would silently turn the purge into a no-op for
    every row, with no error and no log line to notice it by.
    """
    csvs = _copy_real_csvs(tmp_path)
    rows, fieldnames = _read_csv(csvs["products.csv"])
    removed = rows[0]

    _import(csvs)  # seed sync: `removed` starts out active=1 in the DB

    remaining = rows[1:]
    blank_row = dict(remaining[0])
    blank_row["product_id"] = ""
    remaining.append(blank_row)
    _write_csv(csvs["products.csv"], fieldnames, remaining)
    _import(csvs)  # purge sync, fresh set now also contains one blank product_id

    con = sqlite3.connect(tmp_db)
    row = con.execute(
        "SELECT active FROM products WHERE product_id=?", (removed["product_id"],)
    ).fetchone()
    con.close()
    assert row[0] == 0, "purge must still fire even when the fresh set contains a blank product_id"


def test_purge_aborts_on_empty_fresh_product_set(tmp_db, tmp_path):
    """An empty/truncated fetch must never be read as 'everything was
    deleted' — that would deactivate all products. Must abort instead."""
    csvs = _copy_real_csvs(tmp_path)
    _, fieldnames = _read_csv(csvs["products.csv"])
    _write_csv(csvs["products.csv"], fieldnames, [])

    with pytest.raises(SystemExit):
        _import(csvs)


def test_purge_rowcount_does_not_recount_already_inactive_products(tmp_db, tmp_path):
    """The UPDATE must scope to active=1 rows, or cur.rowcount (and the
    reported purge count) over-reports by re-touching rows that were already
    inactive from a prior run."""
    csvs = _copy_real_csvs(tmp_path)
    rows, fieldnames = _read_csv(csvs["products.csv"])
    removed = rows[0]

    _import(csvs)  # seed
    _write_csv(csvs["products.csv"], fieldnames, rows[1:])
    first = _import(csvs)  # removed -> active=0
    assert len(first["products"]) == 1

    second = _import(csvs)  # same fresh set again, removed already inactive
    assert second["products"] == [], "a product already inactive must not be reported as newly purged again"


# ── Extensions purge (hard delete) ──────────────────────────────────────────


def test_purge_deletes_extension_removed_from_csv(tmp_db, tmp_path):
    csvs = _copy_real_csvs(tmp_path)
    rows, fieldnames = _read_csv(csvs["base_model_extensions.csv"])
    assert len(rows) > 1
    removed = rows[0]

    _import(csvs)  # seed

    _write_csv(csvs["base_model_extensions.csv"], fieldnames, rows[1:])
    purged = _import(csvs)

    con = sqlite3.connect(tmp_db)
    row = con.execute(
        "SELECT 1 FROM base_model_extensions WHERE extension_id=?", (removed["extension_id"],)
    ).fetchone()
    con.close()
    assert row is None, "extensions have no active column — purge must hard DELETE, not soft-delete"
    assert len(purged["extensions"]) == 1
    assert purged["extensions"][0]["extension_id"] == removed["extension_id"]


def test_purge_flags_extension_whose_product_is_still_active(tmp_db, tmp_path):
    """The dangerous case: an extension row is deleted upstream but its
    product survives — the product would silently vanish from
    src/data_loader.py's INNER JOIN with zero error. The purge report must
    flag this explicitly rather than reporting it identically to a benign
    delete-alongside-its-product case."""
    csvs = _copy_real_csvs(tmp_path)
    ext_rows, ext_fields = _read_csv(csvs["base_model_extensions.csv"])
    prod_rows, _ = _read_csv(csvs["products.csv"])
    removed = ext_rows[0]
    target_bm_id = removed["base_model_id"]
    assert any(p["base_model_id"] == target_bm_id for p in prod_rows), (
        "fixture assumption: the removed extension's base_model still has an active product"
    )

    _import(csvs)  # seed

    _write_csv(csvs["base_model_extensions.csv"], ext_fields, ext_rows[1:])
    purged = _import(csvs)  # product stays in products.csv, only the extension vanishes

    flagged = [e for e in purged["extensions"] if e["extension_id"] == removed["extension_id"]]
    assert len(flagged) == 1
    assert flagged[0]["orphaned_active_product"] is True


def test_purge_aborts_on_empty_fresh_extension_set(tmp_db, tmp_path):
    csvs = _copy_real_csvs(tmp_path)
    _, fieldnames = _read_csv(csvs["base_model_extensions.csv"])
    _write_csv(csvs["base_model_extensions.csv"], fieldnames, [])

    with pytest.raises(SystemExit):
        _import(csvs)


# ── Large-purge guard ────────────────────────────────────────────────────────


def test_large_product_purge_aborts_without_flag(tmp_db, tmp_path):
    csvs = _copy_real_csvs(tmp_path)
    rows, fieldnames = _read_csv(csvs["products.csv"])
    assert len(rows) > 20

    _import(csvs)  # seed: everything active

    # simulate a truncated fetch: only keep a handful of rows
    _write_csv(csvs["products.csv"], fieldnames, rows[:3])

    with pytest.raises(SystemExit):
        _import(csvs)


def test_large_product_purge_proceeds_with_flag(tmp_db, tmp_path):
    csvs = _copy_real_csvs(tmp_path)
    rows, fieldnames = _read_csv(csvs["products.csv"])

    _import(csvs)  # seed

    _write_csv(csvs["products.csv"], fieldnames, rows[:3])
    purged = _import(csvs, allow_large_purge=True)

    assert len(purged["products"]) == len(rows) - 3


def test_small_product_purge_does_not_require_flag(tmp_db, tmp_path):
    """A handful of genuine deletions (today's actual use case) must not be
    blocked by the large-purge guard — only an implausibly large fraction is."""
    csvs = _copy_real_csvs(tmp_path)
    rows, fieldnames = _read_csv(csvs["products.csv"])

    _import(csvs)  # seed

    _write_csv(csvs["products.csv"], fieldnames, rows[2:])  # remove 2 of many
    purged = _import(csvs)  # no exception, no flag needed

    assert len(purged["products"]) == 2


# ── base_models insert (OI-119) ──────────────────────────────────────────────


def test_base_models_table_populated(tmp_db, tmp_path):
    """OI-119 smoke test: base_models must actually receive rows.

    Before this fix, sync_airtable.py built a lookup dict from base_models.csv
    but never issued a single INSERT into the base_models table — confirmed via
    `git log -S "INTO base_models"` returning zero hits across all history.
    """
    csvs = _copy_real_csvs(tmp_path)
    bm_rows, _ = _read_csv(csvs["base_models.csv"])
    expected = len([r for r in bm_rows if r.get("base_model_id")])
    assert expected > 0, "fixture assumption: real base_models.csv has rows with a base_model_id"

    _import(csvs)

    con = sqlite3.connect(tmp_db)
    count = con.execute("SELECT COUNT(*) FROM base_models").fetchone()[0]
    con.close()
    assert count == expected


def test_base_models_blank_oem_link_public_does_not_crash(tmp_db, tmp_path):
    """oem_link_public is NOT NULL in the schema but blank on most real CSV
    rows — must be defaulted, not passed through as None (sqlite3.IntegrityError)."""
    csvs = _copy_real_csvs(tmp_path)
    bm_rows, _ = _read_csv(csvs["base_models.csv"])
    assert any(
        not r.get("oem_link_public") for r in bm_rows if r.get("base_model_id")
    ), "fixture assumption: at least one real row has a blank oem_link_public"

    _import(csvs)  # must not raise


def test_base_models_skips_blank_primary_key_rows(tmp_db, tmp_path):
    """Rows with no base_model_id (a separate, pre-existing Airtable
    formula-field gap) must be skipped, not inserted as junk rows under a
    blank TEXT PRIMARY KEY."""
    csvs = _copy_real_csvs(tmp_path)
    bm_rows, _ = _read_csv(csvs["base_models.csv"])
    assert any(not r.get("base_model_id") for r in bm_rows), (
        "fixture assumption: real base_models.csv has at least one row with "
        "a blank base_model_id"
    )

    _import(csvs)

    con = sqlite3.connect(tmp_db)
    blank_pk_rows = con.execute(
        "SELECT COUNT(*) FROM base_models WHERE base_model_id IS NULL OR base_model_id = ''"
    ).fetchone()[0]
    con.close()
    assert blank_pk_rows == 0


def test_dangling_base_model_id_warns_but_does_not_abort(tmp_db, tmp_path, capsys):
    """An active product whose base_model_id has no base_models row (a known,
    separate pre-existing gap — see test_base_models_skips_blank_primary_key_rows)
    must be logged loudly but must not abort the sync."""
    csvs = _copy_real_csvs(tmp_path)
    _import(csvs)  # must not raise despite the 3 known dangling rows

    captured = capsys.readouterr()
    assert "[WARN]" in captured.out
    assert "base_model_id" in captured.out


# ── Durable purge log ────────────────────────────────────────────────────────


def test_log_purge_writes_durable_jsonl_record(tmp_path, monkeypatch):
    """purge_log.jsonl must persist what was deactivated/deleted independent
    of terminal scrollback — one JSON line per run that purged something."""
    monkeypatch.setattr(sync_airtable, "DATA_RAW", tmp_path)
    purged = {
        "products": [{"product_id": "abc-123", "product_name": "Test Widget"}],
        "extensions": [],
    }

    sync_airtable._log_purge(purged, local_mode=False)

    log_path = tmp_path / "purge_log.jsonl"
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = _json.loads(lines[0])
    assert entry["products_count"] == 1
    assert entry["extensions_count"] == 0
    assert entry["purged"] == purged
    assert entry["mode"] == "live"
    assert "ts" in entry


def test_log_purge_appends_across_multiple_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_airtable, "DATA_RAW", tmp_path)
    sync_airtable._log_purge(
        {"products": [{"product_id": "a", "product_name": "A"}], "extensions": []},
        local_mode=False,
    )
    sync_airtable._log_purge(
        {"products": [], "extensions": [{"extension_id": "b", "base_model_id": "bm", "base_model_name": "B", "orphaned_active_product": False}]},
        local_mode=True,
    )

    lines = (tmp_path / "purge_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
