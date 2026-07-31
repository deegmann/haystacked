"""Guardrail test for scripts/generate_all.py's validate_no_unit_in_field_name()
(OI-115c Phase 3F) — hard assert that a field_name never encodes its own unit.

Exercises the real function directly against synthetic fixtures and against
the real generated config/fields.json, without constructing a fake openpyxl
workbook — no precedent for that exists in this test suite (see
test_generate_all_operator_direction_guardrail.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).parent.parent.parent


def _load_generate_all():
    sys.path.insert(0, str(BASE_DIR))
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    import generate_all
    return generate_all


def test_rejects_synthetic_unit_suffixed_field_name():
    generate_all = _load_generate_all()
    with pytest.raises(SystemExit):
        generate_all.validate_no_unit_in_field_name(
            {"uuid-1": {"field_name": "foo_mm"}}
        )


def test_rejects_infix_unit_token():
    """Catches unit tokens anywhere in the field_name, not just trailing
    suffixes — the historical example this guards against is
    'room_volume_m3_max' (unit token 'm3' in infix position)."""
    generate_all = _load_generate_all()
    with pytest.raises(SystemExit):
        generate_all.validate_no_unit_in_field_name(
            {"uuid-1": {"field_name": "room_volume_m3_max"}}
        )


def test_silent_on_clean_field_name():
    generate_all = _load_generate_all()
    generate_all.validate_no_unit_in_field_name(
        {"uuid-1": {"field_name": "max_payload"}}
    )


def test_silent_on_allowlisted_field_names():
    generate_all = _load_generate_all()
    for fn in generate_all._NO_UNIT_SUFFIX_ALLOWLIST:
        generate_all.validate_no_unit_in_field_name(
            {"uuid-1": {"field_name": fn}}
        )


def test_passes_cleanly_against_real_generated_fields_json():
    """Regression guard for the OI-115c Phase 3C rename: the real generated
    config/fields.json must never trip this assertion."""
    generate_all = _load_generate_all()
    fields = json.loads((BASE_DIR / "config" / "fields.json").read_text())
    generate_all.validate_no_unit_in_field_name(fields)
