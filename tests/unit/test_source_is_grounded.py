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

from src.json_repair import source_is_grounded

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
