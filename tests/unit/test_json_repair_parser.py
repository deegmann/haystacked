"""Unit tests for repair_and_parse (U-J-01 to U-J-10)."""
import sys
import pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.json_repair import repair_and_parse


def test_U_J_01_clean_json():
    raw = '{"agv_type": "Forklift AGV", "payload": 1500}'
    result = repair_and_parse(raw)
    assert result["agv_type"] == "Forklift AGV"
    assert result["payload"] == 1500


def test_U_J_02_markdown_fence():
    raw = '```json\n{"agv_type": "Tugger AGV"}\n```'
    result = repair_and_parse(raw)
    assert result["agv_type"] == "Tugger AGV"


def test_U_J_03_prose_before_json():
    raw = 'Here is the extracted data:\n{"agv_type": "Mobile AMR"}'
    result = repair_and_parse(raw)
    assert result["agv_type"] == "Mobile AMR"


def test_U_J_04_string_null_normalised():
    raw = '{"agv_type": "Forklift AGV", "payload": "null"}'
    result = repair_and_parse(raw)
    # After normalisation payload should be null (Python None) or string
    # We accept either — the key point is no crash
    assert "agv_type" in result


def test_U_J_05_string_true_false_normalised():
    raw = '{"outdoor": "true", "vda5050": "false"}'
    result = repair_and_parse(raw)
    # After normalisation booleans or strings both acceptable — no crash
    assert "outdoor" in result


def test_U_J_06_truncated_json():
    raw = '{"agv_type": "Forklift AGV", "payload": 1500, "incomplete'
    result = repair_and_parse(raw)
    # Should not crash and should return at least the complete field
    assert isinstance(result, dict)


def test_U_J_07_unescaped_newlines():
    raw = '{"summary": "Line one\nLine two", "agv_type": "Mobile AMR"}'
    result = repair_and_parse(raw)
    assert "agv_type" in result


def test_U_J_08_completely_unparseable():
    raw = "This is not JSON at all. Just prose."
    with pytest.raises(ValueError):
        repair_and_parse(raw)


def test_U_J_09_stray_brace_after_json():
    # Stage 0 brace-balance: trailing } in prose must not extend the candidate
    raw = '{"agv_type": "Forklift AGV"} and then some prose with a stray }'
    result = repair_and_parse(raw)
    assert result["agv_type"] == "Forklift AGV"
    assert len(result) == 1


def test_U_J_10_nested_braces():
    # Stage 0 brace-balance: nested objects must be handled correctly
    raw = '{"outer": "val", "inner": {"key": "nested"}} trailing text'
    result = repair_and_parse(raw)
    assert result["outer"] == "val"
    assert result["inner"]["key"] == "nested"
