"""
Integration pre-flight tests — must pass before any LLM extraction test runs.

These tests require a live Ollama instance with qwen2.5:7b installed.
They are deliberately not in tests/unit/ because they need a running service.

Run with: pytest tests/integration/ -v
The session-scoped fixture blocks ALL integration tests if the model is missing.
"""
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

OLLAMA_URL   = "http://localhost:11434"
# Read from app.py to avoid drift — single source of model name
_APP         = Path(__file__).parent.parent.parent / "app.py"
REQUIRED_MODEL = next(
    (line.split("=")[1].strip().strip('"').strip("'")
     for line in _APP.read_text().splitlines()
     if line.startswith("OLLAMA_MODEL")),
    "qwen2.5:7b",
)


@pytest.fixture(scope="session", autouse=True)
def require_ollama_model():
    """Block all integration tests if the required model is not in the Ollama manifest.

    Checks /api/tags (manifest registry) — NOT just that Ollama is running.
    Catches the specific failure mode where the blob exists but the manifest
    was deleted (Ollama returns 404 on /api/generate in that state).
    """
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5.0)
        r.raise_for_status()
    except Exception as exc:
        pytest.exit(
            f"PREFLIGHT FAIL: Ollama not reachable at {OLLAMA_URL} — {exc}\n"
            f"Start it with: ollama serve",
            returncode=1,
        )

    available = [m["name"] for m in r.json().get("models", [])]
    if REQUIRED_MODEL not in available:
        pytest.exit(
            f"PREFLIGHT FAIL: Required model '{REQUIRED_MODEL}' not in Ollama manifest.\n"
            f"Available models: {available}\n"
            f"Fix: ollama pull {REQUIRED_MODEL}",
            returncode=1,
        )


def test_I_S_01_model_in_manifest():
    """qwen2.5:7b must be present in the Ollama manifest (/api/tags)."""
    r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5.0)
    assert r.status_code == 200
    available = [m["name"] for m in r.json().get("models", [])]
    assert REQUIRED_MODEL in available, (
        f"Model '{REQUIRED_MODEL}' not found in Ollama manifest. "
        f"Available: {available}. Run: ollama pull {REQUIRED_MODEL}"
    )


def test_I_S_02_model_json_smoke():
    """qwen2.5:7b must respond to a minimal prompt with parseable JSON.

    Uses /api/generate (same endpoint as app.py call_ollama).
    Verifies the full inference path: manifest → weights loaded → JSON output.
    """
    payload = {
        "model": REQUIRED_MODEL,
        "prompt": 'Reply with valid JSON only, no explanation: {"status": "ok"}',
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 50},
    }
    r = httpx.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=120.0)
    assert r.status_code == 200, f"Ollama returned {r.status_code}: {r.text[:200]}"

    raw = r.json().get("response", "").strip()
    assert raw, "Empty response from model — inference may be broken"

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    parsed = json.loads(raw)
    assert isinstance(parsed, dict), f"Expected JSON object, got: {type(parsed)}"
