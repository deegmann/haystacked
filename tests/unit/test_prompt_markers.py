"""Unit tests for src/prompt_markers.py — field-agnostic NULL RULE marker handling."""
from __future__ import annotations

from src.prompt_markers import strip_null_rule
from src.field_spec import fields_by_tender_key


def test_strip_null_rule_colon_variant():
    hint = "Field meaning here. NULL RULE: null by default. Do NOT supply a default."
    assert strip_null_rule(hint) == "Field meaning here."


def test_strip_null_rule_em_dash_read_first_variant():
    hint = "Field meaning here. NULL RULE — READ FIRST: null by default. Do NOT supply a default."
    assert strip_null_rule(hint) == "Field meaning here."


def test_strip_null_rule_no_marker_passthrough():
    hint = "  Field meaning with no null rule marker at all.  "
    assert strip_null_rule(hint) == "Field meaning with no null rule marker at all."


def test_strip_null_rule_bound_not_exceeded():
    # 41 non-colon characters between "NULL RULE" and the colon — must NOT match,
    # the {0,40} bound is deliberate so an unrelated later sentence isn't swallowed.
    filler = "x" * 41
    hint = f"Field meaning here. NULL RULE {filler}: trailing text."
    assert strip_null_rule(hint) == hint.strip()


_NULL_BIAS_PHRASES = (
    "Do NOT supply",
    "output null",
    "null by default",
)


def _hint_for(tender_key: str) -> str:
    fields = fields_by_tender_key()[tender_key]
    assert len(fields) == 1, f"expected exactly one scoped field for {tender_key}, got {len(fields)}"
    return fields[0].hint


def test_strip_null_rule_preserves_source_and_bound_temp_min():
    stripped = strip_null_rule(_hint_for("required_operating_temp_min_c"))
    assert "Source: a temperature range or operating condition" in stripped
    assert "this field holds the lower bound (X)" in stripped
    for phrase in _NULL_BIAS_PHRASES:
        assert phrase not in stripped


def test_strip_null_rule_preserves_source_and_bound_temp_max():
    stripped = strip_null_rule(_hint_for("required_operating_temp_max_c"))
    assert "Source: a temperature range or operating condition" in stripped
    assert "this field holds the upper bound (Y)" in stripped
    for phrase in _NULL_BIAS_PHRASES:
        assert phrase not in stripped


def test_strip_null_rule_preserves_source_humidity():
    stripped = strip_null_rule(_hint_for("required_operating_humidity_max_pct"))
    assert "Source: an explicit relative-humidity % figure in the environment specification" in stripped
    for phrase in _NULL_BIAS_PHRASES:
        assert phrase not in stripped


def test_strip_null_rule_preserves_default_resolution_fork_option():
    stripped = strip_null_rule(_hint_for("required_special_fork_option"))
    assert "Standard forks are the default for all forklifts" in stripped
    assert "Rotating forks are the default for VNA/narrow-aisle turret trucks" in stripped
    for phrase in _NULL_BIAS_PHRASES:
        assert phrase not in stripped
