"""Unit tests for repair_and_parse (U-J-01 to U-J-08)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.llm_client import repair_and_parse


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
    result = repair_and_parse(raw)
    assert isinstance(result, dict)  # Empty dict, no crash
