"""Unit tests for src/llm_client.py — the LLM provider abstraction (local Ollama + OpenRouter).

Fully mocked, zero real network calls of any kind — no `cloud` marker needed because
nothing real is ever called (§2.5, spec_llm_provider_abstraction_v0_1.md). httpx.AsyncClient
is monkeypatched at the module level to a fake in-process stand-in for every test here.
"""
import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import llm_client
from src.llm_client import (
    AVAILABLE_MODELS,
    DEFAULT_MODEL_ID,
    LLMModelChoice,
    call_llm,
    list_provider_status,
    resolve_model,
)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Registry invariants (curation rule, user requirement 2026-08-25)
# ---------------------------------------------------------------------------

def test_all_models_weights_open():
    """Machine-checked guard: no closed/proprietary API-only model may ever be added
    to the registry, regardless of quality (§2.1, DoD #11)."""
    assert all(m.weights_open for m in AVAILABLE_MODELS)


def test_all_models_non_reasoning_at_launch():
    """R4: non-reasoning instruct models only at launch."""
    assert all(m.is_reasoning_model is False for m in AVAILABLE_MODELS)


def test_default_model_id_is_registered():
    assert DEFAULT_MODEL_ID in {m.id for m in AVAILABLE_MODELS}


def test_default_model_is_local():
    default = resolve_model(None)
    assert default.is_local is True
    assert default.provider == "ollama"


# ---------------------------------------------------------------------------
# resolve_model() — R2
# ---------------------------------------------------------------------------

def test_resolve_model_none_defaults():
    assert resolve_model(None).id == DEFAULT_MODEL_ID


def test_resolve_model_blank_defaults():
    assert resolve_model("").id == DEFAULT_MODEL_ID


def test_resolve_model_known_id_returns_that_model():
    m = resolve_model(_CLOUD_MODEL.id)
    assert m.id == _CLOUD_MODEL.id
    assert m.provider == "openrouter"


def test_resolve_model_unknown_raises():
    with pytest.raises(ValueError):
        resolve_model("totally-bogus-model-id")


# ---------------------------------------------------------------------------
# Fake httpx.AsyncClient — no real network calls, ever
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", "http://fake"),
                response=httpx.Response(self.status_code, request=httpx.Request("POST", "http://fake")),
            )

    def json(self):
        return self._json_data


class _FakeAsyncClient:
    """Minimal async-context-manager stand-in for httpx.AsyncClient.
    Class-level so tests can configure the next response before invoking code
    that constructs a fresh client instance per call, matching production usage."""
    next_response: _FakeResponse = _FakeResponse()
    last_call: dict = {}

    def __init__(self, *args, **kwargs):
        self._init_kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        _FakeAsyncClient.last_call = {"method": "post", "url": url, **kwargs}
        return _FakeAsyncClient.next_response

    async def get(self, url, **kwargs):
        _FakeAsyncClient.last_call = {"method": "get", "url": url, **kwargs}
        return _FakeAsyncClient.next_response


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Every test in this file runs against the fake client — guarantees zero real
    network calls regardless of which code path under test is exercised."""
    monkeypatch.setattr(llm_client, "httpx", type("_H", (), {
        "AsyncClient": _FakeAsyncClient,
        "HTTPStatusError": httpx.HTTPStatusError,
        "Request": httpx.Request,
        "Response": httpx.Response,
    }))
    _FakeAsyncClient.next_response = _FakeResponse()
    _FakeAsyncClient.last_call = {}
    yield


_LOCAL_MODEL = next(m for m in AVAILABLE_MODELS if m.provider == "ollama")
_CLOUD_MODEL = next(m for m in AVAILABLE_MODELS if m.provider == "openrouter")


# ---------------------------------------------------------------------------
# call_llm() — Ollama branch
# ---------------------------------------------------------------------------

def test_call_llm_ollama_builds_native_payload_and_returns_response_field():
    _FakeAsyncClient.next_response = _FakeResponse(200, {"response": "hello world"})
    out = _run(call_llm("SYS", "USER", "label", _LOCAL_MODEL))
    assert out == "hello world"
    call = _FakeAsyncClient.last_call
    assert call["url"] == llm_client.OLLAMA_URL
    payload = call["json"]
    assert payload["model"] == _LOCAL_MODEL.model_name
    assert payload["system"] == "SYS"
    assert payload["prompt"] == "USER"
    assert payload["stream"] is False
    assert payload["options"]["temperature"] == 0.0
    assert payload["options"]["num_predict"] == _LOCAL_MODEL.max_output_tokens
    assert payload["options"]["num_ctx"] == _LOCAL_MODEL.context_tokens


def test_call_llm_ollama_non_200_raises():
    _FakeAsyncClient.next_response = _FakeResponse(500, {})
    with pytest.raises(Exception):
        _run(call_llm("SYS", "USER", "label", _LOCAL_MODEL))


def test_call_llm_ollama_missing_response_key_returns_empty_string():
    """Matches today's call_ollama() behaviour exactly — .get("response", "")."""
    _FakeAsyncClient.next_response = _FakeResponse(200, {})
    out = _run(call_llm("SYS", "USER", "label", _LOCAL_MODEL))
    assert out == ""


# ---------------------------------------------------------------------------
# call_llm() — OpenRouter branch (R3 failure modes)
# ---------------------------------------------------------------------------

def _openrouter_ok_body(content="hello from the cloud", finish_reason="stop"):
    return {
        "choices": [
            {"message": {"content": content}, "finish_reason": finish_reason}
        ]
    }


def test_call_llm_openrouter_builds_openai_compatible_payload(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123")
    _FakeAsyncClient.next_response = _FakeResponse(200, _openrouter_ok_body())
    out = _run(call_llm("SYS", "USER", "label", _CLOUD_MODEL))
    assert out == "hello from the cloud"
    call = _FakeAsyncClient.last_call
    assert call["url"] == llm_client.OPENROUTER_URL
    assert call["headers"]["Authorization"] == "Bearer test-key-123"
    payload = call["json"]
    assert payload["model"] == _CLOUD_MODEL.model_name
    assert payload["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]
    assert payload["temperature"] == 0.0
    assert payload["max_tokens"] == _CLOUD_MODEL.max_output_tokens
    # R4 enforcement (2026-08-25): reasoning must be disabled on every OpenRouter
    # call, unconditionally — not just claimed via is_reasoning_model=False on a
    # model that may default reasoning to enabled (e.g. qwen/qwen3.8-27b).
    assert payload["reasoning"] == {"enabled": False}


def test_call_llm_openrouter_missing_api_key_raises_without_network_call(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        _run(call_llm("SYS", "USER", "label", _CLOUD_MODEL))
    assert _FakeAsyncClient.last_call == {}  # never even tried to call out


def test_call_llm_openrouter_non_200_raises(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123")
    _FakeAsyncClient.next_response = _FakeResponse(500, {})
    with pytest.raises(Exception):
        _run(call_llm("SYS", "USER", "label", _CLOUD_MODEL))


def test_call_llm_openrouter_200_with_error_body_raises(monkeypatch):
    """R3: raise_for_status() alone will NOT catch this — status is 200."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123")
    _FakeAsyncClient.next_response = _FakeResponse(200, {"error": {"message": "rate limited"}})
    with pytest.raises(RuntimeError):
        _run(call_llm("SYS", "USER", "label", _CLOUD_MODEL))


def test_call_llm_openrouter_no_choices_raises(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123")
    _FakeAsyncClient.next_response = _FakeResponse(200, {"choices": []})
    with pytest.raises(RuntimeError):
        _run(call_llm("SYS", "USER", "label", _CLOUD_MODEL))


@pytest.mark.parametrize("bad_content", [None, "", " ", "\n\t "])
def test_call_llm_openrouter_empty_or_none_content_raises(monkeypatch, bad_content):
    """Whitespace-only cases (2026-08-25): live evidence from the DeepSeek V4 Flash
    comparison run — a single-space response is a non-empty Python string (`not " "`
    is False), so the original `if not content` check let it through. Fixed with
    `.strip()`; regression-tested here so it can't silently reopen."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123")
    _FakeAsyncClient.next_response = _FakeResponse(200, _openrouter_ok_body(content=bad_content))
    with pytest.raises(RuntimeError):
        _run(call_llm("SYS", "USER", "label", _CLOUD_MODEL))


def test_call_llm_openrouter_finish_reason_length_warns_but_returns_content(monkeypatch, caplog):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123")
    _FakeAsyncClient.next_response = _FakeResponse(
        200, _openrouter_ok_body(content="truncated...", finish_reason="length")
    )
    with caplog.at_level("WARNING"):
        out = _run(call_llm("SYS", "USER", "label", _CLOUD_MODEL))
    assert out == "truncated..."
    assert any("finish_reason=length" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# call_llm() — pure dispatcher, no default for `model`
# ---------------------------------------------------------------------------

def test_call_llm_requires_model_argument():
    with pytest.raises(TypeError):
        call_llm("SYS", "USER", "label")  # missing required `model` arg


def test_call_llm_unknown_provider_raises():
    bogus = LLMModelChoice(
        id="bogus", provider="not-a-real-provider", model_name="x",
        display_name="x", is_local=False, is_reasoning_model=False,
        context_tokens=1000, max_output_tokens=100, weights_open=True,
    )
    with pytest.raises(ValueError):
        _run(call_llm("SYS", "USER", "label", bogus))


# ---------------------------------------------------------------------------
# list_provider_status()
# ---------------------------------------------------------------------------

def test_list_provider_status_local_available_when_in_manifest(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    _FakeAsyncClient.next_response = _FakeResponse(
        200, {"models": [{"name": _LOCAL_MODEL.model_name}]}
    )
    statuses = _run(list_provider_status())
    local_status = next(s for s in statuses if s["id"] == _LOCAL_MODEL.id)
    assert local_status["available"] is True
    assert local_status["reason"] is None


def test_list_provider_status_local_unavailable_when_ollama_unreachable(monkeypatch):
    class _Boom:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            raise ConnectionError("boom")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(llm_client, "httpx", type("_H", (), {"AsyncClient": _Boom}))
    statuses = _run(list_provider_status())
    local_status = next(s for s in statuses if s["id"] == _LOCAL_MODEL.id)
    assert local_status["available"] is False
    assert local_status["reason"] == "Ollama nicht erreichbar"


def test_list_provider_status_cloud_unavailable_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    _FakeAsyncClient.next_response = _FakeResponse(200, {"models": []})
    statuses = _run(list_provider_status())
    cloud_status = next(s for s in statuses if s["id"] == _CLOUD_MODEL.id)
    assert cloud_status["available"] is False
    assert cloud_status["reason"] == "kein API-Key"


def test_list_provider_status_cloud_available_with_api_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123")
    _FakeAsyncClient.next_response = _FakeResponse(200, {"models": []})
    statuses = _run(list_provider_status())
    cloud_status = next(s for s in statuses if s["id"] == _CLOUD_MODEL.id)
    assert cloud_status["available"] is True
    assert cloud_status["reason"] is None


# ---------------------------------------------------------------------------
# Self-test for conftest.py's cost-safety `cloud` marker (senior-architect
# post-implementation audit, 2026-08-25, follow-up #2): the skip mechanism was
# previously correct but entirely unexercised — nothing would have noticed if it
# silently broke. This test carries @pytest.mark.cloud, so a plain `pytest tests/`
# run (no HAYSTACKED_RUN_CLOUD_TESTS/OPENROUTER_API_KEY opt-in) must skip it
# without ever executing its body. If the skip logic in conftest.py is ever
# broken (marker unregistered, opt-in check inverted, ...), this test starts
# actually running and fails loudly instead of the breakage going unnoticed.
# ---------------------------------------------------------------------------

@pytest.mark.cloud
def test_cloud_marker_never_executes_without_explicit_opt_in():
    # Reached only if conftest.py's skip logic let this test run — fail loudly
    # unless BOTH opt-in conditions are genuinely present (i.e. this run really
    # was an intentional, explicitly-authorized cloud opt-in, not a broken skip).
    opted_in = (
        os.environ.get("HAYSTACKED_RUN_CLOUD_TESTS") == "1"
        and bool(os.environ.get("OPENROUTER_API_KEY"))
    )
    if not opted_in:
        pytest.fail(
            "This @pytest.mark.cloud test executed without the required opt-in "
            "(HAYSTACKED_RUN_CLOUD_TESTS=1 AND OPENROUTER_API_KEY) — the cost-safety "
            "skip mechanism in conftest.py is broken and real money may now be at "
            "risk on every plain `pytest tests/` run."
        )
