"""Unit tests for repair_and_parse (U-J-01 to U-J-10)."""
import sys
import pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.json_repair import repair_and_parse


def test_U_J_01_clean_json():
    raw = '{"product_type": "Forklift AGV", "payload": 1500}'
    result = repair_and_parse(raw)
    assert result["product_type"] == "Forklift AGV"
    assert result["payload"] == 1500


def test_U_J_02_markdown_fence():
    raw = '```json\n{"product_type": "Tugger AGV"}\n```'
    result = repair_and_parse(raw)
    assert result["product_type"] == "Tugger AGV"


def test_U_J_03_prose_before_json():
    raw = 'Here is the extracted data:\n{"product_type": "Mobile AMR"}'
    result = repair_and_parse(raw)
    assert result["product_type"] == "Mobile AMR"


def test_U_J_04_string_null_field_survives():
    raw = '{"product_type": "Forklift AGV", "payload": "null"}'
    result = repair_and_parse(raw)
    assert "product_type" in result and "payload" in result, (
        "Both fields must be present after parsing"
    )


def test_U_J_05_string_bool_fields_survive():
    raw = '{"outdoor": "true", "vda5050": "false"}'
    result = repair_and_parse(raw)
    assert "outdoor" in result and "vda5050" in result, (
        "Both fields must be present after parsing"
    )


def test_U_J_06_truncated_json():
    raw = '{"product_type": "Forklift AGV", "payload": 1500, "incomplete'
    result = repair_and_parse(raw)
    assert result.get("product_type") == "Forklift AGV", (
        "Complete field before truncation point must survive repair"
    )


def test_U_J_07_unescaped_newlines():
    raw = '{"summary": "Line one\nLine two", "product_type": "Mobile AMR"}'
    result = repair_and_parse(raw)
    assert "product_type" in result


def test_U_J_08_completely_unparseable():
    raw = "This is not JSON at all. Just prose."
    with pytest.raises(ValueError):
        repair_and_parse(raw)


def test_U_J_09_stray_brace_after_json():
    # Stage 0 brace-balance: trailing } in prose must not extend the candidate
    raw = '{"product_type": "Forklift AGV"} and then some prose with a stray }'
    result = repair_and_parse(raw)
    assert result["product_type"] == "Forklift AGV"
    assert len(result) == 1


def test_U_J_10_nested_braces():
    # Stage 0 brace-balance: nested objects must be handled correctly
    raw = '{"outer": "val", "inner": {"key": "nested"}} trailing text'
    result = repair_and_parse(raw)
    assert result["outer"] == "val"
    assert result["inner"]["key"] == "nested"
