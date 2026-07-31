"""Unit tests for source_is_grounded() (U-SG-xx) — src/json_repair.py.

source_is_grounded(value, source, document) answers a different question than
source_confirms_value(): the latter only checks internal consistency between
a value and the LLM's own self-reported quote (trivially satisfied by a
self-consistent fabrication); this checks whether that quote is actually
grounded in the real document text.

Every case here is a real value/quote/document triple captured from the
tender corpus during the 2026-06-16 source-grounding investigation (Nordlicht,
Dragonfly, Mama, CompanyX — OeA-199-25 has no AGV numeric fields), not a
synthetic string. See .claude/agent-memory/senior-architect/
decision_grounding_binary_anchor.md for the corpus-level research this is
derived from.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import _NUMERIC_KO_TENDER_KEYS, _NUMERIC_KO_FIELD_UNITS
from src.json_repair import source_is_grounded, enforce_source_spans, _METRIC_PREFIX_SCALE

_TENDERS = Path(__file__).parent.parent.parent / "tenders"


def _pdf_text(filename: str) -> str:
    import pdfplumber

    with pdfplumber.open(_TENDERS / filename) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


# ---------------------------------------------------------------------------
# Genuine values must survive — across paraphrase, verbatim quoting, German
# decimal commas, ×1000 unit-scale mismatch, and PDF font/glyph noise.
# ---------------------------------------------------------------------------

def test_U_SG_01_genuine_verbatim_quote_dragonfly_weight():
    """Dragonfly: quote copies the document almost verbatim."""
    document = "Max Loaded weight (KG) (Footprint) 1000"
    quote = "Max Loaded weight (KG) (Footprint) 1000"
    assert source_is_grounded(1000, quote, document) is True


def test_U_SG_02_genuine_paraphrased_quote_companyx_weight():
    """CompanyX: quote paraphrases the document in different words.

    Real doc: 'Most pallet weights are less than 500 kg, with a maximum of
    1,000 kg.' Model's actual quote: 'The maximum loaded weight of the AGVs
    is up to 1,000 kg.' Shares 'maximum'/'1,000'/'kg', not the sentence.
    """
    document = "Most pallet weights are less than 500 kg, with a maximum of 1,000 kg."
    quote = "The maximum loaded weight of the AGVs is up to 1,000 kg."
    assert source_is_grounded(1000, quote, document) is True


def test_U_SG_03_genuine_german_decimal_comma_nordlicht_aisle():
    """Nordlicht: 'Regalbreite (Gassenbreite) 3,4 m' — German comma decimal."""
    document = "Regalbreite (Gassenbreite) 3,4 m\nLagerhöhe 10 m"
    quote = "Regalbreite (Gassenbreite) 3,4 m"
    assert source_is_grounded(3.4, quote, document) is True


def test_U_SG_04_genuine_unit_scale_mismatch_dragonfly_aisle():
    """Dragonfly: tender_key is in meters (2.0), document states mm (2000)."""
    document = "Aisle width is 2000 mm rack-to-rack, with a minimum of 1900 mm pallet-to-pallet."
    quote = document
    assert source_is_grounded(2.0, quote, document) is True


def test_U_SG_05_genuine_pdf_glyph_artifact_mama_temp_min():
    """Mama: real pdfplumber extraction inserts a private-use-area glyph
    (U+E088) where the source PDF had an en-dash: 'ranging from
    10\\ue08830°C'. The model's own quote uses a normal hyphen. Both
    numbers must still ground independently.
    """
    document = "ambient temperatures ranging from 1030°C\nindoors."
    quote = "The AGVS must be able to operate in ambient temperatures ranging from 10-30°C indoors."
    assert source_is_grounded(10, quote, document) is True
    assert source_is_grounded(30, quote, document) is True


def test_U_SG_06_genuine_mama_weight_with_pua_bullet_glyphs():
    """Mama: real document text around the weight value contains private-use
    bullet glyphs (U+E09F) between pallet dimensions — must not interfere
    with anchoring the unrelated weight number on the line above.
    """
    document = (
        "The AGV must handle three different pallet sizes with a maximum load of 2000 kg:\n"
        "● 8001200\n● 10001200\n● 12001200"
    )
    quote = "The AGV must handle three different pallet sizes with a maximum load of 2000 kg"
    assert source_is_grounded(2000, quote, document) is True


# ---------------------------------------------------------------------------
# Fabricated values must be rejected — all 7 from the real CompanyX
# hallucination, individually, against the real 17.9k-char document text.
# ---------------------------------------------------------------------------

def test_U_SG_07_fabricated_companyx_values_all_rejected():
    """All 7 fabricated CompanyX numeric KO values, each with its own
    plausible-sounding fabricated quote, must fail grounding against the
    real document — this is the regression case for the whole guard.
    """
    document = _pdf_text("CompanyX.pdf")
    fabrications = [
        (4.8, "The maximum lift height of the AGVs is up to 4.8 m."),
        (-25, "The operating temperature range for the AGVs is from -25 °C to +40 °C."),
        (40, "The operating temperature range for the AGVs is from -25 °C to +40 °C."),
        (95, "The maximum relative humidity the AGVs must tolerate is 95%."),
        (10, "The maximum gradeability of the loaded unit is up to 10 %."),
        (2500, "The lowest overall vehicle height (mast collapsed) is 2,500 mm."),
        (3.6, "The minimum working aisle width available in the facility is 3.6 m."),
    ]
    failures = [
        value for value, quote in fabrications if source_is_grounded(value, quote, document)
    ]
    assert not failures, f"these fabricated values incorrectly passed grounding: {failures}"


def test_U_SG_08_number_present_but_no_colocated_context_companyx_temp_max():
    """The temp_max=40 fabrication is the 'number present, zero shared words'
    case from the corpus research: '40' genuinely occurs in the real CompanyX
    document (in an unrelated shelf/transfer-point table), but none of the
    fabricated quote's content words appear near any of those occurrences.
    Anchor-only would false-accept this; co-location correctly rejects it.
    """
    document = _pdf_text("CompanyX.pdf")
    assert "40" in document, "test assumption: '40' must genuinely occur in the document"
    quote = "The operating temperature range for the AGVs is from -25 °C to +40 °C."
    assert source_is_grounded(40, quote, document) is False


def test_U_SG_09_number_absent_entirely_companyx_lift_height():
    """The lift-height fabrication is the dominant failure mode: the value's
    digit-string (4.8, and its x1000/x0.001 variants) does not occur in the
    real document at all.
    """
    document = _pdf_text("CompanyX.pdf")
    assert "4.8" not in document and "4,8" not in document
    quote = "The maximum lift height of the AGVs is up to 4.8 m."
    assert source_is_grounded(4.8, quote, document) is False


# ---------------------------------------------------------------------------
# Structural edge cases
# ---------------------------------------------------------------------------

def test_U_SG_10_zero_always_grounded():
    """LL-06 (Blank != Zero): a deliberate zero is never treated as ungrounded,
    regardless of source/document content.
    """
    assert source_is_grounded(0, "", "") is True
    assert source_is_grounded(0, "no lifting required", "completely unrelated text") is True


def test_U_SG_11_empty_source_not_grounded():
    """An empty or missing source can never be grounded (this is also caught
    earlier by Layer 1 in enforce_source_spans, but source_is_grounded itself
    must be defensive too).
    """
    assert source_is_grounded(1000, "", "a maximum of 1,000 kg") is False
    assert source_is_grounded(1000, None, "a maximum of 1,000 kg") is False


def test_U_SG_12_non_numeric_value_passes_through():
    """Non-numeric values (e.g. a categorical field accidentally routed
    through this numeric-only guard) must not raise — defined as trivially
    grounded since the anchor/co-location logic does not apply to them.
    """
    assert source_is_grounded("Forklift AGV", "some quote", "some document") is True


def test_U_SG_13_single_digit_anchor_substring_colocation_rejected():
    """OI-83 regression: LLM hallucinated lifting_height_mm=3.0 with source
    'The AGVs must be able to lift pallets up to a height of 3 meters.'
    The digit '3' appears in 'Hall 3' in the document; 'lift' in the source
    matched as substring inside 'forklift' in the window around 'Hall 3'.
    After the word-boundary co-location fix, 'lift' must not match 'forklift'.
    """
    document = _pdf_text("CompanyX.pdf")
    assert "3" in document, "test assumption: single digit '3' must appear in document"
    quote = "The AGVs must be able to lift pallets up to a height of 3 meters."
    assert source_is_grounded(3.0, quote, document) is False, (
        "lifting_height=3.0 must be rejected: fabricated source not grounded "
        "(word 'lift' must not match as substring of 'forklift')"
    )


def test_U_SG_14_single_digit_anchor_aisle_width_rejected():
    """OI-83 regression: LLM hallucinated min_aisle_width_mm=2.0 with source
    'The minimum working aisle width available in the facility is 2 meters.'
    The digit '2' appears many times in the document (data tables).
    After the word-boundary co-location fix, co-location must not produce
    a false positive from incidental table values.
    """
    document = _pdf_text("CompanyX.pdf")
    assert "2" in document, "test assumption: digit '2' must appear in document"
    quote = "The minimum working aisle width available in the facility is 2 meters."
    assert source_is_grounded(2.0, quote, document) is False, (
        "min_aisle_width=2.0 must be rejected: fabricated source not grounded"
    )


# ---------------------------------------------------------------------------
# Metric-prefix unit-gated anchor (D2 residual-risk fix, 2026-07-31).
#
# Background: the converted-scale target family ({value*1000, value/1000}) used
# to anchor unconditionally, with no check on WHAT the matched document number
# actually meant. For a round value like 10000, the target set includes a bare
# 10 — which anchors against almost any document (e.g. an unrelated "10 years"
# clause, or an unrelated "mm 10" table cell). This was predicted over a month
# ago as an accepted, monitored residual risk in test_U_SS_11 (see
# tests/unit/test_source_span_enforcement.py:227), whose docstring says
# "if this starts failing... needs a real fix, not a threshold nudge" — that
# risk materialized on the real Dragonfly tender's required_lifting_height_mm
# field (captured tests/tenders/run_20260730_dragonfly.json, before the
# separately-shipped user_description prompt fix in commit 685b492 already
# resolved the acute symptom for that specific tender run). This section is
# the real fix test_U_SS_11 anticipated: the converted-scale anchor now only
# counts if a metric-prefix unit token sits adjacent to the matched document
# number AND that unit dimensionally resolves to the same real-world quantity
# as `value` under the field's actual AP0 unit.
# ---------------------------------------------------------------------------

def test_U_SG_15_dragonfly_fabricated_lifting_height_rejected_after_fix():
    """The actual historical regression: required_lifting_height_mm=10000
    (Pass 4c/4b's raw pre-mm-to-m-conversion value; enforce_source_spans() runs
    before validate_domain_criteria()'s mm->m auto-conversion, so this is the
    value source_is_grounded() actually saw — the final persisted value in
    run_20260730_dragonfly.json is 10.0, i.e. 10000 * 0.001) with fabricated
    source "Lift height: 10,000 mm" — captured verbatim from
    tests/tenders/run_20260730_dragonfly.json. The real Dragonfly.pdf contains
    no "lift"/"Lift" text at all and no genuine lift-height figure; the only
    reason this fabrication passed grounding before this fix is a coincidental
    "10" collision (pallet-deflection table cells "width mm 10" / "length mm
    10", and an unrelated "10 years" clause) plus the word "height" from an
    unrelated "pallet height" line sitting nearby. Before this fix this
    asserted True (confirmed empirically during implementation); after this
    fix it must be False.
    """
    document = _pdf_text("Dragonfly.pdf")
    assert "Lift" not in document and "lift" not in document, (
        "test assumption: the real Dragonfly document contains no lift-height text at all"
    )
    assert source_is_grounded(
        10000, "Lift height: 10,000 mm", document, unit="m"
    ) is False


def test_U_SG_16_dragonfly_second_fabricated_lifting_height_variant_rejected():
    """A second real Dragonfly fabrication for the same field, captured from
    tests/tenders/run_20260729_dragonfly.json ("Lift height: 12 m", value
    12000 mm-scale pre-conversion). This one was already correctly rejected
    before this fix (no "12"/"12,000"/"12000" anchor at all in the real
    document) — included alongside U_SG_15 for corpus completeness, not
    because it demonstrates new gating behavior.
    """
    document = _pdf_text("Dragonfly.pdf")
    assert source_is_grounded(
        12000, "Lift height: 12 m", document, unit="m"
    ) is False


def test_U_SG_17_nordlicht_genuine_lifting_height_survives_metric_gate():
    """The genuine counterpart the fix must preserve: a real height figure
    "Höhe 10 m" appears in the real Nordlicht PDF text (warehouse height,
    m·high-bay context: "20.000 m² · Höhe 10 m · Gasse 3,4 m"). A tender
    value of 10000 (pre-conversion mm-scale, same convention as the Dragonfly
    triples above) with a source quoting this real "10 m" text must ground:
    the adjacent unit "m" dimensionally resolves 10 m back to the same
    real-world quantity as value=10000 under unit="m" (10000/1000 == 10).

    Note: the real Nordlicht PDF does not literally contain the word
    "Hubhöhe" (lift height) anywhere — the closest genuine real occurrence of
    a "<number> m" height figure is this warehouse-height line. Used here
    (per this file's real-corpus-only convention) instead of a synthetic
    "Hubhöhe >= 10 m" string.
    """
    document = _pdf_text("Beispielausschreibung_AGV_Nordlicht.pdf")
    assert "Höhe 10 m" in document, "test assumption: real Nordlicht text must contain this figure"
    quote = "Höhe 10 m"
    assert source_is_grounded(10000, quote, document, unit="m") is True


def test_U_SG_18_aisle_width_unit_scale_mismatch_survives_metric_gate_explicit_unit():
    """Re-run of test_U_SG_04 (genuine unit-scale mismatch: value in meters,
    document in mm) but now exercised THROUGH the new metric-prefix gate by
    passing unit="m" explicitly (required_min_aisle_width_mm's real AP0 unit,
    per _NUMERIC_KO_FIELD_UNITS) instead of relying on the unit="" carve-out
    default. Proves the fix does not regress this exact case: document's
    "2000 mm" dimensionally resolves (2000 * 0.001 == 2.0) to the tender
    value 2.0 under unit="m".
    """
    assert _NUMERIC_KO_FIELD_UNITS["required_min_aisle_width_mm"] == "m"
    document = "Aisle width is 2000 mm rack-to-rack, with a minimum of 1900 mm pallet-to-pallet."
    quote = document
    assert source_is_grounded(2.0, quote, document, unit="m") is True


def test_U_SG_19_nonmetric_unit_carveout_converted_scale_still_anchors_unconditionally():
    """Structural pin for the carve-out: for a unit outside
    _METRIC_PREFIX_SCALE (here '%' — required_max_gradient_pct's real AP0
    unit), a x1000/x0.001 converted-scale anchor must keep matching
    unconditionally, exactly as before this fix — the new gate only applies
    to metric-prefix units (mm/cm/m/km/g/kg/t). Synthetic document (not from
    the tender corpus) because this pins the ABSENCE of new gating behavior
    for a non-metric field, not a real hallucination case.
    """
    assert "%" not in _METRIC_PREFIX_SCALE
    document = "The maximum incline the AGV must climb is rated at 10 percent under load."
    quote = document
    # value=0.01 -> converted target av*1000 == 10, matching the document's
    # literal "10". The exact-scale target (0.01 itself) does not occur.
    assert "0.01" not in document and "0,01" not in document
    assert source_is_grounded(0.01, quote, document, unit="%") is True


def test_U_SG_20_wiring_enforce_source_spans_passes_unit_through_end_to_end():
    """Guards against the wiring silently regressing to unit="" (old
    behavior) if a future refactor drops the `unit=units.get(key, "")`
    argument at the enforce_source_spans() call site. Exercises the full
    production function (not source_is_grounded() directly) with the real
    `units` dict (_NUMERIC_KO_FIELD_UNITS, as passed in production by
    app.py:1135) against the real Dragonfly fabrication: with real units,
    Layer 0 must null the value; with an empty units dict (simulating the
    pre-fix/unwired state), the same fabrication must survive Layer 0 —
    proving the unit parameter is what makes the difference, not some other
    coincidental change.
    """
    document = _pdf_text("Dragonfly.pdf")
    key = "required_lifting_height_mm"
    criteria = {key: 10000, f"{key}_source": "Lift height: 10,000 mm"}

    result_wired, _messages, events_wired = enforce_source_spans(
        dict(criteria), document, _NUMERIC_KO_TENDER_KEYS, set(),
        units=_NUMERIC_KO_FIELD_UNITS,
    )
    assert result_wired[key] is None, "with real units wired through, L0 must null the fabrication"
    assert any(ev.layer == "L0" and ev.field == key for ev in events_wired)

    result_unwired, _messages2, _events_unwired = enforce_source_spans(
        dict(criteria), document, _NUMERIC_KO_TENDER_KEYS, set(),
        units={},
    )
    assert result_unwired[key] == 10000, (
        "sanity check: without units, the metric-prefix gate is inactive (carve-out) "
        "and this same fabrication survives L0 — confirms the wired test above is "
        "actually exercising the new gate, not some unrelated change"
    )


def test_U_SG_21_numeric_ko_field_units_coverage_survives_dash_o():
    """app.py has a hard `assert` (lines ~188-195) that _NUMERIC_KO_FIELD_UNITS
    is non-empty and covers every _NUMERIC_KO_TENDER_KEYS entry with a truthy
    unit — but `assert` is stripped under Python's -O flag. This pytest-based
    test independently re-verifies the same invariant so a -O deployment
    cannot silently lose unit coverage (and therefore silently lose this
    fix's gating for every numeric KO field).
    """
    assert _NUMERIC_KO_FIELD_UNITS, "_NUMERIC_KO_FIELD_UNITS must not be empty"
    for tk in _NUMERIC_KO_TENDER_KEYS:
        assert tk in _NUMERIC_KO_FIELD_UNITS and _NUMERIC_KO_FIELD_UNITS[tk], (
            f"numeric KO field {tk!r} has no truthy unit in _NUMERIC_KO_FIELD_UNITS — "
            "the metric-prefix gate can never activate for it"
        )
