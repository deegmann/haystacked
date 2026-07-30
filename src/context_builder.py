"""
AP-I2 — Prompt Context Builder
Embeds the Industry Readme + field-level descriptions into the LLM system prompt.
Budget: ~20,000 tokens. Total context window: num_ctx=32768.
"""
import json
from pathlib import Path

BASE_DIR        = Path(__file__).parent.parent
_SCOPE_REGISTRY = BASE_DIR / "config" / "scope_registry.json"


def _load_readme(domain_sid: str) -> str:
    _slug = domain_sid.lower().replace(":", "_")
    _path = BASE_DIR / "config" / f"industry_readme_{_slug}.md"
    if _path.exists():
        return _path.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"industry_readme_{_slug}.md not found in config/ — run generate_all.py"
    )


def build_system_context(domain_prefix: str) -> str:
    readme = _load_readme(domain_sid=domain_prefix)
    from src.field_spec import load_fields
    _seen: set = set()
    ko_fields:   dict = {}
    cond_fields: dict = {}
    for _spec in load_fields().values():
        # Domain filter: include only global (*) and domain-relevant fields
        if domain_prefix is not None:
            if not (_spec.scope == "*"
                    or _spec.scope == domain_prefix
                    or _spec.scope.startswith(domain_prefix + ":")):
                continue
        if _spec.field_name in _seen:
            continue
        _seen.add(_spec.field_name)
        if _spec.level == "KO":
            ko_fields[_spec.field_name] = _spec
        elif _spec.level == "COND_KO":
            cond_fields[_spec.field_name] = _spec

    field_section = ""
    if ko_fields:
        # user_description ("UI Hint") intentionally excluded — UI-only column (Clarification
        # Dialog frontend), not LLM instruction text. Do not re-add for "readability" without
        # first re-auditing ALL KO/COND_KO user_description values for numeric literals (see
        # CLAUDE.md "No numeric literals in AP0 Description cells" — this caused a confirmed
        # hallucination on required_lifting_height_mm, 2026-07-30).
        lines = [f"  {field} [{spec.level}]" for field, spec in list(ko_fields.items()) + list(cond_fields.items())]
        field_section = "## Field-level descriptions (K.O. and Cond. K.O.)\n" + "\n".join(lines)

    _extr_system_path = BASE_DIR / "config" / "prompts" / "extraction_system.txt"
    extraction_rules = _extr_system_path.read_text(encoding="utf-8").strip() if _extr_system_path.exists() else ""

    context = f"""SYSTEM CONTEXT -- haystacked Matching Engine

## Industry domain knowledge
{readme}

{field_section}

## Critical matching rules
1. K.O. fields: a supplier failing even one K.O. criterion is fully excluded.
2. Cond. K.O. fields: score by default; hard filter ONLY when buyer marks them as "required".
3. Blank != zero: NULL means unknown, never absent. Do not infer a capability is absent because a field is empty. NULL reference_count is NOT 0 references.
4. OEM rebadging: same physical machine under multiple brand names shares technical specs.

{extraction_rules}
"""
    return context


def _load_product_type_keywords() -> dict:
    """Load keyword map from scope_registry.json (generated from AP0 ③ Scope Registry)."""
    if _SCOPE_REGISTRY.exists():
        reg = json.loads(_SCOPE_REGISTRY.read_text())
        return {
            node["canonical_name"]: [kw.strip() for kw in node.get("scope_keywords", [])]
            for node in reg.get("scopes", {}).values()
            if node.get("canonical_name") and node.get("scope_keywords")
        }
    return {}

PRODUCT_TYPE_KEYWORDS = _load_product_type_keywords()


def product_type_keyword_fallback(text: str) -> "str | None":
    """Independent from LLM. Checks first 5,000 chars. Per LL-05."""
    excerpt = text[:5000].lower()
    scores  = {
        t: sum(1 for kw in kws if kw in excerpt)
        for t, kws in PRODUCT_TYPE_KEYWORDS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None
