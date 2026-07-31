import json
from pathlib import Path

from src.context_builder import build_system_context
from src.field_spec import load_fields

_SCOPE_REGISTRY = json.loads((Path(__file__).parent.parent.parent / "config" / "scope_registry.json").read_text())
_EXTRACTABLE_DOMAINS = [sid for sid, node in _SCOPE_REGISTRY["scopes"].items() if node.get("parent") == "*"]


def test_build_system_context_excludes_user_description():
    """Regression test anchored to the 2026-07-30 lifting_height hallucination:
    user_description ('UI Hint') must never reach the LLM system prompt again."""
    ctx = build_system_context("Logistics:AGV")
    assert "10,000 mm" not in ctx
    assert "10 m for high-bay storage" not in ctx
    assert "lifting_height [KO]" in ctx


def test_build_system_context_never_leaks_any_user_description():
    """Structural version of the above: no KO/COND_KO field's user_description text
    may appear in any domain's system prompt, not just lifting_height's. Guards
    against a *different* field's UI Hint leaking in the future."""
    fields = load_fields()
    for domain_prefix in _EXTRACTABLE_DOMAINS:
        ctx = build_system_context(domain_prefix)
        for spec in fields.values():
            if spec.level not in ("KO", "COND_KO"):
                continue
            if not spec.user_description:
                continue
            assert spec.user_description not in ctx, (
                f"{spec.field_name}'s user_description leaked into the "
                f"{domain_prefix} system prompt: {spec.user_description!r}"
            )
