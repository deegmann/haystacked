"""Unit tests for matching logic (U-M-01 to U-M-17)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from src.models import FieldValue, Product, SupplierRecord
from src.field_spec import load_fields
from src.matching import TenderRequirements, Matcher
from app import _criteria_to_uuid_keyed


def _make_values(prod: "Product | None" = None, **kwargs) -> dict:
    specs = load_fields()
    defaults = dict(
        product_type="Forklift AGV",
        max_payload_kg=2000.0,
        lifting_height_mm=12000,
        min_aisle_width_mm=1600,
        navigation_type=["Natural Feature"],
        stacking_capability=True,
        forks_free_floating=True,
        outdoor_capable=False,
        vda5050_compatible=True,
        battery_runtime_h=10.0,
        autonomous_charging=True,
        safety_standard=["ISO 3691-4"],
        stop_accuracy_mm=8,
    )
    defaults.update(kwargs)
    values = {}
    for uuid, spec in specs.items():
        if spec.field_name in defaults:
            val = defaults[spec.field_name]
        elif prod is not None and spec.entity in ("Product", "Company"):
            val = getattr(prod, spec.field_name, None)
        else:
            val = None
        values[uuid] = FieldValue(spec=spec, value=val)
    return values


def _make_prod(**kwargs) -> Product:
    defaults = dict(
        product_id="p-1",
        company_id="c-1",
        base_model_id="bm-1",
        product_name="TestProduct",
        product_type="Forklift AGV",
        company_name="TestCo",
        reference_count=10,
        lead_time_weeks=12,
        service_coverage=["DACH", "EU"],
        active=True,
    )
    defaults.update(kwargs)
    return Product(**defaults)


def _make_record(**val_kwargs) -> SupplierRecord:
    prod = _make_prod()
    return SupplierRecord(product=prod, values=_make_values(prod=prod, **val_kwargs))


matcher = Matcher()


def _match_one(req_dict: dict, **ext_kwargs) -> object:
    rec = _make_record(**ext_kwargs)
    top, _ = matcher.match([rec], TenderRequirements.from_dict(_criteria_to_uuid_keyed(req_dict)), top_n=1)
    return top[0]


def test_U_M_01_ko_payload_too_low():
    r = _match_one({"max_payload_kg": 3000}, max_payload_kg=1000.0)
    assert r.disqualified


def test_U_M_02_ko_payload_null_not_excluded():
    r = _match_one({"max_payload_kg": 3000}, max_payload_kg=None)
    assert not r.disqualified


def test_U_M_03_ko_wrong_product_type():
    prod = _make_prod(product_type="Tugger AGV")
    rec = SupplierRecord(
        product=prod,
        values=_make_values(prod=prod, product_type="Tugger AGV"),
    )
    top, _ = matcher.match([rec], TenderRequirements.from_dict(_criteria_to_uuid_keyed({"product_type": "Forklift AGV"})))
    assert top[0].disqualified


def test_U_M_04_navigation_context_no_disqualification():
    """Step 6: navigation_type is now CONTEXT (no operator). A mismatch must NOT disqualify.

    Before Step 6 (COND_KO / KO_SUBSET): supplier with Natural Feature was excluded
    when tender required Laser Reflector. After Step 6: navigation_type is informational
    only — no KO fires regardless of the mismatch.
    """
    r = _match_one({"navigation_type": ["Laser Reflector"]}, navigation_type=["Natural Feature"])
    assert not r.disqualified


def test_U_M_05_cond_ko_outdoor_not_required_no_filter():
    r = _match_one({"outdoor_capable": "not_required"}, outdoor_capable=False)
    assert not r.disqualified


def test_U_M_06_cond_ko_outdoor_required_false_excluded():
    r = _match_one({"outdoor_capable": "required"}, outdoor_capable=False)
    assert r.disqualified


def test_U_M_07_cond_ko_outdoor_required_null_not_excluded():
    r = _match_one({"outdoor_capable": "required"}, outdoor_capable=None)
    assert not r.disqualified


def test_U_M_08_cond_ko_forks_free_floating_required_straddle_excluded():
    r = _match_one({"forks_free_floating": "required"}, forks_free_floating=False)
    assert r.disqualified


def test_U_M_09_cond_ko_forks_free_floating_required_counterbalanced_in_pool():
    r = _match_one({"forks_free_floating": "required"}, forks_free_floating=True)
    assert not r.disqualified


def test_U_M_10_scoring_higher_reference_count_ranks_higher():
    prod_high = _make_prod(reference_count=20)
    prod_low  = _make_prod(reference_count=2)
    rec_high = SupplierRecord(product=prod_high, values=_make_values(prod=prod_high))
    rec_low  = SupplierRecord(product=prod_low,  values=_make_values(prod=prod_low))
    top, _ = matcher.match([rec_low, rec_high], TenderRequirements.from_dict(_criteria_to_uuid_keyed({"product_type": "Forklift AGV"})))
    assert top[0].record.product.reference_count == 20


def test_U_M_11_scoring_reference_count_null_neutral():
    prod_null = _make_prod(reference_count=None)
    rec_null = SupplierRecord(product=prod_null, values=_make_values(prod=prod_null))
    top, _ = matcher.match([rec_null], TenderRequirements.from_dict(_criteria_to_uuid_keyed({"product_type": "Forklift AGV"})))
    assert not top[0].disqualified


def test_U_M_12_cond_ko_vda5050_preferred_no_filter():
    r = _match_one({"vda5050_compatible": "preferred"}, vda5050_compatible=False)
    assert not r.disqualified


def test_U_M_13_empty_tender_returns_all_active():
    recs = [_make_record() for _ in range(3)]
    top, all_r = matcher.match(recs, TenderRequirements.from_dict(_criteria_to_uuid_keyed({})), top_n=10)
    assert len(all_r) == 3
    assert all(not r.disqualified for r in all_r)


def test_U_M_14_service_coverage_is_context_not_ko():
    """service_coverage demoted Cond.K.O.->Context (OI-97 Blocker A, 2026-07-30):
    the AP0 allowed_values bucket set (None/DACH/EU/Global) had zero DACH-tagged
    suppliers in the live DB while 199 carried EU/EU|Global, so a real DACH-required
    tender would have disqualified every active supplier once KO_SUBSET's substring
    false-pass bug (OI-97) is fixed. Field is informational until the Airtable
    per-country re-tagging research item is done. A mismatch must NOT disqualify."""
    prod = _make_prod(service_coverage=["EU"])
    rec = SupplierRecord(
        product=prod,
        values=_make_values(prod=prod),
    )
    top, _ = matcher.match([rec], TenderRequirements.from_dict(_criteria_to_uuid_keyed({"required_service_coverage": ["DE"]})))
    assert not top[0].disqualified, "service_coverage is CONTEXT-level and must never disqualify"


def test_U_M_15_ranking_3_suppliers():
    recs = [_make_record() for _ in range(5)]
    top, _ = matcher.match(recs, TenderRequirements.from_dict(_criteria_to_uuid_keyed({})), top_n=5)
    assert len(top) >= 3


def test_U_M_16_score_details_present():
    r = _match_one({"product_type": "Forklift AGV"})
    assert len(r.score_details) > 0
    for detail in r.score_details:
        assert "field" in detail
        assert "points" in detail


def test_U_M_17_deterministic_same_input_same_order():
    recs = [_make_record(max_payload_kg=float(i * 500 + 1000)) for i in range(5)]
    req  = TenderRequirements.from_dict(_criteria_to_uuid_keyed({"product_type": "Forklift AGV"}))
    _, r1 = matcher.match(recs, req)
    _, r2 = matcher.match(recs, req)
    assert [r.product_name for r in r1] == [r.product_name for r in r2]


# ── OI-17: KO_BOOL_EXCLUSIVE — VNA gate both directions ──────────────────────

def test_U_M_18_vna_required_non_vna_supplier_excluded():
    r = _match_one({"required_vna_capable": "required"}, vna_capable=False)
    assert r.disqualified

def test_U_M_19_vna_not_required_vna_supplier_excluded():
    r = _match_one({"required_vna_capable": "not_required"}, vna_capable=True)
    assert r.disqualified

def test_U_M_20_vna_required_vna_supplier_passes():
    r = _match_one({"required_vna_capable": "required"}, vna_capable=True)
    assert not r.disqualified

def test_U_M_21_vna_null_vna_supplier_not_excluded():
    r = _match_one({}, vna_capable=True)
    assert not r.disqualified

# SQLite stores booleans as integers (0/1); `1 is True` is False in Python.
# These two tests use int literals to catch identity-check regressions.
def test_U_M_19b_vna_not_required_vna_supplier_int1_excluded():
    r = _match_one({"required_vna_capable": "not_required"}, vna_capable=1)
    assert r.disqualified, "SQLite int 1 must trigger VNA K.O. (not just Python True)"

def test_U_M_20b_vna_required_vna_supplier_int1_passes():
    r = _match_one({"required_vna_capable": "required"}, vna_capable=1)
    assert not r.disqualified, "SQLite int 1 must be treated as True in VNA check"


# ── OI-18: special_fork_option COND_KO (KO_SUBSET) ───────────────────────────

def test_U_M_22_special_fork_null_tender_never_disqualifies():
    r = _match_one({}, special_fork_option=["Telescopic"])
    assert not r.disqualified

def test_U_M_23_special_fork_clamp_required_telescopic_supplier_excluded():
    r = _match_one({"required_special_fork_option": ["Clamp"]},
                   special_fork_option=["Telescopic"])
    assert r.disqualified

def test_U_M_24_special_fork_telescopic_supplier_has_it_passes():
    r = _match_one({"required_special_fork_option": ["Telescopic"]},
                   special_fork_option=["Telescopic", "Side-Shift"])
    assert not r.disqualified


# ── OI-19: NULL-KO-Penalty (-15pt) ───────────────────────────────────────────

def test_U_M_25_null_ko_penalty_fires_for_null_supplier_numeric_field():
    # Tender requires lift height 8000mm; supplier has no data → not disqualified but -15pt
    r = _match_one({"required_lifting_height_mm": 8000}, lifting_height_mm=None)
    assert not r.disqualified
    penalty = sum(d["points"] for d in r.score_details if "null_penalty" in d["field"])
    assert penalty == -15

def test_U_M_26_null_ko_penalty_absent_when_tender_null():
    # No tender requirement → no null penalty even if supplier field is null
    r = _match_one({}, lifting_height_mm=None)
    assert not any("null_penalty" in d["field"] for d in r.score_details)


# ── OI-21: vda5050 preferred bonus — no double-count with scoring_weights ─────

def test_U_M_27_vda5050_preferred_not_double_counted():
    r = _match_one({"required_vda5050_compatible": "preferred"}, vda5050_compatible=True)
    vda_entries = [d for d in r.score_details
                   if "vda5050" in d["field"].lower()]
    # Must appear at most once — either from fields.json scoring weight or preferred bonus, not both
    assert len(vda_entries) <= 1


# ── OI-21: Regression guard — preferred bonus block removed (OI-01) ───────────

def test_U_M_28_no_hardcoded_preferred_bonus_labels():
    r = _match_one({"required_vda5050_compatible": "preferred",
                    "required_outdoor_capable": "preferred",
                    "required_auto_hitch": "preferred"},
                   vda5050_compatible=True, outdoor_capable=True, auto_hitch=True)
    labels = [d["field"] for d in r.score_details]
    assert "vda5050_preferred_bonus" not in labels
    assert "outdoor_preferred_bonus" not in labels
    assert "auto_hitch_preferred_bonus" not in labels


# ── OI-47: VT-scope isolation — Tugger supplier must not be evaluated ─────────
#           against Forklift-specific fields

def test_OI47_tugger_supplier_not_penalised_for_forklift_field():
    """Tugger-Supplier must not receive a null-KO-penalty for Forklift-specific fields.

    lifting_height_mm belongs to the 'Forklift AGV' sheet only.
    A Tugger supplier with lifting_height_mm=None and a tender that requires
    a lift height must NOT accumulate a null_penalty for that field, because
    lifting_height_mm is not in the relevant field set for Tugger AGV suppliers.
    """
    prod = _make_prod(product_type="Tugger AGV")
    rec = SupplierRecord(
        product=prod,
        values=_make_values(prod=prod, product_type="Tugger AGV", lifting_height_mm=None),
    )
    top, _ = matcher.match(
        [rec],
        TenderRequirements.from_dict(_criteria_to_uuid_keyed({"required_lifting_height_mm": 5.0})),
        top_n=1,
    )
    r = top[0]
    assert not r.disqualified, "Tugger supplier must not be disqualified for lift height"
    penalty_labels = [d["field"] for d in r.score_details if "null_penalty" in d["field"]]
    assert "lifting_height_mm_null_penalty" not in penalty_labels, (
        "Tugger supplier must not receive null-penalty for Forklift-specific lifting_height_mm"
    )


# ── value_if_null: VNA closed-world assumption ────────────────────────────────

def test_value_if_null_vna_supplier_none_is_kod_on_vna_tender():
    """Supplier vna_capable=None gets KO'd on VNA tender because value_if_null=False."""
    r = _match_one({"required_vna_capable": "required"}, vna_capable=None)
    assert r.disqualified, (
        "Supplier with vna_capable=None must be KO'd on VNA tender — "
        "value_if_null=False substitutes None, then KO_BOOL_EXCLUSIVE fires"
    )


def test_value_if_null_vna_supplier_none_passes_non_vna_tender():
    """Supplier vna_capable=None is NOT KO'd on non-VNA tender (required_vna_capable=None)."""
    r = _match_one({}, vna_capable=None)
    assert not r.disqualified, (
        "Supplier with vna_capable=None must not be KO'd when tender has no VNA requirement — "
        "tender-side value stays None, no constraint applies"
    )


def test_value_if_null_no_null_penalty_when_value_substituted():
    """When value_if_null substitutes None, no _null_penalty appears in score_details."""
    r = _match_one({"required_vna_capable": "required"}, vna_capable=None)
    penalty_labels = [d["field"] for d in r.score_details if "null_penalty" in d["field"]]
    assert "vna_capable_null_penalty" not in penalty_labels, (
        "After value_if_null substitution, vna_capable must not appear as a null_penalty entry"
    )


# ── Bool operator: True/False handling ───────────────────────────────────────

def test_U_M_29_bool_required_true_triggers_ko():
    """KO_BOOL_REQUIRED with tender=True (LLM boolean) must trigger KO when supplier=False."""
    from src.matching import _op_bool_required
    failed, msg = _op_bool_required(True, False)
    assert failed, "tender=True must trigger KO_BOOL_REQUIRED when supplier=False"
    assert "required" in msg.lower()

def test_U_M_30_bool_required_false_no_ko():
    """KO_BOOL_REQUIRED with tender=False must NOT trigger KO (not required)."""
    from src.matching import _op_bool_required
    failed, _ = _op_bool_required(False, False)
    assert not failed, "tender=False means 'not required' — must not trigger KO"

def test_U_M_31_bool_required_null_supplier_no_ko():
    """KO_BOOL_REQUIRED with tender=True but supplier=None must NOT trigger KO (LL-06)."""
    from src.matching import _op_bool_required
    failed, _ = _op_bool_required(True, None)
    assert not failed, "Null supplier must not trigger KO (LL-06)"

def test_U_M_32_is_active_requirement_false_not_active():
    """_is_active_requirement returns False for boolean False tender value."""
    from src.matching import _is_active_requirement
    assert not _is_active_requirement(False, "KO_BOOL_REQUIRED")
    assert not _is_active_requirement(False, "KO_BOOL_EXCLUSIVE")

def test_U_M_33_is_active_requirement_true_is_active():
    """_is_active_requirement returns True for boolean True tender value."""
    from src.matching import _is_active_requirement
    assert _is_active_requirement(True, "KO_BOOL_REQUIRED")
    assert _is_active_requirement("required", "KO_BOOL_REQUIRED")

def test_U_M_34_is_active_requirement_numeric_nonzero():
    """_is_active_requirement returns False for KO_IF_LT with value 0 (no minimum = no constraint).
    Signed units (°C) are exempt — 0 °C is a real temperature constraint.
    """
    from src.matching import _is_active_requirement
    assert not _is_active_requirement(0, "KO_IF_LT")          # 0 = no min requirement (e.g. flat floor)
    assert not _is_active_requirement(0, "KO_IF_LT", None)    # unsigned unit also inactive
    assert _is_active_requirement(0, "KO_IF_LT", "°C")        # signed unit — 0 °C is a real constraint
    assert _is_active_requirement(1200, "KO_IF_LT")
    assert not _is_active_requirement(None, "KO_IF_LT")


# ── OI-115b: reversed (m→mm) auto-heal conversion in validate_domain_criteria ────
# lifting_height_mm/min_aisle_width_mm's AP0 Unit is now 'mm' (was 'm'). The AP0
# Unit Conversions sheet now defines the REVERSE direction: threshold=30, factor=1000
# (m→mm) — historical replay files that stored these fields' values in meters
# self-heal on replay instead of needing a forward mm→m conversion.

def test_U_M_35_lifting_height_m_auto_healed_to_mm():
    """validate_domain_criteria converts a lifting height mistakenly stated in
    meters (small raw value, below threshold=30) up to mm.

    A value of 8 (clearly meters, < threshold of 30) must be healed to 8000 mm.
    A value of 8000 (already in mm, >= threshold) must pass through unchanged.
    """
    from app import validate_domain_criteria
    result_m, warnings_m = validate_domain_criteria(
        {"required_lifting_height_mm": 8}
    )
    assert result_m["required_lifting_height_mm"] == pytest.approx(8000.0), (
        "8 m must be auto-healed to 8000 mm (factor=1000 from plausibility.json)"
    )
    assert any("konvertiert" in w or "converted" in w.lower() for w in warnings_m), (
        "A conversion warning must be emitted when m→mm auto-heal fires"
    )

    result_mm, warnings_mm = validate_domain_criteria(
        {"required_lifting_height_mm": 8000}
    )
    assert result_mm["required_lifting_height_mm"] == pytest.approx(8000.0), (
        "8000 mm (already in mm, >= threshold of 30) must pass through unchanged"
    )


def test_U_M_36_aisle_width_m_auto_healed_to_mm():
    """validate_domain_criteria converts an aisle width mistakenly stated in
    meters up to mm.

    Same conversion rule as lifting height: threshold=30, factor=1000.
    1.8 m → 1800 mm; 1800 stays as 1800.
    """
    from app import validate_domain_criteria
    result, warnings = validate_domain_criteria({"required_min_aisle_width_mm": 1.8})
    assert result["required_min_aisle_width_mm"] == pytest.approx(1800.0), (
        "1.8 m must be auto-healed to 1800 mm"
    )
    assert any("konvertiert" in w or "converted" in w.lower() for w in warnings)

    result2, _ = validate_domain_criteria({"required_min_aisle_width_mm": 1800})
    assert result2["required_min_aisle_width_mm"] == pytest.approx(1800.0), (
        "1800 mm (already in mm, >= threshold of 30) must pass through unchanged"
    )


def test_U_M_37_integration_capability_ko_subset_mismatch_disqualifies():
    """Step 6: integration_capability is now COND_KO / KO_SUBSET.

    A supplier whose integration_capability has no overlap with the tender's
    required_integration_capability must be disqualified.
    Supplier has only WMS+ERP; tender requires REST API — no overlap → KO.
    """
    r = _match_one(
        {"integration_capability": ["REST API"]},
        integration_capability=["WMS", "ERP"],
    )
    assert r.disqualified


def test_U_M_38_integration_capability_ko_subset_overlap_passes():
    """Step 6: integration_capability KO_SUBSET — all tender items are covered — passes.

    Tender requires WMS; supplier has SAP+WMS+REST API — WMS is covered → not KO.
    """
    r = _match_one(
        {"integration_capability": ["WMS"]},
        integration_capability=["SAP", "WMS", "REST API"],
    )
    assert not r.disqualified


def test_U_M_39_integration_capability_null_supplier_no_ko():
    """Step 6: null supplier integration_capability must not trigger KO (LL-06 null rule)."""
    r = _match_one(
        {"integration_capability": ["WMS"]},
        integration_capability=None,
    )
    assert not r.disqualified


# ---------------------------------------------------------------------------
# SA-18: Structural CONTEXT guard — all CONTEXT fields must never disqualify
# ---------------------------------------------------------------------------
# Dynamically loaded: when new fields are demoted to CONTEXT, they are
# automatically covered here without any test update.
import json as _json
_CONTEXT_MISMATCH_CASES = []
_all_fields = _json.loads((Path(__file__).parent.parent.parent / "config" / "fields.json").read_text())
for _spec in _all_fields.values():
    if _spec.get("level") != "CONTEXT" or not _spec.get("allowed_values"):
        continue
    _av = _spec["allowed_values"]
    if len(_av) >= 2:
        _tender_val = [_av[0]] if _spec.get("data_type") == "Multi-Select" else _av[0]
        _supplier_val = [_av[1]] if _spec.get("data_type") == "Multi-Select" else _av[1]
        _CONTEXT_MISMATCH_CASES.append((_spec["field_name"], _tender_val, _supplier_val))


@pytest.mark.parametrize("field_name,tender_val,supplier_val", _CONTEXT_MISMATCH_CASES)
def test_U_M_44_context_fields_never_disqualify(field_name, tender_val, supplier_val):
    """SA-18: CONTEXT-level fields must never trigger disqualification regardless of mismatch.

    Structural guard: dynamically built from fields.json at import time. Automatically
    covers future CONTEXT demotions. If this test fails, the field has a residual operator
    in AP0 — AP0 hygiene assert in generate_all.py (SA-22) should have caught it first.
    """
    r = _match_one({field_name: tender_val}, **{field_name: supplier_val})
    assert not r.disqualified, (
        f"CONTEXT field '{field_name}' must never disqualify. "
        f"Tender={tender_val!r}, Supplier={supplier_val!r}. "
        "Fix: check AP0 xlsx — CONTEXT fields must have no operator."
    )


# ---------------------------------------------------------------------------
# SA-19: infrastructure_free boolean-inversion semantic tests (Step 6)
# ---------------------------------------------------------------------------

def test_U_M_45a_infrastructure_free_required_supplier_false_disqualifies():
    """SA-19: COND_KO fires when buyer requires infra-free AND supplier needs infrastructure.

    infrastructure_free=False means the AGV REQUIRES permanent infrastructure (reflectors,
    tape, etc.). When the tender demands infra-free operation and the supplier cannot deliver
    it, the supplier must be disqualified.
    """
    r = _match_one({"infrastructure_free": "required"}, infrastructure_free=False)
    assert r.disqualified, (
        "Supplier with infrastructure_free=False must be disqualified when tender requires "
        "infrastructure-free operation (COND_KO/KO_BOOL_REQUIRED)."
    )


def test_U_M_45b_infrastructure_free_required_supplier_true_passes():
    """SA-19: No KO when supplier is infrastructure-free and tender requires it."""
    r = _match_one({"infrastructure_free": "required"}, infrastructure_free=True)
    assert not r.disqualified


def test_U_M_45c_infrastructure_free_null_supplier_no_ko():
    """SA-19: Null supplier infrastructure_free must not trigger KO (LL-06 null rule).

    Unknown infra status is not the same as 'requires infrastructure'. Blank ≠ Zero.
    """
    r = _match_one({"infrastructure_free": "required"}, infrastructure_free=None)
    assert not r.disqualified, (
        "Supplier with infrastructure_free=None must not be disqualified — "
        "null means unknown, not infrastructure-required. LL-06 null rule."
    )


# ---------------------------------------------------------------------------
# SA-21: Global-scope COND_KO coverage (country, languages_spoken)
# ---------------------------------------------------------------------------

def test_U_M_47_languages_spoken_ko_subset_mismatch_disqualifies():
    """SA-21: languages_spoken is Global scope (*) COND_KO/KO_SUBSET.

    Proves that Global-scope fields participate in matching via the resolution
    chain. Tender requires DE+EN; supplier only speaks ZH → no overlap → COND_KO.
    """
    r = _match_one(
        {"languages_spoken": ["DE", "EN"]},
        languages_spoken=["ZH"],
    )
    assert r.disqualified, (
        "languages_spoken KO_SUBSET must disqualify when there is no overlap. "
        "Global-scope (*) fields must participate in matching via resolution chain."
    )


def test_U_M_48_languages_spoken_ko_subset_overlap_passes():
    """SA-21: languages_spoken KO_SUBSET — all tender items are covered — passes."""
    r = _match_one(
        {"languages_spoken": ["DE"]},
        languages_spoken=["DE", "EN"],
    )
    assert not r.disqualified


def test_U_M_49_languages_spoken_null_supplier_no_ko():
    """SA-21: Null supplier languages_spoken must not trigger KO (LL-06 null rule)."""
    r = _match_one(
        {"languages_spoken": ["DE"]},
        languages_spoken=None,
    )
    assert not r.disqualified, (
        "Null supplier languages_spoken must not disqualify — LL-06 null rule. "
        "Unknown language support ≠ no German speakers."
    )


def test_U_M_50_ko_subset_partial_coverage_disqualifies():
    """OI-33: AND semantics — ALL tender items must be covered.
    Supplier covers Pallet EUR but not Pallet ISO → KO.
    """
    r = _match_one({"load_type": ["Pallet EUR", "Pallet ISO"]}, load_type=["Pallet EUR", "Tote"])
    assert r.disqualified


def test_U_M_51_ko_subset_superset_passes():
    """OI-33: Supplier covers all tender items plus extras → passes."""
    r = _match_one({"load_type": ["Pallet EUR"]}, load_type=["Pallet EUR", "Pallet ISO", "Tote"])
    assert not r.disqualified


def test_U_M_52_integration_capability_partial_overlap_now_ko():
    """OI-33: AND semantics applies to all KO_SUBSET fields.
    Tender requires VDA5050 AND REST API; supplier only has VDA5050 → KO.
    Under old OR semantics this would have passed (VDA5050 overlaps).
    """
    r = _match_one(
        {"integration_capability": ["VDA5050", "REST API"]},
        integration_capability=["VDA5050"],
    )
    assert r.disqualified


def test_U_M_53_context_info_in_to_dict():
    """OI-66: to_dict() must include context_info dict with no null values and only CONTEXT fields."""
    from src.field_spec import load_fields
    fields = load_fields()
    context_field_names = {f.field_name for f in fields.values() if f.level == "CONTEXT"}
    r = _match_one({})
    d = r.to_dict()
    assert "context_info" in d, "context_info key must be present"
    ctx = d["context_info"]
    assert isinstance(ctx, dict), "context_info must be a dict"
    for k, v in ctx.items():
        assert v is not None, f"context_info must not contain null values (got {k}=None)"
        assert k in context_field_names, f"{k} in context_info is not a CONTEXT-level field"


# ---------------------------------------------------------------------------
# IK: temperature KO direction (KO_IF_GT)
# ---------------------------------------------------------------------------

def test_temperature_ko_direction():
    """KO_IF_GT: supplier temperature_min_celsius must be <= tender requirement.

    Cold store tender requires -2 °C minimum temperature.
    Supplier that can only go to 0.0 °C is warmer than required → disqualified.
    Supplier that reaches -25.0 °C is colder than required → not disqualified.
    """
    prod_warm = _make_prod(product_type="Industrial Refrigeration")
    rec_warm = SupplierRecord(
        product=prod_warm,
        values=_make_values(prod=prod_warm, product_type="Industrial Refrigeration",
                            temperature_min_celsius=0.0),
    )

    prod_cold = _make_prod(product_type="Industrial Refrigeration")
    rec_cold = SupplierRecord(
        product=prod_cold,
        values=_make_values(prod=prod_cold, product_type="Industrial Refrigeration",
                            temperature_min_celsius=-25.0),
    )

    req = TenderRequirements.from_dict(
        _criteria_to_uuid_keyed({"temperature_min_celsius": -2})
    )

    top_warm, _ = matcher.match([rec_warm], req, top_n=1)
    assert top_warm[0].disqualified, (
        "Supplier with temperature_min_celsius=0.0 must be disqualified for a "
        "-2 °C cold store tender (0.0 > -2 triggers KO_IF_GT)"
    )

    top_cold, _ = matcher.match([rec_cold], req, top_n=1)
    assert not top_cold[0].disqualified, (
        "Supplier with temperature_min_celsius=-25.0 must NOT be disqualified for a "
        "-2 °C cold store tender (-25.0 <= -2, KO_IF_GT does not fire)"
    )


# ---------------------------------------------------------------------------
# OI-97: KO_SUBSET must split a raw comma/pipe string, not treat it as one blob
# ---------------------------------------------------------------------------

def test_U_M_54_op_subset_raw_string_splits_correctly():
    """OI-97 direct pin: _op_subset must split a raw (unsplit) tender string on
    comma/pipe before comparing — not treat it as one substring-matchable blob.
    Before the fix: "wms, erp" contains "wms" as a substring, so the whole
    requirement silently passed even though "erp" was never covered.
    """
    from src.matching import _op_subset
    failed, msg = _op_subset("WMS, ERP", ["SAP", "WMS"])
    assert failed, "supplier lacking ERP must be disqualified, not pass via substring blob match"
    assert "erp" in msg.lower()


def test_U_M_55_ko_subset_raw_string_disqualifies_via_real_pipeline_path():
    """OI-97 real-path pin: the production pipeline stores tender values UUID-keyed
    (TenderRequirements(run), not from_dict()) and never pre-splits Multi-Select
    strings. Feed a raw comma string through build_tender_run() -> TenderRequirements
    exactly as app.py does, and confirm the KO fires for real via that path."""
    from src.tender_store import build_tender_run

    prod = _make_prod()
    rec = SupplierRecord(
        product=prod,
        values=_make_values(prod=prod, integration_capability=["SAP", "WMS"]),
    )
    run = build_tender_run(
        run_id="test-oi97-01",
        source_file="test.pdf",
        new_req={"required_integration_capability": "WMS, ERP"},
        domain_criteria={},
        result={"buyer": "Test", "in_scope": True},
        vehicle_type="Forklift AGV",
        in_scope=True,
    )
    top, _ = matcher.match([rec], TenderRequirements(run), top_n=1)
    assert top[0].disqualified, "raw comma-string tender requirement must disqualify a supplier missing ERP"
    assert any("erp" in m.lower() for m in top[0].disqualified_by)


def test_U_M_56_ko_subset_raw_string_no_false_ko_when_covered():
    """OI-97 no-false-KO pin: same real pipeline path, but supplier actually has
    ERP too -> must NOT be disqualified. Without this, a fix that just KO's
    everything would also satisfy test_U_M_55."""
    from src.tender_store import build_tender_run

    prod = _make_prod()
    rec = SupplierRecord(
        product=prod,
        values=_make_values(prod=prod, integration_capability=["SAP", "WMS", "ERP"]),
    )
    run = build_tender_run(
        run_id="test-oi97-02",
        source_file="test.pdf",
        new_req={"required_integration_capability": "WMS, ERP"},
        domain_criteria={},
        result={"buyer": "Test", "in_scope": True},
        vehicle_type="Forklift AGV",
        in_scope=True,
    )
    top, _ = matcher.match([rec], TenderRequirements(run), top_n=1)
    assert not top[0].disqualified, "supplier covering both WMS and ERP must not be disqualified"


def test_U_M_57_ko_subset_raw_string_non_multiselect_country_field():
    """OI-97 blind-spot pin: `country`'s AP0 data_type is 'ISO 3166 (2-letter)', not
    'Multi-Select' — a fix keyed off data_type (e.g. a _COERCE dict lookup) would
    silently skip it. The correct fix lives inside _op_subset itself, so it must
    also split/compare correctly for this field regardless of its data_type label."""
    from src.tender_store import build_tender_run

    prod_de = _make_prod()
    rec_de = SupplierRecord(product=prod_de, values=_make_values(prod=prod_de, country="DE"))

    run = build_tender_run(
        run_id="test-oi97-03",
        source_file="test.pdf",
        new_req={"required_country": "DE"},
        domain_criteria={},
        result={"buyer": "Test", "in_scope": True},
        vehicle_type="Forklift AGV",
        in_scope=True,
    )
    top, _ = matcher.match([rec_de], TenderRequirements(run), top_n=1)
    assert not top[0].disqualified, "DE supplier must satisfy a DE-required tender"

    prod_fr = _make_prod()
    rec_fr = SupplierRecord(product=prod_fr, values=_make_values(prod=prod_fr, country="FR"))
    top_fr, _ = matcher.match([rec_fr], TenderRequirements(run), top_n=1)
    assert top_fr[0].disqualified, "FR supplier must be disqualified for a DE-required tender"
