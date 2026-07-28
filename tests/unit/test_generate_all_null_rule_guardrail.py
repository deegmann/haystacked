"""Guardrail test for scripts/generate_all.py's NULL RULE marker assertion (OI-109 D2).

Exercises generate_all.py's own `_check_null_rule_marker()` helper (called from
emit_fields_json's per-row loop) against synthetic bad-marker fixtures, without
constructing a fake openpyxl workbook — no precedent for that exists in this
test suite, and the helper is a pure function of (field_name, hint) so it can
be imported and called directly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).parent.parent.parent


def _load_generate_all():
    sys.path.insert(0, str(BASE_DIR))
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    import generate_all
    return generate_all


def test_check_null_rule_marker_accepts_canonical_colon_variant():
    generate_all = _load_generate_all()
    generate_all._check_null_rule_marker("some_field", "Field meaning. NULL RULE: null by default.")


def test_check_null_rule_marker_accepts_canonical_em_dash_variant():
    generate_all = _load_generate_all()
    generate_all._check_null_rule_marker("some_field", "Field meaning. NULL RULE — READ FIRST: null by default.")


def test_check_null_rule_marker_accepts_hint_without_marker():
    generate_all = _load_generate_all()
    generate_all._check_null_rule_marker("some_field", "Field meaning with no marker at all.")


@pytest.mark.parametrize("bad_hint", [
    # "NULL RULE" present, but no colon within the deliberate 40-char bound.
    "Field meaning. NULL RULE without any colon at all in this sentence.",
    # "NULL RULE" present, but the colon is more than 40 chars away — the bound
    # is deliberate so a marker-like phrase can't swallow an unrelated clause.
    "Field meaning. NULL RULE, this thing needs way more than forty characters "
    "before any colon shows up here: null by default.",
])
def test_check_null_rule_marker_rejects_unrecognised_variant(bad_hint):
    generate_all = _load_generate_all()
    with pytest.raises(SystemExit):
        generate_all._check_null_rule_marker("offending_field", bad_hint)
