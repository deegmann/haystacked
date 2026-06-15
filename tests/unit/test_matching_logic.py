"""Unit tests for matching logic (U-M-01 to U-M-17)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.models import Extension, Product, SupplierRecord
from src.matching import TenderRequirements, Matcher


def _make_ext(**kwargs) -> Extension:
    defaults = dict(
        extension_id="ext-1",
        base_model_id="bm-1",
        agv_type="Forklift AGV",
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
    return Extension(**defaults)


def _make_prod(**kwargs) -> Product:
    defaults = dict(
        product_id="p-1",
        company_id="c-1",
        base_model_id="bm-1",
        product_name="TestProduct",
        agv_type="Forklift AGV",
        company_name="TestCo",
        reference_count=10,
        lead_time_weeks=12,
        service_coverage=["DACH", "EU"],
        active=True,
    )
    defaults.update(kwargs)
    return Product(**defaults)


def _make_record(**ext_kwargs) -> SupplierRecord:
    return SupplierRecord(product=_make_prod(), extension=_make_ext(**ext_kwargs))


matcher = Matcher()


def _match_one(req_dict: dict, **ext_kwargs) -> object:
    rec = _make_record(**ext_kwargs)
    top, _ = matcher.match([rec], TenderRequirements(req_dict), top_n=1)
    return top[0]


def test_U_M_01_ko_payload_too_low():
    r = _match_one({"max_payload_kg": 3000}, max_payload_kg=1000.0)
    assert r.disqualified


def test_U_M_02_ko_payload_null_not_excluded():
    r = _match_one({"max_payload_kg": 3000}, max_payload_kg=None)
    assert not r.disqualified


def test_U_M_03_ko_wrong_agv_type():
    rec = SupplierRecord(
        product=_make_prod(agv_type="Tugger AGV"),
        extension=_make_ext(agv_type="Tugger AGV"),
    )
    top, _ = matcher.match([rec], TenderRequirements({"agv_type": "Forklift AGV"}))
    assert top[0].disqualified


def test_U_M_04_ko_navigation_no_match():
    r = _match_one({"navigation_type": ["Laser Reflector"]}, navigation_type=["Natural Feature"])
    assert r.disqualified


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
    rec_high = SupplierRecord(product=_make_prod(reference_count=20), extension=_make_ext())
    rec_low  = SupplierRecord(product=_make_prod(reference_count=2),  extension=_make_ext())
    top, _ = matcher.match([rec_low, rec_high], TenderRequirements({"agv_type": "Forklift AGV"}))
    assert top[0].record.product.reference_count == 20


def test_U_M_11_scoring_reference_count_null_neutral():
    rec_null = SupplierRecord(product=_make_prod(reference_count=None), extension=_make_ext())
    top, _ = matcher.match([rec_null], TenderRequirements({"agv_type": "Forklift AGV"}))
    assert not top[0].disqualified


def test_U_M_12_cond_ko_vda5050_preferred_no_filter():
    r = _match_one({"vda5050_compatible": "preferred"}, vda5050_compatible=False)
    assert not r.disqualified


def test_U_M_13_empty_tender_returns_all_active():
    recs = [_make_record() for _ in range(3)]
    top, all_r = matcher.match(recs, TenderRequirements({}), top_n=10)
    assert len(all_r) == 3
    assert all(not r.disqualified for r in all_r)


def test_U_M_14_service_coverage_dach_required_eu_only_excluded():
    rec = SupplierRecord(
        product=_make_prod(service_coverage=["EU"]),
        extension=_make_ext(),
    )
    top, _ = matcher.match([rec], TenderRequirements({"required_service_coverage": ["DACH"]}))
    assert top[0].disqualified, "EU-only supplier must be disqualified for DACH-required tender"


def test_U_M_15_ranking_3_suppliers():
    recs = [_make_record() for _ in range(5)]
    top, _ = matcher.match(recs, TenderRequirements({}), top_n=5)
    assert len(top) >= 3


def test_U_M_16_score_details_present():
    r = _match_one({"agv_type": "Forklift AGV"})
    assert len(r.score_details) > 0
    for detail in r.score_details:
        assert "field" in detail
        assert "points" in detail


def test_U_M_17_deterministic_same_input_same_order():
    recs = [_make_record(max_payload_kg=float(i * 500 + 1000)) for i in range(5)]
    req  = TenderRequirements({"agv_type": "Forklift AGV"})
    _, r1 = matcher.match(recs, req)
    _, r2 = matcher.match(recs, req)
    assert [r.product_name for r in r1] == [r.product_name for r in r2]


# ── OI-17: KO_BOOL_EXCLUSIVE — VNA gate both directions ──────────────────────

def test_U_M_18_vna_required_non_vna_supplier_excluded():
    r = _match_one({"required_vna": "required"}, vna_capable=False)
    assert r.disqualified

def test_U_M_19_vna_not_required_vna_supplier_excluded():
    r = _match_one({"required_vna": "not_required"}, vna_capable=True)
    assert r.disqualified

def test_U_M_20_vna_required_vna_supplier_passes():
    r = _match_one({"required_vna": "required"}, vna_capable=True)
    assert not r.disqualified

def test_U_M_21_vna_null_vna_supplier_not_excluded():
    r = _match_one({}, vna_capable=True)
    assert not r.disqualified


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
    r = _match_one({"required_max_lift_height_m": 8000}, lifting_height_mm=None)
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
    # Must appear at most once — either from scoring_weights or preferred bonus, not both
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
