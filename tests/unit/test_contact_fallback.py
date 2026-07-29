"""Tests for OI-98: contact-fallback field sets derived from AP0 platform_config.xlsx.

_CONTACT_FALLBACK_TRIGGER / _CONTACT_FALLBACK_TARGET (app.py) are built from the
"Contact Fallback" column of the Basic Extraction Schema tab, not hardcoded.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

import app as _app_module


def test_contact_fallback_trigger_set():
    """TRIGGER set must be exactly the fields flagged 'trigger' in AP0."""
    assert _app_module._CONTACT_FALLBACK_TRIGGER == frozenset(
        {"contact_name", "contact_email", "contact_phone"}
    )


def test_contact_fallback_target_set():
    """TARGET set must include all TRIGGER fields plus the 'target'-only fields."""
    assert _app_module._CONTACT_FALLBACK_TARGET == frozenset(
        {"contact_name", "contact_email", "contact_phone", "deadline", "tender_date"}
    )


def test_contact_fallback_trigger_is_subset_of_target():
    """Invariant: every trigger field is always also a target field."""
    assert _app_module._CONTACT_FALLBACK_TRIGGER <= _app_module._CONTACT_FALLBACK_TARGET
