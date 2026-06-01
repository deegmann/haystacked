"""
AP-I2 — Ollama LLM Client
Always sets num_ctx=32768. Never calls json.loads directly — uses repair_and_parse.
Retry logic with 2s pause per LL-01, LL-02, LL-03.
"""
from __future__ import annotations
import json
import re
import time
import logging
from typing import Optional

import requests

log = logging.getLogger("haystacked.llm")

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b"


def call_llm(
    system: str,
    prompt: str,
    label: str = "llm",
    model: str = OLLAMA_MODEL,
    retries: int = 3,
    timeout: float = 180.0,
) -> Optional[str]:
    payload = {
        "model":  model,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_ctx":     32768,
            "temperature": 0.1,
            "num_predict": 2048,
        },
    }
    log.info("LLM [%s] system=%d prompt=%d chars", label, len(system), len(prompt))
    for attempt in range(retries):
        try:
            r = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
            r.raise_for_status()
            raw = r.json().get("response", "")
            log.info("LLM [%s] response=%d chars", label, len(raw))
            return raw
        except requests.exceptions.ConnectionError:
            if attempt == retries - 1:
                raise
            log.warning("LLM [%s] connection error, retry %d/%d", label, attempt+1, retries)
            time.sleep(2)
        except Exception as e:
            if attempt == retries - 1:
                raise
            log.warning("LLM [%s] error: %s, retry %d/%d", label, e, attempt+1, retries)
            time.sleep(2)
    return None


def repair_and_parse(raw: str) -> dict:
    """Mehrstufiger LLM-JSON-Reparatur-Parser per LL-03. Nie direkt json.loads() verwenden."""
    if not raw:
        return {}

    # Stage 1: direct
    try:
        return json.loads(raw)
    except Exception:
        pass

    # Stage 2: remove markdown fences
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # Stage 3: extract first { ... }
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass

    # Stage 4: normalize string "null" / "true" / "false"
    normalized = re.sub(r':\s*"null"', ": null", cleaned)
    normalized = re.sub(r':\s*"true"', ": true", normalized)
    normalized = re.sub(r':\s*"false"', ": false", normalized)
    try:
        return json.loads(normalized)
    except Exception:
        pass

    # Stage 5: fix unescaped newlines inside strings
    fixed = re.sub(r'(?<!\\)\n(?=[^"]*")', "\\n", normalized)
    try:
        return json.loads(fixed)
    except Exception:
        pass

    # Stage 6: truncated JSON — drop last incomplete field
    partial = re.sub(r',\s*"[^"]*"\s*:\s*[^,}\]]*$', "", fixed)
    if not partial.endswith("}"):
        partial += "}"
    try:
        return json.loads(partial)
    except Exception:
        pass

    # Stage 7: regex field extraction
    result: dict = {}
    for key, val in re.findall(r'"(\w+)"\s*:\s*"([^"]*)"', raw):
        result[key] = val
    return result
