"""
Root-level pytest configuration.

Cost-safety hard rule (§2.5, spec_llm_provider_abstraction_v0_1.md): a plain `pytest
tests/` run must never make a real network call to OpenRouter and must never spend
paid tokens. Tests that genuinely need a live OpenRouter call must be marked `@pytest.mark.cloud`
— this marker is auto-skipped unless BOTH `HAYSTACKED_RUN_CLOUD_TESTS=1` and
`OPENROUTER_API_KEY` are set in the environment. Presence of the API key alone is
deliberately NOT sufficient — a developer may have the key configured for manual/
frontend use without intending `pytest` to spend it.
"""
import os

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "cloud: marks a test as requiring a real OpenRouter network call "
                   "(auto-skipped unless HAYSTACKED_RUN_CLOUD_TESTS=1 AND OPENROUTER_API_KEY are set)"
    )


def pytest_collection_modifyitems(config, items):
    cloud_opt_in = os.environ.get("HAYSTACKED_RUN_CLOUD_TESTS") == "1" and bool(
        os.environ.get("OPENROUTER_API_KEY")
    )
    if cloud_opt_in:
        return
    skip_cloud = pytest.mark.skip(
        reason="cloud test skipped — set HAYSTACKED_RUN_CLOUD_TESTS=1 and OPENROUTER_API_KEY "
               "to opt in to real OpenRouter calls"
    )
    for item in items:
        if "cloud" in item.keywords:
            item.add_marker(skip_cloud)
