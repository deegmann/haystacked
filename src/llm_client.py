# No domain/industry logic here. No field names, no AP0 values, no per-model prompt
# variants (see CLAUDE.md / R4). This module knows how to talk to an LLM provider,
# never what to ask it.
"""
LLM provider abstraction: local Ollama + OpenRouter cloud models, selectable per request.

`call_llm(system, user, label, model)` is the ONE function every pipeline call site
uses. There is no default for `model` — a forgotten call site is a Python TypeError,
never a silent fallback to local. That is real enforcement of the "one path per run"
invariant, not just convention.

Determinism note (R7): temp=0.0 gives no reproducibility guarantee on cloud providers
— no uniform seed across OpenRouter models, and provider-side batching/MoE routing can
vary output run-to-run even at temperature 0. Reproducibility (and therefore the golden-
run capture workflow) is a local-only property from here on.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime

import httpx

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional — OPENROUTER_API_KEY can also come from the real environment

log = logging.getLogger("haystacked.llm_client")


class LLMProviderError(RuntimeError):
    """Raised when a provider responds but the response itself is unusable (HTTP 200
    with an error body, empty/None content, no choices, ...) — i.e. R3's loud-failure
    conditions. Deliberately distinct from `httpx.HTTPError` (transport/status failures,
    which propagate unchanged) so callers can catch "the provider failed to answer" as
    one category, separate from "the model answered but parsing the answer failed"
    (a plain `ValueError`/`Exception` from `repair_and_parse()` downstream). See
    senior-architect post-implementation audit, 2026-08-25: conflating these two allowed
    a transport/provider failure to be laundered into hallucination-guard evidence."""

OLLAMA_URL      = "http://localhost:11434/api/generate"
OPENROUTER_URL  = "https://openrouter.ai/api/v1/chat/completions"

# Local Ollama calls keep today's 3600s timeout unchanged. OpenRouter gets its own,
# much shorter timeout — a stuck cloud call on a paid endpoint has no reason to run
# an hour (§4, Tech Lead decision 2026-08-25).
_OLLAMA_TIMEOUT_S     = 3600.0
_OPENROUTER_TIMEOUT_S = 300.0


@dataclass(frozen=True)
class LLMModelChoice:
    id: str                    # stable selector, e.g. "local-qwen2.5-7b", "openrouter-qwen2.5-72b"
    provider: str               # "ollama" | "openrouter"
    model_name: str             # provider-native model string, e.g. "qwen2.5:7b" / "qwen/qwen-2.5-72b-instruct"
    display_name: str           # UI label, e.g. "Qwen 2.5 7B (lokal, Ollama)"
    is_local: bool
    is_reasoning_model: bool    # R4 — must be False for every entry at launch
    context_tokens: int         # R1 — replaces the former module-level _OLLAMA_NUM_CTX
    max_output_tokens: int      # R1 — replaces the former hardcoded num_predict/max_tokens=4096
    weights_open: bool          # user requirement 2026-08-25 — must be True for every entry, always;
                                 # see curation rule below. A closed/API-only model (GPT-*, Claude,
                                 # Gemini, ...) may never be added, no matter how strong, because it
                                 # can never satisfy "runs locally with the right hardware."


AVAILABLE_MODELS: list[LLMModelChoice] = [
    LLMModelChoice("local-qwen2.5-7b", "ollama", "qwen2.5:7b",
                    "Qwen 2.5 7B (lokal, Ollama)", is_local=True,
                    is_reasoning_model=False, context_tokens=32_768, max_output_tokens=4096,
                    weights_open=True),
    LLMModelChoice("openrouter-qwen3.8-27b", "openrouter", "qwen/qwen3.8-27b",
                    "Qwen 3.8 27B (Cloud, OpenRouter)", is_local=False,
                    is_reasoning_model=False, context_tokens=1_000_000, max_output_tokens=4096,
                    weights_open=True),
    # User decision 2026-08-25: swapped in for the originally-planned Qwen 2.5 72B.
    # Open-weight (hugging_face_id "Qwen/Qwen3.8-27B" per OpenRouter's own model
    # metadata, description explicitly says "open-weight"), 1M-token context.
    #
    # is_reasoning_model=False here is a claim about OUR CONFIGURED USE of this entry,
    # not about the model's underlying capability: qwen/qwen3.8-27b is genuinely
    # reasoning-capable and defaults to reasoning ENABLED at "xhigh" effort on
    # OpenRouter (per its live /api/v1/models metadata, checked 2026-08-25) — which is
    # exactly what R4 excludes, since a <think>-style preamble would break
    # repair_and_parse()'s "first {, shortest balanced object" JSON extraction. This is
    # made safe, not just claimed safe, by _call_openrouter() sending
    # `"reasoning": {"enabled": false}` unconditionally on every OpenRouter call (see
    # that function) — OpenRouter's documented reasoning.enabled=false switch. NOT YET
    # LIVE-VERIFIED against a real API response as of this comment (verification
    # requires a paid call and explicit authorization, same gate as the DoD #4/R6
    # cloud comparison) — until that verification happens, treat this entry's
    # non-reasoning behavior as configured-but-unconfirmed, not proven.
    # Originally-planned slug "qwen/qwen-2.5-72b-instruct" (hyphen before "2.5" — an
    # earlier fix already caught the no-hyphen variant as wrong) was correct and live
    # but has been replaced per this swap, not because it was broken.
    LLMModelChoice("openrouter-llama3.3-70b", "openrouter", "meta-llama/llama-3.3-70b-instruct",
                    "Llama 3.3 70B (Cloud, OpenRouter)", is_local=False,
                    is_reasoning_model=False, context_tokens=131_072, max_output_tokens=4096,
                    weights_open=True),
    LLMModelChoice("openrouter-mistral-large", "openrouter", "mistralai/mistral-large-2512",
                    "Mistral Large 3 (Cloud, OpenRouter)", is_local=False,
                    is_reasoning_model=False, context_tokens=128_000, max_output_tokens=4096,
                    weights_open=True),
    # User decision 2026-08-25: seed with 3 cloud entries spanning different model families
    # (Qwen/Llama/Mistral) rather than just the one confirmed slug — lets the guard-layer
    # comparison (R6) distinguish "qwen-family quirk" from "generic stronger-model behavior".
    # All three slugs verified live against OpenRouter's own model pages 2026-08-25.
    #
    # CURATION RULE (user requirement, 2026-08-25): every AVAILABLE_MODELS entry must be an
    # open-weight model — one that could, with the right hardware, also run as a local Ollama
    # entry. No closed/API-only proprietary model (GPT-*, Claude, Gemini, etc.) is ever added,
    # regardless of quality, because it can NEVER satisfy that condition.
    #
    # Further entries go here only — but see R4: non-reasoning instruct models only at launch;
    # a reasoning/CoT model (e.g. anything emitting a <think> preamble or a wrapper object)
    # needs its own repair_and_parse() handling and is explicitly OUT of scope here.
]

DEFAULT_MODEL_ID = "local-qwen2.5-7b"   # preserves today's zero-config behaviour

_MODELS_BY_ID = {m.id: m for m in AVAILABLE_MODELS}


def resolve_model(model_id: str | None) -> LLMModelChoice:
    """R2 (senior-architect, required): an ABSENT (None or blank) model_id resolves to
    DEFAULT_MODEL_ID. An unknown/unavailable model_id is a hard error (raises ValueError,
    translated to HTTP 400 by the caller) — never a silent fallback to local. A run that
    silently executed local while the UI said cloud would produce a false quality verdict,
    which defeats the entire point of this feature."""
    if not model_id:
        return _MODELS_BY_ID[DEFAULT_MODEL_ID]
    model = _MODELS_BY_ID.get(model_id)
    if model is None:
        raise ValueError(
            f"Unknown model_id: {model_id!r}. Available: {sorted(_MODELS_BY_ID)}"
        )
    return model


async def call_llm(system: str, user: str, label: str, model: LLMModelChoice) -> str:
    """The ONE function every pipeline call site uses. Dispatches internally on
    model.provider to build the right request and parse the right response shape;
    callers never see the difference. No default for `model` — a forgotten call
    site is a TypeError, not a silent fallback to local. That is real enforcement
    of the "one path per run" invariant, not just convention.
    """
    log.info("LLM [%s] via %s/%s: system=%d Z., prompt=%d Z.",
              label, model.id, model.provider, len(system), len(user))
    t0 = datetime.now()
    if model.provider == "ollama":
        raw = await _call_ollama(system, user, model)
    elif model.provider == "openrouter":
        raw = await _call_openrouter(system, user, model)
    else:
        raise ValueError(f"Unknown provider: {model.provider!r} for model {model.id!r}")
    elapsed = (datetime.now() - t0).total_seconds()
    log.info("LLM [%s]: %.1fs, %d Z. Antwort", label, elapsed, len(raw))
    _debug_log_raw(label, model, raw)
    return raw


_RAW_LOG_PATH = os.environ.get("HAYSTACKED_LLM_RAW_LOG")


def _debug_log_raw(label: str, model: LLMModelChoice, raw: str) -> None:
    """Opt-in raw-completion logging for manual output-quality inspection (e.g.
    comparing a new cloud model's raw text against the local baseline). No-op unless
    HAYSTACKED_LLM_RAW_LOG points to a file. Never allowed to break a real analysis
    run — any failure here is swallowed, not raised. No domain logic: writes the raw
    string verbatim, does not parse or interpret it."""
    if not _RAW_LOG_PATH:
        return
    try:
        with open(_RAW_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 80}\n[{datetime.now().isoformat(timespec='seconds')}] "
                     f"label={label} model={model.id} ({model.provider})\n{'-' * 80}\n")
            f.write(raw)
            f.write("\n")
    except Exception:
        pass


async def _call_ollama(system: str, user: str, model: LLMModelChoice) -> str:
    # native /api/generate payload, exactly today's call_ollama() body — this is the
    # path with production-proven temp=0.0 determinism behind it (see module rationale)
    payload = {
        "model": model.model_name,
        "system": system,
        "prompt": user,
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": model.max_output_tokens,
                     "num_ctx": model.context_tokens},
    }
    async with httpx.AsyncClient(timeout=_OLLAMA_TIMEOUT_S) as client:
        resp = await client.post(OLLAMA_URL, json=payload)
        resp.raise_for_status()
    return resp.json().get("response", "")


def _openrouter_api_key() -> str | None:
    return os.environ.get("OPENROUTER_API_KEY") or None


async def _call_openrouter(system: str, user: str, model: LLMModelChoice) -> str:
    # OpenAI-compatible /chat/completions payload against
    # https://openrouter.ai/api/v1/chat/completions, Bearer auth from
    # OPENROUTER_API_KEY, messages=[{system},{user}], temperature=0.0,
    # max_tokens=model.max_output_tokens; parse choices[0].message.content per R3.
    api_key = _openrouter_api_key()
    if not api_key:
        raise LLMProviderError(
            "OPENROUTER_API_KEY is not set — required to call an OpenRouter model."
        )
    payload = {
        "model": model.model_name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.0,
        "max_tokens": model.max_output_tokens,
        # R4 enforcement at the request level (2026-08-25): OpenRouter's unified
        # "reasoning" parameter is sent unconditionally on every OpenRouter call, not
        # branched per model id — every AVAILABLE_MODELS entry asserts
        # is_reasoning_model=False, so every call must actually suppress reasoning
        # output, regardless of whether the underlying model is reasoning-capable and
        # defaults it on (e.g. qwen/qwen3.8-27b defaults to default_effort="xhigh").
        # A model that ignores/doesn't support this field treats it as a harmless
        # no-op (OpenRouter's own normalized schema, not the raw provider API).
        "reasoning": {"enabled": False},
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=_OPENROUTER_TIMEOUT_S) as client:
        resp = await client.post(OPENROUTER_URL, json=payload, headers=headers)
        # R3: raise on non-200 ...
        resp.raise_for_status()
    data = resp.json()
    # R3: ... raise on an OpenRouter HTTP-200-with-`error`-body response — raise_for_status()
    # alone will NOT catch this, since the HTTP status itself is 200.
    if isinstance(data, dict) and data.get("error"):
        raise LLMProviderError(f"OpenRouter returned an error body: {data['error']!r}")
    choices = data.get("choices") or []
    if not choices:
        raise LLMProviderError("OpenRouter response has no 'choices'.")
    message = choices[0].get("message") or {}
    content = message.get("content")
    # R3: raise on missing/empty/None choices[0].message.content — an empty completion
    # flows into repair_and_parse() -> {} -> "all fields null" -> a clean guard pass with
    # zero criteria -> a plausible-looking, entirely empty match result. Must be visible.
    if not content:
        raise LLMProviderError("OpenRouter response has missing/empty/None message content.")
    finish_reason = choices[0].get("finish_reason")
    if finish_reason == "length":
        # R3: at minimum warn-log — 4b emits ~80 keys against a 4096-token cap, not
        # generous headroom.
        log.warning("OpenRouter model=%s: finish_reason=length — response may be "
                    "truncated (max_output_tokens=%d).", model.id, model.max_output_tokens)
    return content


async def _ollama_manifest() -> list[str] | None:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://localhost:11434/api/tags")
            r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return None


async def list_provider_status() -> list[dict]:
    """id/display_name/provider/available bool per AVAILABLE_MODELS entry —
    local: live ping to Ollama /api/tags + model-in-manifest check;
    cloud: OPENROUTER_API_KEY presence (no live ping needed)."""
    manifest = None
    manifest_checked = False
    statuses = []
    for m in AVAILABLE_MODELS:
        if m.provider == "ollama":
            if not manifest_checked:
                manifest = await _ollama_manifest()
                manifest_checked = True
            if manifest is None:
                available, reason = False, "Ollama nicht erreichbar"
            elif m.model_name not in manifest:
                available, reason = False, "Modell nicht installiert"
            else:
                available, reason = True, None
        elif m.provider == "openrouter":
            if _openrouter_api_key():
                available, reason = True, None
            else:
                available, reason = False, "kein API-Key"
        else:
            available, reason = False, "unbekannter Provider"
        statuses.append({
            "id": m.id,
            "display_name": m.display_name,
            "provider": m.provider,
            "is_local": m.is_local,
            "available": available,
            "reason": reason,
        })
    return statuses
