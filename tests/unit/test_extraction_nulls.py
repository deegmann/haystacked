"""
U-E-xx — Post-LLM validation unit tests.

No live Ollama required. These tests cover the deterministic code that runs
AFTER the LLM returns but BEFORE matching:
  - validate_domain_criteria(): plausibility filter that must not coerce nulls
  - source_confirms_value(): Layer 2 digit-in-source numeric guard
  - _NUMERIC_KO_TENDER_KEYS: module-level constant populated from config

To test actual LLM extraction outputs against golden files, see
test_golden_extraction.py and scripts/capture_pipeline_run.py.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ---------------------------------------------------------------------------
# U-E-05: null values survive validate_domain_criteria unchanged
# ---------------------------------------------------------------------------

def test_U_E_05_null_lift_height_survives_plausibility_filter():
    """
    A null required_lifting_height must pass through validate_domain_criteria
    unchanged — the plausibility filter must not coerce null to a default value.

    This verifies LL-06 (Blank ≠ Zero) is upheld in the post-LLM validation step.
    """
    from app import validate_domain_criteria

    criteria = {
        "required_product_type": "Forklift AGV",
        "required_lifting_height": None,
        "required_min_aisle_width": 1900,
        "required_max_payload": 1000,
    }
    validated, warnings = validate_domain_criteria(criteria)
    assert validated.get("required_lifting_height") is None, (
        "validate_domain_criteria must not fill a null required_lifting_height "
        "with a default value (LL-06: Blank ≠ Zero)."
    )


# ---------------------------------------------------------------------------
# U-E-06: _source_confirms_value boundary conditions
# ---------------------------------------------------------------------------

def test_U_E_06_source_confirms_value():
    """
    source_confirms_value must correctly gate Layer 2 source-span enforcement.

    Covers: direct match, mm/m scale (×1000), thousands separator, false positive.
    """
    from src.json_repair import source_confirms_value

    # Direct numeric match
    assert source_confirms_value(1000, "Max Loaded weight (KG) (Footprint) 1000") is True

    # Thousands separator: "1,000" must be read as 1000
    assert source_confirms_value(1000, "a maximum of 1,000 kg") is True

    # mm/m scale: value 1.9 m → look for 1900 in source
    assert source_confirms_value(1.9, "minimum of 1900 mm pallet-to-pallet") is True

    # mm/m scale: value 2.0 m → look for 2000 in source
    assert source_confirms_value(2.0, "aisle width is 2000 mm rack-to-rack") is True

    # False positive guard: source "Outbound 1734 / Replenishment 133" must NOT
    # confirm value 6.0 (the Dragonfly lift-height hallucination)
    assert source_confirms_value(6.0, "Outbound 1734\nReplenishment (also halfs) 133") is False

    # Zero always passes (deliberate zero, not an inference hallucination)
    assert source_confirms_value(0, "no lifting required") is True


# ---------------------------------------------------------------------------
# U-E-07: _NUMERIC_KO_TENDER_KEYS non-empty guard
# ---------------------------------------------------------------------------

def test_U_E_07_numeric_ko_tender_keys_non_empty():
    """
    _NUMERIC_KO_TENDER_KEYS must be non-empty after loading fields.json.

    If empty, source-span enforcement and Pass 4c are silently inactive.
    This test catches a missing or stale fields.json before a run.
    """
    from app import _NUMERIC_KO_TENDER_KEYS

    assert len(_NUMERIC_KO_TENDER_KEYS) > 0, (
        "_NUMERIC_KO_TENDER_KEYS is empty — fields.json may be missing or "
        "has no KO_IF_LT/KO_IF_GT Float/Integer fields. Run generate_all.py."
    )
    assert "required_max_payload" in _NUMERIC_KO_TENDER_KEYS, (
        "required_max_payload missing from _NUMERIC_KO_TENDER_KEYS — "
        "check fields.json tender_key mapping for max_payload."
    )
    assert "required_lifting_height" in _NUMERIC_KO_TENDER_KEYS, (
        "required_lifting_height missing from _NUMERIC_KO_TENDER_KEYS."
    )
