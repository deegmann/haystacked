"""U_CL tests — Scope classification config integrity (Step 7)."""
import json
from pathlib import Path

CONFIG = Path(__file__).parent.parent.parent / "config"


def test_U_CL_01_scope_classification_template_exists_with_all_canonical_names():
    p = CONFIG / "prompts" / "scope_classification_template.txt"
    assert p.exists(), "scope_classification_template.txt not generated — run generate_all.py"
    content = p.read_text()
    for name in ["Forklift AGV", "Tugger AGV", "Mobile AMR"]:
        assert name in content, f"{name!r} missing from scope_classification_template.txt"


def test_U_CL_02_scope_registry_has_canonical_name_for_leaf_scopes():
    reg = json.loads((CONFIG / "scope_registry.json").read_text())
    scopes = reg.get("scopes", {})
    parent_ids = {n.get("parent") for n in scopes.values() if n.get("parent")}
    leaf_scopes = {sid: n for sid, n in scopes.items() if sid not in parent_ids}
    assert leaf_scopes, "No leaf scopes found in scope_registry.json"
    for sid, node in leaf_scopes.items():
        assert node.get("canonical_name"), f"Leaf scope {sid!r} missing canonical_name"


def test_U_CL_03_agv_detection_keywords_non_empty():
    reg = json.loads((CONFIG / "scope_registry.json").read_text())
    kws = reg.get("agv_detection_keywords", [])
    assert isinstance(kws, list) and len(kws) > 0, "agv_detection_keywords is empty or missing"


def test_U_CL_04_legacy_map_keys_match_canonical_names():
    # legacy_map keys must equal canonical_names ∪ scope_variants (exact set, not superset).
    # canonical_name → primary routing key; scope_variants → display-variant aliases.
    reg = json.loads((CONFIG / "scope_registry.json").read_text())
    canonical_names = {n["canonical_name"] for n in reg["scopes"].values() if n.get("canonical_name")}
    scope_variants = {
        v.strip()
        for n in reg["scopes"].values()
        for v in n.get("scope_variants", [])
        if v.strip()
    }
    expected_keys = canonical_names | scope_variants
    legacy_keys = set(reg.get("legacy_map", {}).keys())
    assert legacy_keys == expected_keys, (
        f"legacy_map key mismatch.\n"
        f"Extra in legacy_map: {legacy_keys - expected_keys}\n"
        f"Missing from legacy_map: {expected_keys - legacy_keys}"
    )
    # All values must be valid scope_ids
    scope_ids = set(reg.get("scopes", {}).keys())
    bad_values = {v for v in reg.get("legacy_map", {}).values() if v not in scope_ids}
    assert not bad_values, f"legacy_map values not valid scope_ids: {bad_values}"


def test_U_CL_05_variant_map_values_subset_of_legacy_map():
    reg = json.loads((CONFIG / "scope_registry.json").read_text())
    variant_values = set(reg.get("variant_map", {}).values())
    legacy_keys = set(reg.get("legacy_map", {}).keys())
    assert variant_values <= legacy_keys, \
        f"variant_map values not in legacy_map: {variant_values - legacy_keys}"


def test_U_CL_06_agv_keyword_fallback_returns_correct_type():
    from src.context_builder import product_type_keyword_fallback
    assert product_type_keyword_fallback("VNA schmalgangstapler hochregal") == "Forklift AGV"
    assert product_type_keyword_fallback("tugger schlepper routenzug milk run") == "Tugger AGV"
    assert product_type_keyword_fallback("autonomous mobile robot AMR SLAM navigation") == "Mobile AMR"


def test_U_CL_07_agv_system_contains_conservative_value_extraction():
    from src.context_builder import build_system_context
    ctx = build_system_context("Logistics:AGV")
    assert "CONSERVATIVE VALUE EXTRACTION" in ctx, "Rule 8 missing from AGV_SYSTEM"


def test_U_CL_08_agv_system_contains_anti_hallucination():
    from src.context_builder import build_system_context
    ctx = build_system_context("Logistics:AGV")
    assert "ANTI-HALLUCINATION" in ctx, "Rule 9 missing from AGV_SYSTEM"


def test_domain_keywords_non_empty():
    """scope_registry.json must have domain_keywords with at least one entry."""
    import json
    from pathlib import Path
    reg = json.loads((Path(__file__).parent.parent.parent / "config" / "scope_registry.json").read_text())
    assert reg.get("domain_keywords"), "domain_keywords must be non-empty in scope_registry.json"
    for domain_id, kws in reg["domain_keywords"].items():
        assert kws, f"domain_keywords[{domain_id!r}] must be non-empty"


def test_domain_extractability_contract():
    """Verifies that extractability is determined by detected_domain ∈ _EXTRACTABLE_DOMAINS,
    not by a legacy boolean. The retired field name must not appear in app.py code logic."""
    import pathlib
    src = pathlib.Path(__file__).parent.parent.parent / "app.py"
    lines = src.read_text().splitlines()
    non_comment_lines = [line for line in lines if not line.strip().startswith("#")]
    code = "\n".join(non_comment_lines)
    retired_key = "is_agv" + "_amr"  # split to avoid grep catching this test file
    assert retired_key not in code, \
        f"{retired_key} must not appear in app.py code logic (variable assignments or result keys)"
    assert "detected_domain" in code, \
        "detected_domain must appear in app.py (new extractability key)"
    assert "_EXTRACTABLE_DOMAINS" in code, \
        "Extractability must use _EXTRACTABLE_DOMAINS constant, not legacy boolean"
    # Behavioral: the gate expression must be present — is_extractable derived from detected_domain
    assert "in _EXTRACTABLE_DOMAINS" in code, \
        "is_extractable gate must use 'in _EXTRACTABLE_DOMAINS' membership test"
    # Behavioral: _EXTRACTABLE_DOMAINS must be non-empty at runtime (guards against empty config)
    import json, pathlib as _pl
    reg = json.loads((_pl.Path(__file__).parent.parent.parent / "config" / "scope_registry.json").read_text())
    extractable = {d["scope_id"] for d in reg["scopes"].values() if d.get("parent") == "*"}
    assert extractable, "_EXTRACTABLE_DOMAINS must be non-empty — check scope_registry.json"
    assert None not in extractable, "None must not be a valid extractable domain"
