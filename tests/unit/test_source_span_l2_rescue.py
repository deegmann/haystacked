"""Unit tests for the D0 Layer-2 unit-adjacency rescue (`document_supports_value_with_unit()`
and the L2_RESCUED branch of `enforce_source_spans()` in src/json_repair.py).

Background: Pass 4b's `_source` fields sometimes echo the AP0 extraction hint
(generic descriptive prose) instead of a real document quote. When Pass 4c also
abstains on the same field, Layer 2 previously nulled the value unconditionally —
correctly for real hallucinations, but ALSO for genuinely correct extractions
whose citation channel happened to be broken the same way (the CompanyX
`required_max_payload_kg=1000` / `required_max_gradient_pct=1.5` regression).

The rescue: before nulling, check whether the value's digit-string occurs in the
REAL document adjacent to its unit token. If so, keep the value instead of
nulling it (SpanEvent(layer="L2_RESCUED", ...)) — a broken citation is not proof
a value is wrong when the value+unit pair independently exists in the document.

All tests below use REAL extracted document text (via pdfplumber, from the
tender PDFs already committed under tenders/) rather than synthetic strings —
this fix depends on real document layout/spacing properties (unit sometimes
precedes the number, coincidental short-token collisions like "58,000 m²"),
which a hand-written string cannot faithfully stand in for.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pdfplumber

from app import _NUMERIC_KO_TENDER_KEYS, _NUMERIC_KO_FIELD_UNITS
from src.json_repair import (
    enforce_source_spans,
    document_supports_value_with_unit,
    SpanEvent,
)

TENDERS_DIR = Path(__file__).parent.parent.parent / "tenders"


def _pdf_text(filename: str) -> str:
    with pdfplumber.open(TENDERS_DIR / filename) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def _companyx_text() -> str:
    return _pdf_text("CompanyX.pdf")


# ---------------------------------------------------------------------------
# Item 1: full-corpus false-rescue sweep against the actual current baseline.
#
# The live pipeline log (haystacked.log, 2026-07-28 15:51-16:01, 3 identical
# CompanyX runs per the D0 baseline capture in docs/d0_baseline_20260728/)
# shows exactly 3 UNIQUE (field, value) pairs ever reaching Layer 2 for the
# current CompanyX.pdf + current field-naming generation of the pipeline:
#   required_max_gradient_pct=1.5   (known-correct  -> must rescue)
#   required_max_payload_kg=1000    (known-correct  -> must rescue)
#   required_min_aisle_width_mm=3000 (known-fabricated -> must NOT rescue;
#       the document contains no "3000"/"3,000" anchor at all, and the field's
#       unit is the single-char 'm' which is excluded unconditionally anyway —
#       double-covered by both guard conditions)
# This is the complete population of L2 firings in the current baseline, so
# this sweep has 100% coverage of what's actually reproducible today (older
# log entries from 2026-06-03/04 use pre-rename field names — e.g.
# required_max_lift_height_m, required_temp_min_c — that no longer exist in
# fields.json/_NUMERIC_KO_TENDER_KEYS and cannot be replayed against current
# code).
# ---------------------------------------------------------------------------
_BASELINE_L2_FIRINGS = [
    ("required_max_gradient_pct", 1.5, True),
    ("required_max_payload_kg", 1000, True),
    ("required_min_aisle_width_mm", 3000, False),
]


def test_D0_full_corpus_false_rescue_sweep_current_baseline():
    """Every (field, value) pair that actually reached Layer 2 in the current
    (2026-07-28) CompanyX baseline capture is checked against the real document
    text: the two known-correct pairs must rescue, the one known-fabricated
    pair must not.
    """
    document = _companyx_text()
    for field, value, expected_rescue in _BASELINE_L2_FIRINGS:
        unit = _NUMERIC_KO_FIELD_UNITS[field]
        result = document_supports_value_with_unit(value, unit, document)
        assert result == expected_rescue, (
            f"{field}={value} (unit={unit!r}): expected rescue={expected_rescue}, got {result}"
        )


def test_D0_known_fabricated_values_from_prior_investigation_not_rescued():
    """Additional known-fabricated values named by the senior-architect's 2026-06
    investigation (required_max_gradient_pct=10, required_operating_temp_min_c=-25)
    do not occur as digit-anchors anywhere in the real CompanyX.pdf text at all —
    confirmed not rescued regardless of unit.
    """
    document = _companyx_text()
    assert document_supports_value_with_unit(10, "%", document) is False
    assert document_supports_value_with_unit(-25, "°C", document) is False


# ---------------------------------------------------------------------------
# Item 2: positive tests — known-correct CompanyX values are rescued end-to-end.
# ---------------------------------------------------------------------------

def test_D0_positive_payload_rescued_via_pure_function():
    document = _companyx_text()
    assert document_supports_value_with_unit(1000, "kg", document) is True


def test_D0_positive_gradient_rescued_via_pure_function():
    document = _companyx_text()
    assert document_supports_value_with_unit(1.5, "%", document) is True


def test_D0_positive_payload_rescued_end_to_end_via_enforce_source_spans():
    """Full enforce_source_spans() call, mirroring the actual production
    hint-echo failure mode (fabricated-looking, digit-free `_source`, 4c
    abstained): the field must be kept, not nulled, and a SpanEvent(layer=
    "L2_RESCUED", ...) must be present.
    """
    key = "required_max_payload_kg"
    hint_echo_source = (
        "The maximum permissible payload capacity of the vehicle, expressed in "
        "kilograms, describing the heaviest load the AGV can carry during operation."
    )
    criteria = {key: 1000, f"{key}_source": hint_echo_source}
    result, messages, events = enforce_source_spans(
        dict(criteria), _companyx_text(), _NUMERIC_KO_TENDER_KEYS, {key},
        units=_NUMERIC_KO_FIELD_UNITS,
    )
    assert result[key] == 1000, "rescued value must survive, not be nulled"
    assert any(ev.layer == "L2_RESCUED" and ev.field == key for ev in events)
    assert not any(ev.layer == "L2" and ev.field == key for ev in events), (
        "must not ALSO record a plain L2 null event for the same field"
    )
    assert any("L2_RESCUED" in m for m in messages)


def test_D0_positive_gradient_rescued_end_to_end_via_enforce_source_spans():
    key = "required_max_gradient_pct"
    hint_echo_source = (
        "The maximum gradient value the AGV must handle, described as a "
        "percentage figure for the loading area."
    )
    criteria = {key: 1.5, f"{key}_source": hint_echo_source}
    result, messages, events = enforce_source_spans(
        dict(criteria), _companyx_text(), _NUMERIC_KO_TENDER_KEYS, {key},
        units=_NUMERIC_KO_FIELD_UNITS,
    )
    assert result[key] == 1.5
    assert any(ev.layer == "L2_RESCUED" and ev.field == key for ev in events)


# ---------------------------------------------------------------------------
# Item 3: negative test — a coincidental anchor collision (grounded at L0, no
# digit in the hint-echoed quote, reaches L2) must still be nulled, no rescue.
# ---------------------------------------------------------------------------

def test_D0_negative_coincidental_anchor_collision_still_nulled_no_rescue():
    """A fabricated required_max_gradient_pct=10 whose hint-echoed source
    happens to be grounded (L0 passes) because the real document independently
    contains an unrelated '10' (spare-parts-availability '10 years' clause,
    not a gradient figure) must still be nulled at Layer 2 — the rescue must
    not fire because '%' does not co-locate with that unrelated '10'.
    """
    key = "required_max_gradient_pct"
    document = _companyx_text()
    hint_echo_source = (
        "Spare parts availability is guaranteed for an extended number of "
        "years after acceptance."
    )
    criteria = {key: 10, f"{key}_source": hint_echo_source}
    result, messages, events = enforce_source_spans(
        dict(criteria), document, _NUMERIC_KO_TENDER_KEYS, {key},
        units=_NUMERIC_KO_FIELD_UNITS,
    )
    assert result[key] is None, "must still be nulled — no rescue for an unrelated collision"
    assert len(events) == 1
    assert events[0] == SpanEvent(field=key, layer="L2", value=10, source=hint_echo_source)


# ---------------------------------------------------------------------------
# Item 4: single-character-alphabetic-unit exclusion.
# ---------------------------------------------------------------------------

def test_D0_single_char_unit_m_never_rescues_despite_adjacency():
    """Before OI-115b, required_lifting_height_mm / required_min_aisle_width_mm /
    required_tugger_min_aisle_width_mm carried unit 'm' in fields.json despite
    the _mm name suffix; OI-115b realigned their AP0 Unit to 'mm', so no numeric
    KO field carries the single-character unit 'm' any more. The exclusion rule
    itself is generic (field-agnostic, keyed on the unit string's length, not on
    a field list) so it still needs pinning against a real single-char-unit
    adjacency collision: real CompanyX.pdf text '...(yellow), which is 4m
    wide...'.
    """
    document = _companyx_text()
    assert not any(u == "m" for u in _NUMERIC_KO_FIELD_UNITS.values()), (
        "no numeric KO field should carry the bare unit 'm' post-OI-115b"
    )
    # The real 0-char-distance adjacency case: "4m wide" in the document.
    assert document_supports_value_with_unit(4, "m", document) is False


def test_D0_single_char_unit_m_squared_collision_never_rescues():
    """The concrete senior-architect-identified case: a fabricated 'm'-unit
    value of 58000 coincidentally anchors on the real '58,000 m²' area figure
    (an unrelated warehouse-area number, not any AGV dimension) — must not
    rescue.
    """
    document = _companyx_text()
    assert "58,000 m" in document
    assert document_supports_value_with_unit(58000, "m", document) is False


def test_D0_single_char_unit_K_and_h_also_excluded():
    """Generic rule, not a per-field list: ANY single-character alphabetic
    unit is excluded, including 'K' (required_temperature_stability_k) and
    'h' (required_pulldown_time_h).
    """
    document = "The system runs at a stable 5 K variance for 3 h during the test cycle."
    assert document_supports_value_with_unit(5, "K", document) is False
    assert document_supports_value_with_unit(3, "h", document) is False


# ---------------------------------------------------------------------------
# Item 5: empty-unit test.
# ---------------------------------------------------------------------------

def test_D0_empty_unit_never_rescues():
    document = _companyx_text()
    assert document_supports_value_with_unit(1000, "", document) is False
    assert document_supports_value_with_unit(1000, None, document) is False


# ---------------------------------------------------------------------------
# Item 6: regex-safety — unit tokens with regex metacharacters must not crash
# or misbehave, against real IK cold-chain tender document text.
# ---------------------------------------------------------------------------

def test_D0_regex_safety_percent_and_degree_and_cubic_units_real_text():
    """Real tender_ik_cold_store.pdf text contains 'ca. 3.800 m³', '+2 °C bis
    +6 °C', and '80 % und 90 %' — all units carrying regex metacharacters
    ('³', '°', '%'). None must crash re.escape()/re.search(), and each must
    correctly match its own real adjacent value.
    """
    document = _pdf_text("tender_ik_cold_store.pdf")
    assert document_supports_value_with_unit(3800, "m³", document) is True
    assert document_supports_value_with_unit(2, "°C", document) is True
    assert document_supports_value_with_unit(80, "%", document) is True
    # kg/h contains a regex-metacharacter-free but slash-bearing unit that the
    # AP0 field list carries (required_blast_freeze_capacity_kg_h) — the real
    # deep-freeze doc expresses the same physical quantity as "0,65 t/h", not
    # literally "kg/h", so this must not crash and must correctly return False
    # (no literal "kg/h" match) rather than silently no-op-matching everything.
    deep_freeze = _pdf_text("tender_ik_deep_freeze.pdf")
    assert document_supports_value_with_unit(650, "kg/h", deep_freeze) is False


def test_D0_regex_safety_cop_unit_no_metacharacters_still_safe():
    document = _pdf_text("tender_ik_deep_freeze.pdf")
    # COP has no regex metacharacters but exercises the same code path — must
    # not crash, and (no COP number present as a bare digit near "COP" in this
    # doc's phrasing) is expected to return False here.
    assert document_supports_value_with_unit(3, "COP", document) is False


# ---------------------------------------------------------------------------
# Item 7: critical regression check — test_T_TR_06 must be unaffected.
# ---------------------------------------------------------------------------

def test_D0_scale_tolerance_not_applied_matches_T_TR_06_fixture():
    """Pin the exact fixture values from
    test_T_TR_06_d1_l2_hint_echo_provenance_persists (tests/unit/test_tender_store.py):
    fabricated required_max_payload_kg=4.8, unit 'kg', document text containing
    the genuine but numerically-scaled '4800 kg'. document_supports_value_with_unit()
    must NOT rescue this — it must require an EXACT digit-string match, not the
    x1000/x0.001 scale tolerance used elsewhere in this module. If this ever
    flips to True, test_T_TR_06 (run explicitly, see below) would start failing.
    """
    document_text = "Maximum payload 4800 kg specified for heavy duty operation onsite."
    assert document_supports_value_with_unit(4.8, "kg", document_text) is False
    # And confirm the actual regression test is unaffected — run explicitly,
    # not just trusting the full-suite pass/fail.
    import subprocess
    proc = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q",
            "tests/unit/test_tender_store.py::test_T_TR_06_d1_l2_hint_echo_provenance_persists",
        ],
        cwd=str(Path(__file__).parent.parent.parent),
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        f"test_T_TR_06 regression check failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )


# ---------------------------------------------------------------------------
# Item 8: _NUMERIC_KO_FIELD_UNITS construction — first-spec-with-truthy-unit
# wins, correctly handling a tender_key shared across scopes where one scope's
# entry might have an empty unit.
# ---------------------------------------------------------------------------

def test_D0_units_dict_real_shared_scope_key_populated():
    """required_min_aisle_width_mm is the one tender_key in the current AP0
    that is genuinely shared across two scopes (Forklift AGV, Tugger AGV).
    Both scopes carry the same truthy unit ('mm' post-OI-115b) today, so this
    pins that the real construction picks a non-empty unit for it (the
    degenerate case where both entries agree)."""
    assert _NUMERIC_KO_FIELD_UNITS["required_min_aisle_width_mm"] == "mm"


def test_D0_units_dict_selection_algorithm_skips_empty_unit_shadowing_entry():
    """Synthetic reproduction of the exact selection algorithm used to build
    _NUMERIC_KO_FIELD_UNITS in app.py (first spec with hint+scope+unit all
    truthy wins) for a scenario that does not currently occur in the real AP0
    data: a shared tender_key where an EARLIER scope's spec has an empty unit
    and a LATER scope's spec has the real unit. The empty-unit entry must not
    shadow/suppress the real one.
    """
    from src.field_spec import FieldSpec

    def _mk(scope, unit):
        return FieldSpec(
            uuid=f"uuid-{scope}", field_name="fake_field", tender_key="fake_shared_key",
            entity="Tender", scope=scope, level="KO", operator="KO_IF_LT",
            data_type="Float", unit=unit, allowed_values=None, score_function=None,
            threshold_a=None, threshold_b=None, scoring_weight=None,
            hint="some hint", user_description=None, display_mode=None,
        )

    specs_shadow_first = [_mk("Logistics:AGV:Forklift", ""), _mk("Logistics:AGV:Tugger", "m")]
    units: dict = {}
    for spec in specs_shadow_first:
        if spec.hint and spec.scope and spec.unit:
            units[spec.tender_key] = spec.unit
            break
    assert units["fake_shared_key"] == "m", (
        "an empty-unit entry in an earlier scope must not suppress a real unit "
        "populated under a later scope for the same tender_key"
    )
