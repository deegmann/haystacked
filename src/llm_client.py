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
    timeout: float = 600.0,
) -> Optional[str]:
    payload = {
        "model":  model,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_ctx":     32768,
            "temperature": 0.0,
            "num_predict": 4096,
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


from src.json_repair import repair_and_parse
