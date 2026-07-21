"""Golden extraction regression tests (U-GE-xx).

Reads golden run JSON files from tests/tenders/golden_run_tender_XXX.json
(produced by scripts/capture_pipeline_run.py) and compares the extracted
agv_criteria values against the golden_extraction fields in the corresponding
fixture file tests/tenders/tender_XXX.json.

If no golden run file exists for a tender, the test is skipped — the suite
never fails just because the LLM has not been run yet.

To generate a golden run file:
    python3 scripts/capture_pipeline_run.py tenders/Beispielausschreibung_AGV_Nordlicht.pdf

For in-scope AGV tenders the test verifies:
    golden_run['agv_criteria'][key] == fixture['golden_extraction'][key]
for every key in the fixture's golden_extraction dict.

For out-of-scope tenders (fixture has expected_out_of_scope=true) the test
verifies that the pipeline produced an empty agv_criteria and no matches —
i.e. the document was correctly identified as not an AGV tender.
"""
import sys
import json
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

_TENDER_DIR = Path(__file__).parent.parent / "tenders"


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _fixture_files():
    """Return all tests/tenders/tender_XXX.json files that have golden_extraction
    OR expected_out_of_scope=true with a golden_run_file."""
    fixtures = []
    for f in sorted(_TENDER_DIR.glob("tender_*.json")):
        data = _load_json(f)
        if data.get("golden_extraction") or (
            data.get("expected_out_of_scope") and data.get("golden_run_file")
        ):
            fixtures.append(f)
    return fixtures


def test_fixture_collection_floor():
    """Guard against a silent orphaning regression: this suite must keep collecting
    at least 8 fixtures (001–005 AGV + 006–008 IK as of 2026-07-21). A drop
    below this floor must fail loudly.
    """
    assert len(_fixture_files()) >= 8


def _golden_run_path(fixture: dict):
    golden_run_file = fixture.get("golden_run_file")
    if not golden_run_file:
        return None
    return _TENDER_DIR / golden_run_file


@pytest.mark.parametrize("fixture_path", _fixture_files(), ids=lambda p: p.stem)
def test_golden_extraction(fixture_path: Path):
    """Compare agv_criteria in a golden run file against the fixture's golden_extraction.

    For out-of-scope tenders, asserts the pipeline produced empty agv_criteria
    and no matches. Skipped if no golden run file exists for this tender.
    """
    fixture = _load_json(fixture_path)
    tender_id = fixture["tender_id"]

    golden_run_file = fixture.get("golden_run_file")
    if not golden_run_file:
        pytest.skip(f"{tender_id}: fixture has golden_extraction but no golden_run_file")
    golden_run_path = _TENDER_DIR / golden_run_file

    if not golden_run_path.exists():
        pytest.skip(
            f"No golden run file for {tender_id} — "
            f"run: python3 scripts/capture_pipeline_run.py {fixture.get('source_file', '?')}"
        )

    golden_run = _load_json(golden_run_path)

    # Out-of-scope path: pipeline must produce no AGV extraction and no matches.
    # vehicle_type must be present (positive sign the pipeline ran to completion)
    # and must not be a known AGV/AMR type.
    if fixture.get("expected_out_of_scope"):
        agv_criteria = golden_run.get("agv_criteria", {})
        match_results = golden_run.get("match_results", [])
        vehicle_type = golden_run.get("vehicle_type")
        _AGV_TYPES = {"Forklift AGV", "Tugger AGV", "Mobile AMR"}
        assert "vehicle_type" in golden_run, (
            f"{tender_id}: golden run must contain 'vehicle_type' key — "
            "its absence suggests the pipeline crashed before completing"
        )
        assert vehicle_type not in _AGV_TYPES, (
            f"{tender_id}: vehicle_type={vehicle_type!r} must not be an AGV type "
            "for an out-of-scope tender"
        )
        assert agv_criteria == {}, (
            f"{tender_id}: expected empty agv_criteria for out-of-scope tender, "
            f"got {list(agv_criteria.keys())}"
        )
        assert match_results == [], (
            f"{tender_id}: expected no match_results for out-of-scope tender, "
            f"got {len(match_results)} results"
        )
        return

    agv_criteria = golden_run.get("agv_criteria", {})
    golden_extraction = fixture["golden_extraction"]

    mismatches = []
    for key, expected in golden_extraction.items():
        actual = agv_criteria.get(key)
        if expected is None:
            if actual is not None:
                mismatches.append(
                    f"  {key}: expected None, got {actual!r}"
                )
        elif isinstance(expected, float):
            if actual is None or abs(float(actual) - expected) > 1e-6:
                mismatches.append(
                    f"  {key}: expected {expected}, got {actual!r}"
                )
        else:
            if actual != expected:
                mismatches.append(
                    f"  {key}: expected {expected!r}, got {actual!r}"
                )

    assert not mismatches, (
        f"Golden extraction mismatches for {tender_id} "
        f"({fixture.get('description', '')}):\n"
        + "\n".join(mismatches)
    )
