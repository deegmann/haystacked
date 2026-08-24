"""Unit tests for data_loader parsing helpers (U-D-01 to U-D-16) and DB integrity."""
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.data_loader import DB_PATH, _parse_bool, _parse_float, _parse_int, _parse_multiselect


def test_U_D_01_multiselect_pipe_separated():
    result = _parse_multiselect("Laser|Natural Feature")
    assert result == ["Laser", "Natural Feature"]


def test_U_D_02_multiselect_empty_string():
    assert _parse_multiselect("") == []


def test_U_D_03_multiselect_none():
    assert _parse_multiselect(None) == []


def test_U_D_04_bool_1_true():
    assert _parse_bool(1) is True


def test_U_D_05_bool_0_false():
    assert _parse_bool(0) is False


def test_U_D_06_bool_none():
    assert _parse_bool(None) is None


def test_U_D_07_reference_count_empty_is_none():
    assert _parse_int("") is None
    assert _parse_int(None) is None


def test_U_D_08_payload_empty_is_none():
    assert _parse_float("") is None
    assert _parse_float(None) is None


def test_U_D_09_uuid_format():
    test_uuid = str(uuid.uuid4())
    import re
    pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
    )
    assert pattern.match(test_uuid)


def test_U_D_16_multiselect_with_embedded_comma():
    # Pipe is the separator, embedded commas in values are fine
    result = _parse_multiselect("ISO 3691-4|ISO 13849, PLd")
    assert "ISO 3691-4" in result
    assert "ISO 13849, PLd" in result


def test_multiselect_whitespace_trimmed():
    result = _parse_multiselect(" Laser | Natural Feature ")
    assert result == ["Laser", "Natural Feature"]


def test_bool_string_true():
    assert _parse_bool("true") is True
    assert _parse_bool("True") is True
    assert _parse_bool("1") is True


def test_bool_string_false():
    assert _parse_bool("false") is False
    assert _parse_bool("False") is False
    assert _parse_bool("0") is False


def test_int_parses_float_string():
    assert _parse_int("1500.0") == 1500


def test_float_nan_is_none():
    assert _parse_float(float("nan")) is None


# ── DB integrity (U-D-DB-01 / U-D-DB-02) ─────────────────────────────────────

def test_U_D_DB_01_no_active_products_without_product_id():
    """Every active product must have a non-null product_id.

    Fails red when import scripts are run without a subsequent sync_airtable.py,
    making the affected products invisible to matching with no other signal.
    Fix: run  python3 sync_airtable.py
    """
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT product_name FROM products "
        "WHERE active = 1 AND (product_id IS NULL OR product_id = '')"
    ).fetchall()
    con.close()
    missing = [r[0] for r in rows]
    assert not missing, (
        f"{len(missing)} active product(s) have no product_id and are silently "
        f"excluded from matching — run sync_airtable.py to fix: {missing}"
    )


def test_U_D_DB_02_no_duplicate_extensions_per_base_model():
    """Every base_model_id referenced by an active product must resolve to
    exactly one base_model_extensions row.

    JOIN_SQL (src/data_loader.py) joins products to base_model_extensions on
    base_model_id, not product_id — product_id is a TEXT PRIMARY KEY and can
    never duplicate, so grouping on it (an earlier version of this test)
    always passes even when the real fan-out condition is present.

    IMPORTANT (fixed 2026-08-24, OEM-rebadge false positive): this must count
    rows directly in base_model_extensions, NOT via a join through products.
    A base_model legitimately has multiple products by design (the OEM-rebadge
    pattern, e.g. Magazino "SOTO" and "Jungheinrich SOTO" sharing one base
    model) — joining products to extensions and grouping on base_model_id
    fans out to N rows for N legitimate sibling products sharing one real
    extension row, which an earlier version of this test misread as N
    duplicate extensions. The actual danger case this test guards against is
    a base_model with >1 EXTENSION row (ambiguous which one data_loader's
    JOIN picks first) — a property of base_model_extensions itself, entirely
    independent of how many products point at that base_model.
    Fix if this ever fires for real: remove the duplicate extension record in
    Airtable, then run sync_airtable.py.
    """
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT bme.base_model_id, COUNT(*) as cnt "
        "FROM base_model_extensions bme "
        "WHERE bme.base_model_id IN ("
        "    SELECT DISTINCT base_model_id FROM products "
        "    WHERE active = 1 AND product_id IS NOT NULL"
        ") "
        "GROUP BY bme.base_model_id HAVING cnt > 1"
    ).fetchall()
    con.close()
    dupes = {r[0]: r[1] for r in rows}
    assert not dupes, (
        f"base_model_id(s) with multiple extension rows (base_model_id → count): {dupes}. "
        "Remove the duplicate extension record in Airtable, then run sync_airtable.py."
    )
