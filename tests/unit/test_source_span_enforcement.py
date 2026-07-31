"""Unit tests for source-span enforcement logic (U-SS-xx).

Imports the real production function `enforce_source_spans()` from
src/json_repair.py directly — this used to be replicated inline here (a copy
of app.py's loop kept in sync by hand), which is exactly how the Layer 0
grounding gap went undetected: the test exercised a stale copy of the logic,
not the code that actually runs. `enforce_source_spans()` is a pure function
(no async, no I/O) specifically so it can be imported and called directly.

Layer order (first match nulls the value and stops):
  Layer 1: source absent/empty -> null (no citation = inference).
  Layer 0: source present but not grounded in the real document text -> null
    (catches a fabricated value paired with a fabricated-but-self-consistent
    quote; runs unconditionally, not scoped to 4c abstention).
  Layer 2 (4c-abstention only): source's own digits don't numerically confirm
    the value -> null.

Several cases below use real extracted text from the tender PDFs in tenders/
(Dragonfly, CompanyX, Nordlicht, Mama) rather than synthetic strings, captured
during the 2026-06-16 source-grounding investigation.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import _NUMERIC_KO_TENDER_KEYS
from src.json_repair import enforce_source_spans, source_confirms_value, SpanEvent, _messages_from_events


def _apply(criteria: dict, document_text: str, four_c_abstained: set = frozenset()) -> dict:
    """Thin call-site adapter — not a reimplementation. Discards the messages
    list (app.py turns those into SSE events; tests only need the resulting dict).
    """
    result, _messages, _events = enforce_source_spans(
        dict(criteria), document_text, _NUMERIC_KO_TENDER_KEYS, set(four_c_abstained)
    )
    return result


# ---------------------------------------------------------------------------
# U-SS-01: L1 — value set + source is None → value becomes None
# ---------------------------------------------------------------------------

def test_U_SS_01_l1_source_none_nulls_value():
    """Layer 1: if the source field is None, the value must be nulled.

    No citation = LLM inference. Layer 1 enforces that every numeric KO value
    must have an explicit source string. Fires before Layer 0 ever needs a
    document, so the document text is irrelevant here.
    """
    key = "required_max_payload"
    criteria = {key: 1000, f"{key}_source": None}
    result = _apply(criteria, document_text="")
    assert result[key] is None, f"L1: {key}=1000 with source=None must be nulled"


def test_U_SS_02_l1_source_empty_string_nulls_value():
    """Layer 1: an empty-string source is treated the same as None (falsy)."""
    key = "required_max_payload"
    criteria = {key: 1000, f"{key}_source": ""}
    result = _apply(criteria, document_text="")
    assert result[key] is None, f"L1: {key}=1000 with source='' must be nulled"


# ---------------------------------------------------------------------------
# U-SS-03: source present, grounded in the real document → value survives L1+L0
# ---------------------------------------------------------------------------

def test_U_SS_03_l1_source_present_value_unchanged():
    """A non-empty, document-grounded source passes both L1 and L0.

    Real Dragonfly.pdf text: 'Max Loaded weight (KG) (Footprint) 1000'.
    """
    key = "required_max_payload"
    document = "Max Loaded weight (KG) (Footprint) 1000"
    criteria = {key: 1000, f"{key}_source": document}
    result = _apply(criteria, document_text=document)
    assert result[key] == 1000, f"{key}=1000 with a grounded source must remain 1000"


# ---------------------------------------------------------------------------
# U-SS-04..05: Layer 0 — fabricated vs. genuine-but-paraphrased CompanyX pair
# ---------------------------------------------------------------------------

def _companyx_pdf_text() -> str:
    import pdfplumber
    pdf_path = Path(__file__).parent.parent.parent / "tenders" / "CompanyX.pdf"
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def test_U_SS_04_l0_fabricated_value_with_self_consistent_fake_quote_nulls():
    """Layer 0: a fabricated value whose self-reported quote is numerically
    self-consistent (would pass the old source_confirms_value-only guard) but
    whose quote text does not occur anywhere in the real document must be nulled.

    This is the exact CompanyX regression: the model fabricated
    required_lifting_height=4.8 with the plausible quote 'The maximum lift
    height of the AGVs is up to 4.8 m.' — '4.8' never appears in the real
    17.9k-char CompanyX.pdf text.
    """
    key = "required_lifting_height"
    fabricated_quote = "The maximum lift height of the AGVs is up to 4.8 m."
    criteria = {key: 4.8, f"{key}_source": fabricated_quote}
    result = _apply(criteria, document_text=_companyx_pdf_text())
    assert result[key] is None, (
        "L0 must null a fabricated value even when its own quote is internally "
        "self-consistent — the quote itself is not grounded in the real document"
    )


def test_U_SS_05_l0_genuine_value_with_paraphrased_quote_survives():
    """Layer 0: a genuine value survives even when the model's quote paraphrases
    the document rather than copying it verbatim.

    Real CompanyX.pdf text: 'Most pallet weights are less than 500 kg, with a
    maximum of 1,000 kg.' The model's actual (genuine) self-reported quote was
    'The maximum loaded weight of the AGVs is up to 1,000 kg.' — different
    words, same number, same topic.
    """
    key = "required_max_payload"
    paraphrased_quote = "The maximum loaded weight of the AGVs is up to 1,000 kg."
    criteria = {key: 1000, f"{key}_source": paraphrased_quote}
    result = _apply(criteria, document_text=_companyx_pdf_text())
    assert result[key] == 1000, (
        "L0 must not null a genuine value just because the model paraphrased "
        "the source instead of quoting it verbatim"
    )


# ---------------------------------------------------------------------------
# U-SS-06: Layer 0 — German decimal comma, real Nordlicht text
# ---------------------------------------------------------------------------

def test_U_SS_06_l0_german_decimal_comma_survives():
    """Layer 0 must handle the German comma-as-decimal-separator convention.

    Real Beispielausschreibung_AGV_Nordlicht.pdf text: 'Regalbreite
    (Gassenbreite) 3,4 m'. The value 3.4 must be recognized as anchored to
    the document's '3,4', not treated as absent because of the locale mismatch.
    """
    key = "required_min_aisle_width"
    document = "Regalbreite (Gassenbreite) 3,4 m\nLagerhöhe 10 m"
    quote = "Regalbreite (Gassenbreite) 3,4 m"
    criteria = {key: 3.4, f"{key}_source": quote}
    result = _apply(criteria, document_text=document)
    assert result[key] == 3.4, "L0 must recognize German decimal comma '3,4' as anchoring 3.4"


# ---------------------------------------------------------------------------
# U-SS-07: Layer 0 — non-standard PDF separator glyph between two numbers
# ---------------------------------------------------------------------------

def test_U_SS_07_l0_pdf_glyph_artifact_does_not_merge_numbers():
    """Real Mama.pdf text extracts the en-dash in '10-30°C' as a private-use-area
    glyph (U+E088), not a normal hyphen: 'ambient temperatures ranging from
    10\\ue08830°C indoors.' This must NOT cause '10' and '30' to merge into a
    single '1030' token — both temperatures must independently ground.
    """
    document = "ambient temperatures ranging from 1030°C\nindoors."
    quote = "The AGVS must be able to operate in ambient temperatures ranging from 10-30°C indoors."

    min_criteria = {"required_operating_temp_min": 10, "required_operating_temp_min_source": quote}
    max_criteria = {"required_operating_temp_max": 30, "required_operating_temp_max_source": quote}

    min_result = _apply(min_criteria, document_text=document)
    max_result = _apply(max_criteria, document_text=document)

    assert min_result["required_operating_temp_min"] == 10, "10 must ground despite the glyph artifact"
    assert max_result["required_operating_temp_max"] == 30, "30 must ground despite the glyph artifact"


# ---------------------------------------------------------------------------
# U-SS-08: Layer 2 — abstained + quote has no parseable digit → nulls
# ---------------------------------------------------------------------------

def test_U_SS_08_l2_abstained_quote_with_no_digits_nulls():
    """Layer 2 specifically: a quote that is grounded (L0 passes — the number
    and descriptive words really do sit together in the document) but whose
    own text never spells the value out in digits at all cannot numerically
    self-confirm. Only fires when 4c also abstained.
    """
    key = "required_lifting_height"
    document = "The mast reaches a height of 6 m when extended, approximately six meters tall in total."
    quote = "approximately six meters tall"
    criteria = {key: 6.0, f"{key}_source": quote}

    result = _apply(criteria, document_text=document, four_c_abstained={key})
    assert result[key] is None, (
        "L2 must null when 4c abstained and the quote contains no digit "
        "confirming the value, even though L0 (grounding) passed"
    )


def test_U_SS_09_l2_not_abstained_keeps_value_despite_no_digit_quote():
    """The same grounded-but-digit-free quote as U-SS-08, but the field is NOT
    in 4c_abstained this time → Layer 2 must not fire, value is kept.
    Isolates that L2 is conditional on abstention while L0 is not.
    """
    key = "required_lifting_height"
    document = "The mast reaches a height of 6 m when extended, approximately six meters tall in total."
    quote = "approximately six meters tall"
    criteria = {key: 6.0, f"{key}_source": quote}

    result = _apply(criteria, document_text=document, four_c_abstained=set())
    assert result[key] == 6.0, "L2 must not fire when the field is not in four_c_abstained"


# ---------------------------------------------------------------------------
# U-SS-10: None value skipped entirely — no layer fires, no error
# ---------------------------------------------------------------------------

def test_U_SS_10_none_value_skipped():
    """If the value is already None, the enforcement loop skips the field
    entirely — including when the source key is absent from the dict.
    """
    key = "required_lifting_height"
    criteria = {key: None}
    result = _apply(criteria, document_text="", four_c_abstained={key})
    assert result[key] is None, "Already-null value must remain null and not raise an error"


# ---------------------------------------------------------------------------
# U-SS-11: documented bounded residual — small round integer near unrelated text
# ---------------------------------------------------------------------------

def test_U_SS_11_documented_residual_gradient_collision_case():
    """Regression check for the one residual case flagged during the 2026-06-16
    investigation: CompanyX's fabricated required_max_gradient=10 was
    suspected to risk a coincidental '10' collision elsewhere in the document
    (e.g. '10 years' / '10 %' boilerplate). Direct verification against the
    real CompanyX.pdf text shows no such collision currently occurs — L0
    correctly nulls this fabrication. This test pins that result so a future
    change to the window/stopword constants can't silently reopen the leak
    without a visible test failure.

    This exact vulnerability class (a bare converted-scale number, e.g. 10,
    anchoring against unrelated document boilerplate) DID materialize over a
    month later on a different field/tender: Dragonfly's required_lifting_height
    fabrication ("Lift height: 10,000 mm" against an unrelated "mm 10" table
    cell + "10 years" clause). '%' is not a metric-prefix unit so this specific
    gradient case is unaffected by that fix (still relies on co-location only,
    same as before) — but see tests/unit/test_source_is_grounded.py
    test_U_SG_15..21 for the real fix and the materialized-incident regression
    tests, and the metric-prefix unit-gated anchor added to source_is_grounded()
    in src/json_repair.py.
    """
    import pdfplumber

    with pdfplumber.open(Path(__file__).parent.parent.parent / "tenders" / "CompanyX.pdf") as pdf:
        document = "\n".join(p.extract_text() or "" for p in pdf.pages)

    key = "required_max_gradient"
    fabricated_quote = "The maximum gradeability of the loaded unit is up to 10 %."
    criteria = {key: 10, f"{key}_source": fabricated_quote}
    result = _apply(criteria, document_text=document)
    assert result[key] is None, (
        "Fabricated gradient=10 must be nulled — if this starts failing, the "
        "documented residual collision risk has materialized and needs a real fix, "
        "not a threshold nudge"
    )


# ---------------------------------------------------------------------------
# D1: enforce_source_spans() returns a 3-tuple; events + messages are generic
# ---------------------------------------------------------------------------

def test_D1_returns_events_alongside_messages():
    """enforce_source_spans() returns (domain_criteria, messages, events). One
    SpanEvent per field actually nulled, carrying field/layer/value/source —
    this is what D1 provenance attribution in app.py consumes.
    """
    key = "required_max_payload"
    criteria = {key: 1000, f"{key}_source": None}
    result, messages, events = enforce_source_spans(
        dict(criteria), "", _NUMERIC_KO_TENDER_KEYS, set()
    )
    assert result[key] is None
    assert len(events) == 1
    assert events[0] == SpanEvent(field=key, layer="L1", value=1000, source=None)
    assert len(messages) == 1


def test_D1_messages_are_generically_derived_from_events_not_field_names():
    """The enriched messages must be constructable purely from SpanEvent-shaped
    data — no per-field-name text branches, no domain vocabulary. Proven here by
    feeding a made-up field name (not any real AP0 tender_key) through the same
    generic helper used by enforce_source_spans() and getting a well-formed
    message back, with no special-casing anywhere.
    """
    fake_events = [
        SpanEvent(field="totally_made_up_field_zzz", layer="L0",
                  value=42, source="some fabricated quote text here"),
    ]
    messages = _messages_from_events(fake_events)
    assert len(messages) == 1
    assert "totally_made_up_field_zzz" in messages[0]
    assert "L0" in messages[0]
    assert "42" in messages[0]
    assert "some fabricated quote text here"[:60] in messages[0]

    # And the real enforce_source_spans() call site produces messages using the
    # exact same helper — single source of truth, not two independent code paths.
    key = "required_max_payload"
    criteria = {key: 4.8, f"{key}_source": "The maximum lift height of the AGVs is up to 4.8 m."}
    _, messages_from_call, events_from_call = enforce_source_spans(
        dict(criteria), "", _NUMERIC_KO_TENDER_KEYS, set()
    )
    assert messages_from_call == _messages_from_events(events_from_call)
