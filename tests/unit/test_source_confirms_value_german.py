r"""Unit tests for source_confirms_value — German locale and edge cases (U-G-xx).

Documents the current state of German-locale number handling in source_confirms_value
from src/json_repair.py.

As of 2026-06-04: German decimal comma handling was FIXED by the _interpret_number_token
refactor (OI-30). Negative value confirmation was FIXED by the abs(v) approach — the
regex still only captures digits (no leading '-'), but comparing abs(value) against the
positive number tokens in the source is sufficient for the source-span guard's purpose.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from src.json_repair import source_confirms_value


# ---------------------------------------------------------------------------
# U-G-01: German decimal comma — 3.4 in "Regalbreite 3,4 m"
# Fixed by OI-30 _interpret_number_token refactor.
# ---------------------------------------------------------------------------

def test_U_G_01_german_decimal_comma_3_4():
    """German '3,4' in source text must confirm float value 3.4.

    This is the Nordlicht aisle-width case: document contains 'Regalbreite
    (Gassenbreite) 3,4 m'. Layer 2 must not null the correctly extracted 3.4.

    Bug was present before OI-30 fix; now passing. Test is kept as a
    regression anchor so the fix is never reverted.
    """
    assert source_confirms_value(3.4, "Regalbreite 3,4 m") is True, (
        "German decimal comma '3,4' must confirm value 3.4 — OI-30 regression"
    )


# ---------------------------------------------------------------------------
# U-G-02: German decimal comma — 1.9 in aisle context
# ---------------------------------------------------------------------------

def test_U_G_02_german_decimal_comma_1_9_aisle():
    """German '1,9' in source text must confirm float value 1.9.

    Represents a minimum aisle width expressed in German decimal notation.
    """
    assert source_confirms_value(
        1.9, "Mindestgangbreite 1,9 m (Palette-zu-Palette)"
    ) is True, (
        "German decimal comma '1,9' must confirm value 1.9 — OI-30 regression"
    )


# ---------------------------------------------------------------------------
# U-G-03: German thousands separator (period) — 1.000 kg
# ---------------------------------------------------------------------------

def test_U_G_03_german_thousands_period_1000():
    """German period-as-thousands '1.000' in source text must confirm 1000.0.

    Common pattern in German tender documents: payload in 'Traglast 1.000 kg'.
    """
    assert source_confirms_value(1000.0, "Traglast 1.000 kg") is True, (
        "German thousands separator '1.000' must confirm value 1000.0"
    )


# ---------------------------------------------------------------------------
# U-G-04: Negative value — fixed by abs(v) approach
# ---------------------------------------------------------------------------

def test_U_G_04_negative_value_in_source():
    """Negative value -25.0 must be confirmed by 'Betriebstemperatur -25°C bis +40°C'.

    Fixed: source_confirms_value now uses abs(v) so -25.0 matches the token '25'
    found in the source text. Regression anchor for the abs(v) fix.
    """
    assert source_confirms_value(-25.0, "Betriebstemperatur -25°C bis +40°C") is True
