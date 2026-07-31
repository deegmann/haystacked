"""Guardrail test for scripts/generate_all.py's operator-direction duplication
assertion (D6 hygiene fix).

Exercises generate_all.py's own `_check_operator_direction_duplication()` helper
(called from emit_fields_json's per-row loop) against synthetic fixtures, without
constructing a fake openpyxl workbook — no precedent for that exists in this
test suite, and the helper is a pure function of (field_name, hint, op, dtype)
so it can be imported and called directly.
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


def test_check_operator_direction_duplication_rejects_ko_if_lt_duplicate():
    generate_all = _load_generate_all()
    sentence = generate_all._OPERATOR_DIRECTION["KO_IF_LT"]
    bad_hint = f"Field meaning. NULL RULE: null by default. {sentence}"
    with pytest.raises(SystemExit):
        generate_all._check_operator_direction_duplication(
            "offending_field", bad_hint, "KO_IF_LT", "Float"
        )


def test_check_operator_direction_duplication_rejects_ko_if_gt_duplicate():
    generate_all = _load_generate_all()
    sentence = generate_all._OPERATOR_DIRECTION["KO_IF_GT"]
    bad_hint = f"Field meaning. NULL RULE: null by default. {sentence}"
    with pytest.raises(SystemExit):
        generate_all._check_operator_direction_duplication(
            "offending_field", bad_hint, "KO_IF_GT", "Integer"
        )


def test_check_operator_direction_duplication_silent_on_clean_hint():
    generate_all = _load_generate_all()
    clean_hint = "Field meaning. NULL RULE: null by default."
    generate_all._check_operator_direction_duplication(
        "some_field", clean_hint, "KO_IF_LT", "Float"
    )


def test_check_operator_direction_duplication_silent_on_non_numeric_dtype():
    generate_all = _load_generate_all()
    sentence = generate_all._OPERATOR_DIRECTION["KO_IF_LT"]
    hint_with_sentence = f"Field meaning. {sentence}"
    generate_all._check_operator_direction_duplication(
        "some_field", hint_with_sentence, "KO_IF_LT", "Dropdown"
    )


def test_check_operator_direction_duplication_silent_on_non_directional_op():
    generate_all = _load_generate_all()
    sentence = generate_all._OPERATOR_DIRECTION["KO_IF_LT"]
    hint_with_sentence = f"Field meaning. {sentence}"
    generate_all._check_operator_direction_duplication(
        "some_field", hint_with_sentence, "KO_BOOL_REQUIRED", "Float"
    )


def test_check_operator_direction_duplication_silent_on_real_ap0_content():
    """Regression guard for the actual D6 fix: max_payload's real hint,
    post-fix, must not trip the assertion."""
    generate_all = _load_generate_all()
    from src.field_spec import load_fields

    fields = load_fields()
    max_payload = next(
        f for f in fields.values() if f.field_name == "max_payload"
    )
    generate_all._check_operator_direction_duplication(
        max_payload.field_name,
        max_payload.hint,
        max_payload.operator,
        max_payload.data_type,
    )
