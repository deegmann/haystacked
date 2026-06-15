"""Golden extraction regression tests (U-GE-xx).

Reads golden run JSON files from tests/tenders/golden_run_tender_XXX.json
(produced by scripts/capture_pipeline_run.py) and compares the extracted
agv_criteria values against the golden_extraction fields in the corresponding
fixture file tests/tenders/tender_XXX.json.

If no golden run file exists for a tender, the test is skipped — the suite
never fails just because the LLM has not been run yet.

To generate a golden run file:
    python3 scripts/capture_pipeline_run.py tenders/Beispielausschreibung_AGV_Nordlicht.pdf

The test then verifies:
    golden_run['agv_criteria'][key] == fixture['golden_extraction'][key]
for every key in the fixture's golden_extraction dict.
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
    """Return all tests/tenders/tender_XXX.json files that have golden_extraction."""
    fixtures = []
    for f in sorted(_TENDER_DIR.glob("tender_*.json")):
        data = _load_json(f)
        if data.get("golden_extraction"):
            fixtures.append(f)
    return fixtures


@pytest.mark.parametrize("fixture_path", _fixture_files(), ids=lambda p: p.stem)
def test_golden_extraction(fixture_path: Path):
    """Compare agv_criteria in a golden run file against the fixture's golden_extraction.

    Skipped if no golden run file exists for this tender.
    """
    fixture = _load_json(fixture_path)
    tender_id = fixture["tender_id"]

    # Derive golden run file name: tender_004 → golden_run_tender_004.json
    golden_run_path = _TENDER_DIR / f"golden_run_{tender_id}.json"

    if not golden_run_path.exists():
        pytest.skip(
            f"No golden run file for {tender_id} — "
            f"run: python3 scripts/capture_pipeline_run.py {fixture.get('source_file', '?')}"
        )

    golden_run = _load_json(golden_run_path)
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
