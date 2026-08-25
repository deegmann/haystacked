# Spec: LLM Provider Abstraction (Ollama lokal + OpenRouter Cloud) + Modellauswahl
**Version:** v0.2
**Datum:** 2026-08-25
**Status:** IMPLEMENTIERT + POST-IMPLEMENTATION-REVIEW ABGESCHLOSSEN (senior-architect + ap0-architecture-guardian + reference-integrity-guardian, alle drei "approve as shippable"). Ein vom SA gefundener Blocker (Provider-Fehler wurden bei 4a/4b/4c verschluckt statt laut zu scheitern — bei 4c landete das sogar als Halluzinations-Beweis im Guard) wurde direkt vom Tech Lead gefixt und verifiziert. **Lokaler Pfad (Default) ist produktionsreif und identisch zum bisherigen Verhalten. Der reale Cloud-Vergleichslauf (DoD #4/R6) ist für `openrouter-qwen3.8-27b` UND `openrouter-deepseek-v4-flash` abgeschlossen** — siehe `docs/e2e_20260825_llm_provider_comparison/REPORT.md` bzw. `REPORT_deepseek_v4_flash.md` — **und wartet für die beiden übrigen Cloud-Modelle (Llama 3.3 70B, Mistral Large 3) noch auf explizite Freigabe.** DeepSeek-Test fand + fixte einen echten R3-Robustheitsfall (Whitespace-only-Response wurde nicht als leer erkannt — jetzt providerübergreifend gefixt, `src/llm_client.py`).

Reviews (Plan): senior-architect APPROVE WITH REQUIRED CHANGES (Ruling:
`.claude/agent-memory/senior-architect/decision_llm_provider_abstraction.md`) → ap0-architecture-guardian APPROVE AS-IS → reference-integrity-guardian APPROVE WITH REQUIRED ADDITIONS. Alle Auflagen eingearbeitet.

Reviews (Implementierung, post-impl. 2026-08-25): ap0-architecture-guardian **APPROVE AS SHIPPABLE** (keine Einwände) → reference-integrity-guardian **APPROVE AS SHIPPABLE** (alle 4 Auflagen korrekt gelandet, kein neuer Fund) → senior-architect **SIGN OFF WITH ONE REQUIRED FIX** (Ruling: `.claude/agent-memory/senior-architect/audit_llm_provider_abstraction_post_impl.md`) — Fix seither vom Tech Lead angewendet: `LLMProviderError` in `src/llm_client.py` eingeführt, an den 4a/4b/4c-Handlern in `app.py` ein früheres `except (LLMProviderError, httpx.HTTPError)` ergänzt, das den Lauf sauber mit einem SSE-`error`-Event abbricht statt ihn verschluckt fortzusetzen; bei 4c wird ein Provider-Fehler jetzt NIE mehr in `_4c_abstained` aufgenommen. Zusätzlich behoben: irreführende "Ollama not reachable"-Meldung bei Cloud-Verbindungsfehlern (Pass 1), ein Selbsttest (`test_cloud_marker_never_executes_without_explicit_opt_in`) macht die Kostenschutz-Marker-Mechanik strukturell statt nur angenommen.

**Nachtrag 2026-08-25 (nach Commit, echter API-Key erstmals verfügbar):** kostenloser Key-Check (`GET /api/v1/auth/key`, kein Token-Verbrauch) bestätigte einen gültigen, aktiven Key. Ein anschließender kostenloser Abgleich gegen `GET /api/v1/models` (ebenfalls kein Token-Verbrauch) deckte auf, dass der registrierte Slug `qwen/qwen2.5-72b-instruct` bei OpenRouter **nicht existiert** — korrekt ist `qwen/qwen-2.5-72b-instruct` (Bindestrich vor "2.5"), vermutlich ein Rechercheversehen aus der ursprünglichen Planungsphase. Vor jeglichem bezahlten Aufruf korrigiert und live gegengeprüft. Lehre: jeder neu registrierte Modell-Slug sollte künftig direkt gegen `GET /api/v1/models` verifiziert werden, nicht nur gegen eine Websuche.

**Nachtrag 2 2026-08-25 (User-Wunsch: Qwen 3.8 27B statt Qwen 2.5 72B):** `openrouter-qwen2.5-72b`
ersetzt durch `openrouter-qwen3.8-27b` (`qwen/qwen3.8-27b`, offene Gewichte laut
`hugging_face_id: Qwen/Qwen3.8-27B`, 1M-Token-Kontext). **Wichtiger Fund dabei:** dieses Modell
hat laut OpenRouters `GET /api/v1/models`-Metadaten Reasoning standardmäßig aktiviert
(`default_enabled: true`, `default_effort: "xhigh"`) — genau die Kategorie, die R4 beim
Plan-Review ausdrücklich ausgeschlossen hatte, weil ein `<think>`-artiger Vorspann
`repair_and_parse()`s "erste `{`, kürzestes balanciertes Objekt"-Extraktion bricht. Statt den
Swap abzulehnen (User-Entscheidung): `_call_openrouter()` sendet jetzt unconditional bei **jedem**
OpenRouter-Aufruf `"reasoning": {"enabled": false}` (OpenRouters dokumentierter Schalter) — nicht
modellspezifisch verzweigt, sondern als generelle Durchsetzung von R4 auf Request-Ebene. Damit
bleibt `is_reasoning_model=False` für diesen Eintrag eine Aussage über unsere KONFIGURIERTE
Nutzung, nicht über die Modell-Fähigkeit selbst — das Modell kann reasoning, wir schalten es
immer ab. **Nicht live verifiziert** (bräuchte einen bezahlten Aufruf + Freigabe, gleiches Gate
wie DoD #4/R6) — bis dahin gilt: konfiguriert-aber-unbestätigt, nicht bewiesen.

Key finding (senior-architect): **ein stärkeres Modell kann durch Layer 0 des Halluzinations-Guards SCHLECHTER abschneiden**, weil die Guard-Annahme des wörtlichen Zitierens im Prompt verankert ist, nicht im Code — stärkere Modelle weichen häufiger vom wörtlichen Zitat ab (Whitespace-/Bindestrich-Normalisierung, Tabelle→Prosa-Umformulierung, gelegentlich englische Antworten auf deutschen Ausschreibungen) als das 7B-Modell. Jedes neue Modell muss über Layer-Null-Zählungen bewertet werden (R6), nie über reine Füllquote. Falls ein Modell Layer 0 in die Höhe treibt: Fix liegt im Prompt via AP0 — niemals eine Guard-Lockerung, niemals modellspezifische Logik in `src/json_repair.py`.

## 0. Problem / Goal

User is unhappy with hallucination/flakiness of the local `qwen2.5:7b` model and wants the
option to run the exact same pipeline against stronger cloud models via OpenRouter, while
keeping local Ollama available for offline/no-cost use. Requirement: **all** LLM calls in the
pipeline must go through **one** code path — never half Ollama / half something else within a
single run. A model must be selectable **before** an analysis starts (per-request, not a global
server restart).

## 1. Current state (verified by direct code inspection, 2026-08-25)

All *runtime* pipeline LLM calls already funnel through a single function:
`call_ollama(system, user, label)` at [app.py:481](app.py#L481), called from exactly these 11
call sites inside the `/analyze` SSE generator:

| Line | Label | Pass |
|---|---|---|
| 701 | basic | 1. basic_extraction |
| 738 | contact | 2. contact_fallback |
| 763 | nace | 3. nace_classification |
| 788 | domain_detect | domain detection |
| 854 | agv_4a | 4a. vehicle_type |
| 860 | agv_4a (retry) | 4a correction |
| 865 | agv_4a (retry) | 4a correction |
| 963 | agv_4b | 4b. agv_extraction |
| 969 | agv_4b_retry | 4b retry |
| 973 | agv_4b (retry) | 4b correction |
| 1067 | agv_4c_{field} | 4c. per_field_extraction (×~8) |

Constants: `OLLAMA_URL` (`http://localhost:11434/api/generate`), `OLLAMA_MODEL` (`"qwen2.5:7b"`),
`_OLLAMA_NUM_CTX` (32768) at [app.py:48-50](app.py#L48-L50). `call_ollama()` posts Ollama's
**native** `/api/generate` payload shape (`system`+`prompt` strings, `options.num_ctx`), not the
OpenAI-compatible shape.

Non-runtime code that duplicates Ollama-call knowledge (NOT part of the `/analyze` pipeline, but
relevant to "one path" and to plan cleanup scope):
- [scripts/test_pipeline.py:34-70](scripts/test_pipeline.py#L34) — standalone httpx call, own copy of payload building.
- [scripts/benchmark_models.py](scripts/benchmark_models.py) — switches models between benchmark runs by **regex-rewriting the `OLLAMA_MODEL` line inside app.py source** while the server is stopped, then restarting it. A functioning but fragile hack this refactor can retire.
- [tests/integration/test_llm_preflight.py:22-25](tests/integration/test_llm_preflight.py#L22) — regex-parses `OLLAMA_MODEL` out of app.py source to know which model to preflight-check.

Frontend: [templates/index.html:389-403](templates/index.html#L389) `handleFile()` builds a
`FormData` with only `file` and POSTs to `/analyze`. No model selector exists today. There is
also a JSON-replay path (`.json` upload) that bypasses the LLM entirely — unaffected by this
change.

Health check at [app.py:1461](app.py#L1461) pings `GET http://localhost:11434/api/tags`
specifically for Ollama liveness/model-availability.

`.env` currently holds only `AIRTABLE_TOKEN` / `AIRTABLE_BASE_ID` — no LLM provider secrets yet.

## 2. Proposed architecture

### 2.1 New module `src/llm_client.py` (mirrors existing `src/*.py` module pattern)

**ap0-architecture-guardian (approved as-is; recommended safeguard, folded in as required):** the
module's first line must be an explicit invariant header, mirroring the pattern already used for
`source_confirms_value()`/`source_is_grounded()` in `src/json_repair.py` — e.g. `# No
domain/industry logic here. No field names, no AP0 values, no per-model prompt variants (see
CLAUDE.md / R4). This module knows how to talk to an LLM provider, never what to ask it.` Cheap,
and this is a brand-new file with no institutional scar tissue yet to lean on otherwise.

**STATUS 2026-08-25: the block below is the AS-BUILT registry** (kept in sync after the
Qwen-3.8-27B swap in "Nachtrag 2" above and the reasoning-off enforcement it required — see
`src/llm_client.py` for the authoritative, currently-running version; this copy is updated
whenever that file changes materially, but treat the source file as ground truth if they ever
drift).

```python
@dataclass(frozen=True)
class LLMModelChoice:
    id: str               # stable selector, e.g. "local-qwen2.5-7b", "openrouter-qwen3.8-27b"
    provider: str          # "ollama" | "openrouter"
    model_name: str        # provider-native model string, e.g. "qwen2.5:7b" / "qwen/qwen3.8-27b"
    display_name: str      # UI label, e.g. "Qwen 2.5 7B (lokal, Ollama)"
    is_local: bool
    is_reasoning_model: bool  # R4 — see below; must be False for every entry at launch
    context_tokens: int    # R1 — replaces the module-level _OLLAMA_NUM_CTX
    max_output_tokens: int # R1 — replaces the hardcoded num_predict/max_tokens=4096
    weights_open: bool     # user requirement 2026-08-25 — must be True for every entry, always;
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
    #
    # CURATION RULE (user requirement, 2026-08-25): every AVAILABLE_MODELS entry must be an
    # open-weight model — one that could, with the right hardware, also run as a local Ollama
    # entry. No closed/API-only proprietary model (GPT-*, Claude, Gemini, etc.) is ever added,
    # regardless of quality, because it can NEVER satisfy that condition. Verified 2026-08-25:
    #   - Qwen 3.8 27B: open weights (hugging_face_id "Qwen/Qwen3.8-27B" per OpenRouter's own
    #     model metadata), dense 27B, 1M-token context. Reasoning-capable and defaults to
    #     reasoning ENABLED on OpenRouter (default_effort "xhigh") — handled by sending
    #     `"reasoning": {"enabled": false}` unconditionally on every OpenRouter call (see
    #     `_call_openrouter()`), not by excluding the model. Live-verified 2026-08-25 against a
    #     real 8-tender comparison run: zero reasoning/`<think>` leakage in the raw output —
    #     see `docs/e2e_20260825_llm_provider_comparison/`.
    #   - Llama 3.3 70B Instruct: open weights (Meta Llama 3.3 Community License, permits local
    #     use), in Ollama's library today (`ollama pull llama3.3:70b-instruct-q4_K_M`).
    #   - Mistral Large 3 (2512): open weights, Apache 2.0 (mistralai/Mistral-Large-3-675B-
    #     Instruct-2512 on Hugging Face) — NOT yet confirmed present in Ollama's official
    #     library as of 2026-08-25 (new, Dec-2025-era release); would need a manual GGUF
    #     import via a custom Modelfile to actually run locally today. Passes the open-weight
    #     test; local *convenience* lags the other two.
    # Practical hardware note: Qwen 3.8 27B needs roughly 14-17GB at 4-bit quantization (fits a
    # single 24GB consumer GPU); Llama 3.3 70B is a meaningfully bigger local footprint than the
    # 7B default but within reach of a serious single-workstation GPU setup. Mistral Large 3 is
    # a 675B-parameter MoE (41B active) — open-weight in principle, but "the right hardware" for
    # it in practice means a multi-GPU server, not a single machine. Flagged so the choice is
    # informed, not a surprise later; not a reason to drop it from the registry.
    # Further entries go here only — but see R4: non-reasoning-CAPABLE-by-default models only
    # at launch (see Qwen 3.8 27B note above: reasoning-*capable* is fine now that the
    # request-level reasoning-off enforcement is proven; a model whose reasoning cannot be
    # disabled via this switch, or one that emits a wrapper object instead of a think block,
    # still needs its own repair_and_parse() handling and is explicitly OUT of scope here.
    # DeepSeek's V4 family was specifically flagged during earlier research as having its own
    # reasoning quirks — treat as unverified for the reasoning-off switch until checked the same
    # way Qwen 3.8 27B was). Gemini 2.5 Flash was considered and deliberately excluded at launch
    # both for its configurable thinking budget AND because it is closed-weight (fails the
    # curation rule above on its own, independent of the reasoning-model concern).
]
DEFAULT_MODEL_ID = "local-qwen2.5-7b"   # preserves today's zero-config behaviour

def resolve_model(model_id: str | None) -> LLMModelChoice:
    """R2 (senior-architect, required): an ABSENT model_id resolves to DEFAULT_MODEL_ID.
    An unknown/unavailable model_id is a hard error (HTTP 400), never a silent fallback to
    local — a run that silently executed local while the UI said cloud would produce a false
    quality verdict, which defeats the entire point of this feature."""
    ...

async def call_llm(system: str, user: str, label: str, model: LLMModelChoice) -> str:
    """The ONE function every pipeline call site uses. Dispatches internally on
    model.provider to build the right request and parse the right response shape;
    callers never see the difference. No default for `model` — a forgotten call
    site is a TypeError, not a silent fallback to local. That is real enforcement
    of the "one path per run" invariant, not just convention.

    R3 (senior-architect, required) — must fail loudly, not produce a silently-empty
    result: raise on non-200, raise on an OpenRouter HTTP-200-with-`error`-body response
    (raise_for_status() alone will NOT catch this), raise on missing/empty/None
    `choices[0].message.content`, and at minimum warn-log when `finish_reason == "length"`
    (4b emits ~80 keys against a 4096-token cap — not generous headroom). Rationale: an
    empty completion flows into repair_and_parse() -> {} -> "all fields null" -> a clean
    guard pass with zero criteria -> a plausible-looking, entirely empty match result.
    That failure must be visible, never silent.
    """
    if model.provider == "ollama":
        # native /api/generate payload, exactly today's call_ollama() body — this is the
        # path with production-proven temp=0.0 determinism behind it (see rationale below)
        ...
    elif model.provider == "openrouter":
        # OpenAI-compatible /chat/completions payload against
        # https://openrouter.ai/api/v1/chat/completions, Bearer auth from
        # OPENROUTER_API_KEY, messages=[{system},{user}], temperature=0.0,
        # max_tokens=model.max_output_tokens; parse choices[0].message.content per R3.
        ...

async def list_provider_status() -> list[dict]:
    """id/display_name/provider/available bool per AVAILABLE_MODELS entry —
    local: live ping to Ollama /api/tags + model-in-manifest check;
    cloud: OPENROUTER_API_KEY presence (no live ping needed)."""
```

**R1 (senior-architect, required) — context window is a per-model capability, not a global
constant.** `_OLLAMA_NUM_CTX` is not just a request parameter today: `app.py:943` uses it as the
document-size warning gate, and the `max_chars = 50_000` truncation at `app.py:681` is derived
from the same 32k-token budget (comment at `app.py:680`). §2.2 below reads
`chosen_model.context_tokens` at that gate instead of the deleted global. **Explicit, undecided
question carried into §4:** does `max_chars` stay a flat 50 000 chars for every model, including
a large-context cloud model? If yes, say so out loud — it caps exactly the quality upside a
bigger-context cloud model is being bought for, and that must be a stated tradeoff, not an
accident of not touching that line.

**Determinism note (R7, senior-architect):** temp=0.0 gives no reproducibility guarantee on
cloud providers — no uniform seed across OpenRouter models, and provider-side batching/MoE
routing can vary output run-to-run even at temp 0. **Reproducibility becomes a local-only
property from here on** — state this plainly in the CLAUDE.md update (DoD #7), since the golden-
capture workflow (`scripts/capture_pipeline_run.py`, `tests/unit/test_golden_extraction.py`)
silently assumes determinism today.

Design decision — **why not unify on one wire format** (Ollama also exposes an
OpenAI-compatible `/v1/chat/completions`, which was considered): Ollama's compat layer has a
known open issue where request-level `temperature` handling on `/v1/chat/completions` is not
fully reliable (ollama/ollama#17744 covers the Modelfile-default case; behaviour of an
explicitly-*sent* `temperature=0.0` there hasn't been proven yet in this repo). Since
`temperature=0.0` determinism directly matters for the hallucination guard's diagnostic tests, we
keep local calls on Ollama's **native** `/api/generate` (already proven deterministic in
production) and only use the OpenAI-compatible shape for OpenRouter. "One path" is delivered at
the **Python call-site level** — every pipeline line calls `call_llm(...)` and nothing else — not
at the wire-format level. This should be re-examined once the Ollama compat layer is verified
stable; not a blocker now.

### 2.2 `app.py` changes

- Remove `OLLAMA_URL` / `OLLAMA_MODEL` / `_OLLAMA_NUM_CTX` module constants and the `call_ollama()`
  function body; `from src.llm_client import call_llm, resolve_model, AVAILABLE_MODELS,
  DEFAULT_MODEL_ID, list_provider_status`.
- `POST /analyze` gains an optional form field `model_id: str | None`. At the top of `stream()`:
  `chosen_model = resolve_model(model_id)`. Every one of the 11 call sites changes from
  `await call_ollama(sys, user, label)` to `await call_llm(sys, user, label, chosen_model)`.
- SSE progress messages that interpolate `OLLAMA_MODEL` (e.g. [app.py:694](app.py#L694)) switch
  to `chosen_model.display_name`, and the chosen model is logged once at the start of the run.
- New `GET /api/llm-models` route returning `list_provider_status()` for the frontend dropdown.
- `/health`(-adjacent) endpoint at [app.py:1461](app.py#L1461): keep the existing Ollama-specific
  check (still meaningful — the default model is local) but stop treating "Ollama down" as fatal
  when the caller's stated intent is a cloud model; report both providers' status.
  **reference-integrity-guardian (required):** two more lines inside that same function body read
  the constant §2.2 deletes — [app.py:1463](app.py#L1463) `model_ok = OLLAMA_MODEL in models` and
  [app.py:1467](app.py#L1467) `"model": OLLAMA_MODEL`. This is a second hard `NameError` break
  inside a file the plan already touches, not just a behavioral rewrite — both lines become
  per-entry over `AVAILABLE_MODELS` from `src.llm_client`, not a leftover single constant.
- Unknown/unavailable `model_id` on `POST /analyze` → HTTP 400 per R2, not a silent local
  fallback (only an *absent* field defaults).
- The chosen `model.id` is written into the result dict / SSE payload and into whatever
  `build_tender_run()`/`persist_tender_run()` (`src/tender_store.py`) writes to
  `tests/tenders/run_*.json`, per R5 — see §2.5.
- Cost/blast-radius (senior-architect Q4): 4b plus each of the ~8 4c calls carries the full
  (~50k-char) document, so a single tender run is roughly 200k input tokens on a paid model,
  before the existing 3-attempt retry loops at [app.py:854-865](app.py#L854) and
  [app.py:963-973](app.py#L963). Decide the client timeout for the OpenRouter branch explicitly
  (not silently inherit the local 3600s) and log a per-run call count / approximate token count
  at the end of `stream()` so an accidental expensive run is visible immediately, not discovered
  on the OpenRouter invoice.

### 2.3 Frontend (`templates/index.html`)

- On page load, `fetch('/api/llm-models')` and populate a `<select id="modelSelect">` in
  `uploadSection`, grouped via `<optgroup>` "Lokal (Ollama)" / "Cloud (OpenRouter)"; unavailable
  entries shown disabled with a reason (e.g. "Ollama nicht erreichbar" / "kein API-Key").
  Default selection = `DEFAULT_MODEL_ID`, remembered in `localStorage` between sessions **only
  when the remembered choice `is_local`** (senior-architect: a paid cloud selection must not
  silently survive into the next session/tab as the pre-selected default).
- `handleFile()` ([templates/index.html:389](templates/index.html#L389)) appends
  `form.append('model_id', selectedModelId)` before the existing POST.
- Log panel prints the chosen model's `display_name` as the first log line.

### 2.4 Config / secrets

- `.env`: add `OPENROUTER_API_KEY=` (documented as optional — only required to use any
  `openrouter-*` entry; local-only usage needs nothing new).
- No AP0/config-generation involvement: model choice is infrastructure, not domain/industry data,
  so it deliberately stays out of `generate_all.py` and `config/` — consistent with "No industry
  logic in Python" / AP0-SSoT boundary (this is the inverse: keep infra OUT of the SSoT meant for
  domain data).
- **Ruling (senior-architect, corollary to the above): no per-model prompt variants, ever** — not
  in AP0, not in `config/prompts/`. The prompts are the controlled variable in exactly the
  model-quality comparison this feature exists to enable; forking them per model both destroys
  the comparison and re-imports model-specific logic through the SSoT's back door. If a cloud
  model appears to need different prompting to behave well, that is a finding to escalate to the
  Tech Lead, not a config entry to quietly add.
- Note: `docs/test-report-2026-06-16.md:106` already cites a path `src/llm_client.py:18` — that
  reference predates this plan and is stale/unrelated; do not treat it as prior art or copy
  anything from around that citation while building the real module.

### 2.5 Tests

**Cost-safety default (user requirement 2026-08-25, HARD RULE):** `pytest tests/` — the normal,
default test invocation — must **never** make a real network call to OpenRouter and must
**never** spend paid tokens, unless a cloud run was explicitly requested. This is stronger than
"the frontend defaults to local" (§2.3) — it means the *test suite itself* cannot accidentally
burn money just by being run in CI or by a developer typing `pytest tests/`. Concretely:

- The repo has **no `conftest.py` today** (verified 2026-08-25) — this plan adds one at the repo
  root that registers a custom `cloud` pytest marker (`pytest.ini_options` / `pytest_configure`)
  and auto-skips any test carrying it **unless** an explicit opt-in is present: an env var
  `HAYSTACKED_RUN_CLOUD_TESTS=1` **and** `OPENROUTER_API_KEY` both set. Presence of the API key
  alone is deliberately NOT sufficient to trigger a cloud run — a developer may have the key
  configured for manual/frontend use without intending `pytest` to spend it.
- `tests/unit/test_llm_client.py` (below) is **fully mocked, zero real network calls of any
  kind** — this was already the design intent, now stated as a hard requirement, not an
  implementation detail: no `cloud` marker needed because nothing real is ever called.
- `tests/integration/test_llm_preflight.py`, after migration, must preflight-check only
  `DEFAULT_MODEL_ID` (the local model) by default. It must NOT iterate `AVAILABLE_MODELS` and
  ping every OpenRouter entry as part of a normal run — that would be a real (if cheap/free)
  network call to a paid provider on every plain `pytest tests/` invocation, which the hard rule
  above forbids regardless of per-call cost.
- `scripts/benchmark_models.py`'s `MODELS` list (line 63) stays **local-model-only by default**
  after migration — it already lists only `["qwen2.5:7b", "qwen2.5:14b"]` today, both Ollama
  models (verified 2026-08-25). Adding a cloud model to a benchmark run must require an explicit
  CLI flag (e.g. `--include-cloud`), never a silent addition to the default list.
- `scripts/capture_pipeline_run.py` posts to `/analyze` ([capture_pipeline_run.py:37](scripts/capture_pipeline_run.py#L37))
  without a model parameter today — after §2.2's change, an absent `model_id` resolves to
  `DEFAULT_MODEL_ID` (local) per R2, so this script needs **no change** to stay cost-safe; note it
  here so nobody "improves" it into passing a hardcoded cloud model_id as a new default later.
- **DoD #4 (R6's per-layer null-count comparison against a cloud model) is a manual, explicitly
  authorized one-time validation run performed during implementation review — NOT an automated
  regression test that becomes part of `pytest tests/` and re-runs (and re-spends) on every CI
  invocation or future test run.** Capture its output as a dated artifact (following this repo's
  existing pattern, e.g. `docs/e2e_<date>_llm_provider_cloud_comparison.md`), the same way prior
  E2E/benchmark runs are recorded (`docs/e2e_d2_ab_gate_20260728.md`,
  `docs/benchmark_findings_2026-06-14` per memory) — not as a new always-on pytest case.

- New `tests/unit/test_llm_client.py`: `resolve_model()` fallback behaviour for
  None/unknown/blank `model_id` (unknown → raises, per R2); per-provider payload construction and
  response parsing against mocked `httpx` responses (no real network/Ollama/OpenRouter calls),
  including the R3 failure-mode cases (non-200, HTTP-200-with-`error`-body, empty/None content,
  `finish_reason == "length"`); confirms `call_llm()` is a pure dispatcher with no
  provider-specific logic leaking into callers. **New assertion (user requirement 2026-08-25):**
  `assert all(m.weights_open for m in AVAILABLE_MODELS)` — a machine-checked guard against a
  closed/proprietary model ever being added to the registry, not just a comment-level rule.
- [tests/integration/test_llm_preflight.py](tests/integration/test_llm_preflight.py) updated to
  import `AVAILABLE_MODELS`/`DEFAULT_MODEL_ID` from `src.llm_client` instead of regex-parsing
  `OLLAMA_MODEL` out of app.py source. **Reclassified MANDATORY, not optional** (senior-architect):
  §2.2 deletes the `OLLAMA_MODEL` constant this file's regex depends on
  ([tests/integration/test_llm_preflight.py:25](tests/integration/test_llm_preflight.py#L25)) —
  leaving it unmigrated ships a knowingly-red test, not a neutral omission.
- [scripts/benchmark_models.py](scripts/benchmark_models.py): replace the app.py-source-rewrite
  hack with passing `model_id` per run (the server no longer needs restarting between models).
  **Reclassified MANDATORY, not optional** (senior-architect): its `MODEL_LINE_RE` regex-rewrite
  of `OLLAMA_MODEL` ([scripts/benchmark_models.py:69,112-119](scripts/benchmark_models.py#L69))
  hard `sys.exit`s the moment that constant is deleted — same reasoning as above.
- [scripts/test_pipeline.py](scripts/test_pipeline.py): **RESOLVED (Tech Lead decision,
  2026-08-25): explicitly deferred to a separate follow-up task, not part of this sprint's DoD.**
  It doesn't hard-depend on the deleted constants (own copy of the payload, not an import), so
  leaving it unmigrated for now doesn't break anything — it just means this one script keeps its
  own small duplicate of Ollama-call knowledge until the follow-up lands. Not to be silently
  forgotten: file a tracked open item so it doesn't quietly become permanent scope creep-by-omission.
- **R5 (senior-architect, required) — golden-run provenance.** `tests/tenders/run_*.json` records
  `source_file` / `captured_at` / `duration_s` but has no `model_id` field today, and
  `tests/unit/test_golden_extraction.py` has no notion of provenance. Add `model_id` to whatever
  `scripts/capture_pipeline_run.py` writes into the run capture doc, and make
  `test_golden_extraction.py` fail loudly (not silently pass) when a golden's `model_id !=
  DEFAULT_MODEL_ID` — a golden accidentally captured on a cloud model must never silently become
  the committed baseline. Cheap now, unrecoverable once mixed-provenance goldens exist in the repo.
- **R6 (senior-architect, required) — DoD #4 replacement.** "one PDF runs end-to-end" says
  nothing about guard behaviour, and per the Rev-2 header finding, field-fill counts alone can
  actively mislead (a stronger model can look *worse* through Layer 0 while actually
  hallucinating less). For at least one cloud model, run the existing tender corpus and record
  **per-layer null counts (L1 / L0 / L2 / L2_RESCUED)** side by side with the local baseline,
  using the `events` list already returned by `enforce_source_spans()`
  ([src/json_repair.py:568](src/json_repair.py#L568)) — no new instrumentation needed, just
  capture and diff what already exists.

## 3. Definition of Done

1. Zero direct `httpx` POSTs to any LLM endpoint remain in `app.py` outside `src/llm_client.py`.
2. All 11 pipeline call sites use `call_llm(..., chosen_model)`; `chosen_model` is resolved once
   per `/analyze` request from the submitted `model_id`, not from a module-level global.
3. No `model_id` submitted → identical behaviour to today (local `qwen2.5:7b`, same URL, same
   payload) — zero-config regression safety.
4. **STATUS 2026-08-25: DONE for two models (openrouter-qwen3.8-27b, openrouter-deepseek-v4-flash).** User-authorized live
   comparison run executed against the full 8-tender corpus, local `qwen2.5:7b` baseline vs.
   `openrouter-qwen3.8-27b`, with per-layer guard null counts (L1/L0/L2/L2_RESCUED) captured for
   both and compared side by side. Full methodology, results table, and findings:
   `docs/e2e_20260825_llm_provider_comparison/REPORT.md`. Reusable orchestration tool:
   `scripts/e2e_cross_model_comparison.py` (queries `tender_extraction_values.nulled_by` per
   run_id — no new instrumentation needed, R6's own suggested approach). Headline results: total
   guard nullings identical (3 vs. 3 across all 8 tenders) — **no evidence of the feared "stronger
   model triggers more Layer-0 nulls" pattern**; cloud model extracted substantially more fields
   on every AGV tender (e.g. CompanyX 1→10, Dragonfly 2→10) in ~3.5× less wall time; raw output
   (`qwen3.8-27b_raw_output.txt`) contains zero reasoning/`<think>` leakage, confirming the
   `reasoning: {"enabled": false}` request-level fix works; cost was $0.28 for the full run.
   **Follow-up 2026-08-25:** a second, deeper pass manually re-derived ground truth by reading
   all 8 source PDFs by hand and checking both models' raw completions against it — see
   `docs/e2e_20260825_llm_provider_comparison/GROUND_TRUTH_ANALYSIS.md`. Across 36 manually
   verified critical fields: cloud ≈99% correct, local ≈71%, including 2 confirmed local
   hallucinations (one caught live by the guard's Layer 1, a concrete real-world demonstration
   of it working) and fresh confirmation of two **already-documented, pre-existing** local-model
   issues from `docs/architecture.md` — §5.4 (Pass 4c's high abstention rate, now confirmed on
   more fields than originally documented, and confirmed absent on the cloud model in this run)
   and §5.6 (the temperature sign-flip bug, now with a documented no-citation sub-case caught by
   Layer 1). Corrected 2026-08-25: an earlier draft of this note mischaracterized both as new
   findings — they were not; only the specific fresh instances and the cloud-vs-local delta are
   new. A third pre-existing item was found the same way during the same review: OI-123
   (cooling-capacity ambiguity, IK Deep Freeze 280 vs. 340 kW) — see
   `GROUND_TRUTH_ANALYSIS.md`'s corrected text.
   **Second follow-up 2026-08-25 (DeepSeek V4 Flash, `openrouter-deepseek-v4-flash`, added to
   `AVAILABLE_MODELS` on user request):** same 8-tender comparison,
   `docs/e2e_20260825_llm_provider_comparison/REPORT_deepseek_v4_flash.md`. Matched or exceeded
   Qwen 3.8 27B on every critical field checked, including both IK Deep Freeze ambiguity traps
   and the previously-documented OI-122 (spelled-out German number word → correct kg value,
   "sechshundertfünfzig" → 650). Zero reasoning leakage confirmed (961 lines of raw output).
   Found and fixed a real R3 gap live: a whitespace-only OpenRouter response (`content=" "`)
   passed the old `if not content` check (non-empty Python string) — fixed with `.strip()`,
   regression-tested (`tests/unit/test_llm_client.py`), applies to every OpenRouter model, not
   DeepSeek-specific. One cross-model disagreement found, not a hallucination: IK Process
   Cooling's `temperature_min` — DeepSeek picked +2°C (the document's hard floor), Qwen and
   local both picked +4°C (the document's target capability) — both are literally-grounded
   readings of a genuinely ambiguous field semantics question, worth an AP0 hint clarification
   later, not a bug in any model. IK Cold Store `in_scope` disagreement in the opposite
   direction from the earlier Qwen-vs-local delta (DeepSeek=True, both others=False) — a third
   data point confirming domain classification is inconsistent across models on IK tenders,
   not yet root-caused.
   **Still open:** Llama 3.3 70B and Mistral Large 3 (the other two registered cloud entries)
   have not yet been run through this same comparison — same manual-run, explicit-authorization
   gate applies before spending money on them.
5. Frontend shows a model picker before upload; unavailable models are visibly disabled with a
   reason, not silently broken; a paid/cloud selection is never silently remembered as the
   next-session default (§2.3).
6. Unknown/unavailable `model_id` on `POST /analyze` is a hard 400 (R2); a cloud-provider call
   that returns HTTP 200 with an error body, or empty/None content, raises visibly rather than
   flowing into `repair_and_parse()` as a silently-empty result (R3).
7. `model_id` is recorded in the SSE result payload and in any golden run capture
   (`scripts/capture_pipeline_run.py`); `test_golden_extraction.py` fails loudly on a
   provenance mismatch rather than silently accepting a cloud-captured golden (R5).
8. `pytest tests/` green, including new `test_llm_client.py`, the migrated
   `test_llm_preflight.py`, and the migrated `scripts/benchmark_models.py`. **A plain `pytest
   tests/` run (no env vars set) makes zero real network calls to OpenRouter and spends zero
   paid tokens** — verify this explicitly (e.g. run with network access blocked/mocked at the
   `httpx` transport level, or run once with a deliberately invalid `OPENROUTER_API_KEY` and
   confirm nothing tries to use it) before sign-off, not just by reading the test code.
   **reference-integrity-guardian (required):** while editing that file for §2.5's migration, also
   fix the now-stray comment at
   [tests/integration/test_llm_preflight.py:72](tests/integration/test_llm_preflight.py#L72)
   ("Uses /api/generate (same endpoint as app.py call_ollama)") — cosmetic, but wrong prose once
   the import source changes; cheap to fix in the same edit.
9. CLAUDE.md's "Environment" and "Data Flow" sections updated: new env var, `src/llm_client.py`
   added to the module list, `call_ollama` references replaced, and an explicit note that
   **temp=0.0 reproducibility is a local-only property** (R7) — cloud runs are not guaranteed
   bit-for-bit reproducible even at temperature 0. **reference-integrity-guardian (required):**
   also update `docs/architecture.md` — unlike the dated point-in-time test-report snapshots
   (correctly out of scope), this is living prose asserting the current single-model design as
   fact, and three passages become false the moment a cloud model is selectable:
   `docs/architecture.md:20` ("qwen2.5:7b, running locally via Ollama — no data leaves the
   machine"), `:80` ("the tradeoff for running fully locally with no cloud API cost or
   data-sharing"), `:86` (ties the 50k-char truncation directly to "the model's context window is
   32,768 tokens" — now per-model, per R1). Additionally (ap0-architecture-guardian):
   `src/llm_client.py` added to the "Key Invariants" list of files that must never contain
   industry logic, alongside `source_confirms_value()`/`source_is_grounded()` — makes the
   boundary machine-checkable by future reviews instead of re-derived from scratch each time.
10. When a reasoning/CoT model is added later (explicitly deferred, §4) — any resulting
    `repair_and_parse()` changes must stay format-parsing logic only (how to unwrap a `<think>`
    block or wrapper object), never domain-value logic, and must not touch the field-agnostic
    invariants already documented for `source_confirms_value()`/`source_is_grounded()`
    (ap0-architecture-guardian safeguard).
11. Every `AVAILABLE_MODELS` entry has `weights_open=True` (user requirement 2026-08-25),
    enforced by the `test_llm_client.py` assertion above — no closed/proprietary API-only model
    is ever added to the registry, regardless of quality, since it could never satisfy "runs
    locally with the right hardware."
12. New root-level `conftest.py` registers the `cloud` pytest marker and auto-skips it unless
    `HAYSTACKED_RUN_CLOUD_TESTS=1` AND `OPENROUTER_API_KEY` are both set (user requirement
    2026-08-25, §2.5) — the mechanism that makes DoD #8's zero-real-cloud-calls guarantee
    structural rather than just a convention every future test author has to remember.

## 4. Open questions / explicit non-decisions (flagged, not silently resolved)

**Resolved by Tech Lead, 2026-08-25:**
- Starter `AVAILABLE_MODELS` set: **3 cloud entries** — `qwen/qwen3.8-27b` (swapped in for the
  originally-planned `qwen/qwen-2.5-72b-instruct` per "Nachtrag 2" above, user decision),
  `meta-llama/llama-3.3-70b-instruct`, `mistralai/mistral-large-2512` — spanning three model
  families. See §2.1 for the full, currently-accurate registry and the reasoning behind
  spanning families rather than seeding one.
- `scripts/test_pipeline.py` migration: deferred to a separate follow-up task, explicitly tracked
  rather than silently dropped. `benchmark_models.py` and `test_llm_preflight.py` remain
  mandatory in this sprint's DoD (R5 reclassification) since they hard-break once `OLLAMA_MODEL`
  is deleted.
- `Spec/haystacked_poc_offline_spec_v1_2.md`'s F-08 acceptance criterion
  (`"Kein Netzwerkaufruf ausser localhost:11434 (Ollama)"`, lines 974 & 1193, justified at line
  1220 as "Bewaehrt aus PoC v1 (Lesson LL-01)") is **amended, not silently overridden**: redefined
  as "local-only mode has no external network calls (unchanged guarantee); cloud mode
  (OpenRouter) is an explicit, user-initiated opt-in and is understood to leave the offline
  envelope." Added to the file-touch-list: amend F-08's text in the spec file itself (both the
  checklist line and the table row) so the spec doesn't read as silently violated by a future
  reader. No customer/compliance blocker was flagged — this was a PoC-era default, not a hard
  external constraint.

- **Per-provider timeout / `max_chars` truncation (R1):** local Ollama calls keep today's 3600s
  `httpx` client timeout unchanged. The OpenRouter branch of `call_llm()` uses a separate, shorter
  timeout — **300s** — since a stuck cloud call on a paid endpoint has no reason to run an hour;
  add it as a constant in `src/llm_client.py`, not a magic number inline. `max_chars` (the
  50 000-char PDF-text truncation at `app.py:681`) **stays flat for every model** for this sprint
  — do not make it per-model yet. Revisit only once a large-context cloud model's quality upside
  is actually measured under R6; tuning it now would be optimizing before there's data.
- `start.sh` / `setup.sh`'s Ollama-liveness hard-gate (senior-architect, minor/non-blocking): **out
  of scope for this sprint**, not silently dropped — a cloud-only user still gets a local Ollama
  server started today, which is a cosmetic annoyance, not a correctness or cost problem. File a
  tracked follow-up item; do not fix opportunistically inside this change (keeps the diff scoped
  to what was reviewed).

**Still open: none of the pre-implementation questions.** Every item that was open going into
implementation was resolved above before the developer started. Post-implementation, three
concrete backlog items remain — deliberately deferred, not forgotten (senior-architect
post-implementation follow-up #1, 2026-08-25):
1. **DoD #4 / R6's live cloud comparison run — DONE for `openrouter-qwen3.8-27b` and
   `openrouter-deepseek-v4-flash`, 2026-08-25** (see the STATUS line on DoD #4 in §3,
   `docs/e2e_20260825_llm_provider_comparison/REPORT.md`, and `REPORT_deepseek_v4_flash.md`).
   The DeepSeek run found and fixed a real gap in R3: a whitespace-only OpenRouter response
   (`content=" "`) was not caught by `if not content` (non-empty Python string), which on Pass
   4b (unlike "basic") would have silently degraded into an empty result instead of aborting
   loudly — fixed with `.strip()`, regression-tested, applies to every OpenRouter model, not
   just DeepSeek. Still needed: the same run for `openrouter-llama3.3-70b` and
   `openrouter-mistral-large` — same explicit-authorization-to-spend-money gate applies.
2. **`scripts/test_pipeline.py` migration** to `src.llm_client.call_llm` — still has its own
   independent, non-breaking `httpx` call (verified working as-is post-implementation).
3. **`start.sh` / `setup.sh`'s Ollama-liveness hard-gate** — cosmetic only (a cloud-only user
   still gets a local Ollama server started), not a correctness or cost problem.
