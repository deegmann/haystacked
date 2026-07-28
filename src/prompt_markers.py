"""Shared, field-agnostic helpers for locating the "NULL RULE" marker in AP0 LLM
Hint text.

Pass 4b's prompt needs the full hint, null-bias prose included. Pass 4c's prompt
must NOT include the null-bias prose (it would triple the null-bias already present
in the system prompt) — only the semantic field definition that precedes the marker.

`generate_all.py`'s emit_fields_json() imports the same compiled pattern to assert
at generation time that every "NULL RULE" occurrence in AP0 uses one of the two
recognised marker spellings ("NULL RULE:" or "NULL RULE — READ FIRST:") — never a
third, unrecognised variant that this module's split would silently fail to catch.
"""
from __future__ import annotations

import re

NULL_RULE_PATTERN = re.compile(r"NULL RULE\b[^:\n]{0,40}:")


def strip_null_rule(hint: str) -> str:
    """Return everything in `hint` before the first NULL_RULE_PATTERN match, stripped
    of trailing whitespace. If no match, returns `hint` stripped unchanged."""
    match = NULL_RULE_PATTERN.search(hint)
    if match is None:
        return hint.strip()
    return hint[:match.start()].rstrip()
