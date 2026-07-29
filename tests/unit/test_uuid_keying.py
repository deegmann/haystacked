"""UUID keying tests (T-UUID-01 to T-UUID-03).

Verifies that _criteria_to_uuid_keyed() correctly translates tender_key-keyed
dicts to UUID-keyed dicts, and that TenderRequirements.get() resolves values
via the UUID primary path — not the field_name fallback.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import _criteria_to_uuid_keyed, _TK_TO_UUIDS
from src.matching import TenderRequirements


def test_T_UUID_01_translates_known_tender_key():
    """_criteria_to_uuid_keyed must translate a known tender_key to at least one UUID key."""
    result = _criteria_to_uuid_keyed({"required_max_payload_kg": 5000})
    assert "required_max_payload_kg" not in result, "tender_key must not survive translation"
    uuids = _TK_TO_UUIDS.get("required_max_payload_kg", [])
    assert uuids, "required_max_payload_kg must have at least one UUID in _TK_TO_UUIDS"
    assert result.get(uuids[0]) == 5000, "UUID-keyed value must equal the original"


def test_T_UUID_02_passthrough_non_ap0_keys():
    """Non-AP0 keys (detected_domain, summary) must survive translation unchanged."""
    result = _criteria_to_uuid_keyed({"detected_domain": "Logistics:AGV", "summary": "test"})
    assert result.get("detected_domain") == "Logistics:AGV"
    assert result.get("summary") == "test"
    result_with_domain = _criteria_to_uuid_keyed({"detected_domain": "Logistics:AGV", "summary": "test"})
    assert result_with_domain.get("detected_domain") == "Logistics:AGV", \
        "detected_domain must pass through uuid_keying unchanged"


def test_T_UUID_03_tender_requirements_reads_uuid_keyed_dict():
    """TenderRequirements.get() must resolve a UUID-keyed dict via spec.uuid primary path."""
    translated = _criteria_to_uuid_keyed({"required_max_payload_kg": 5000})
    req = TenderRequirements.from_dict(translated)
    assert req.get("max_payload_kg") == 5000.0, (
        "TenderRequirements must resolve UUID-keyed value via spec.uuid"
    )


def test_T_UUID_04_tender_requirements_from_run_resolves_via_uuid_primary():
    """TenderRequirements(TenderRun) must resolve fields via UUID primary path.

    The real analyze() pipeline constructs TenderRequirements(run), NOT from_dict().
    This test verifies the UUID primary path works end-to-end, distinct from T-UUID-03
    which tests from_dict(uuid_keyed_dict).
    """
    from src.tender_store import build_tender_run
    from src.matching import TenderRequirements

    run = build_tender_run(
        run_id="test-uuid-04",
        source_file="test.pdf",
        new_req={"required_max_payload_kg": 2000.0, "required_product_type": "Forklift AGV"},
        domain_criteria={},
        result={"buyer": "Test", "in_scope": True},
        vehicle_type="Forklift AGV",
        in_scope=True,
    )
    req = TenderRequirements(run)

    assert req.get("max_payload_kg") == 2000.0, (
        "TenderRequirements(TenderRun) must resolve max_payload_kg via UUID primary path"
    )
    assert req.get("product_type") == "Forklift AGV", (
        "TenderRequirements(TenderRun) must resolve product_type via UUID primary path"
    )
