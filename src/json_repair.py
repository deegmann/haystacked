"""
Standalone JSON repair/parse utility for LLM responses (LL-03).

No domain knowledge — no field names, no AP0 allowed-values, no AGV logic.
All stages are field-name-agnostic. Do not add field-specific logic here.
"""
import json
import re
import logging

log = logging.getLogger("haystacked.json_repair")


def repair_and_parse(raw: str) -> dict:
    """Multi-stage LLM JSON repair parser. Never call json.loads() directly on LLM output.

    Stage 0: brace-balanced extraction (prevents trailing prose from grabbing wrong '}').
    Stage 1: direct parse.
    Stage 2: remove JS-style comments.
    Stage 3: fix unescaped newlines inside strings.
    Stage 4: truncation fix (append closing suffix candidates).
    Stage 5: generic regex fallback — field-name-agnostic, no domain knowledge.

    Raises ValueError if no JSON-like structure can be extracted at all.
    """
    if not raw:
        return {}

    log.debug("RAW LLM (%d chars): %s", len(raw), raw[:1000])

    cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()

    start = cleaned.find("{")
    if start == -1:
        raise ValueError("Kein JSON-Objekt in der Antwort")

    # Stage 0: brace-balanced match — find the shortest complete JSON object from `start`,
    # avoiding rfind("}") grabbing stray braces in trailing explanation prose.
    _depth, _in_str, _esc, _bal_end = 0, False, False, -1
    for _i, _ch in enumerate(cleaned[start:], start):
        if _esc:
            _esc = False
        elif _ch == "\\" and _in_str:
            _esc = True
        elif _ch == '"':
            _in_str = not _in_str
        elif not _in_str:
            if _ch == "{":
                _depth += 1
            elif _ch == "}":
                _depth -= 1
                if _depth == 0:
                    _bal_end = _i + 1
                    break
    if _bal_end != -1:
        candidate = cleaned[start:_bal_end]
    else:
        last_brace = cleaned.rfind("}")
        candidate = cleaned[start:last_brace + 1] if last_brace != -1 else cleaned[start:]
    if not candidate:
        raise ValueError("Kein JSON-Objekt in der Antwort")

    # Stage 1: direct parse
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Stage 2: remove JS-style comments
    no_comments = re.sub(r"//[^\n]*", "", candidate)
    try:
        return json.loads(no_comments)
    except json.JSONDecodeError:
        pass

    # Stage 3: fix unescaped newlines inside strings
    def fix_nl(s):
        out, in_str, i = [], False, 0
        while i < len(s):
            ch = s[i]
            if ch == '"' and (i == 0 or s[i-1] != "\\"):
                in_str = not in_str
            if in_str and ch == "\n":
                out.append("\\n")
            elif in_str and ch == "\r":
                pass
            else:
                out.append(ch)
            i += 1
        return "".join(out)

    fixed = fix_nl(no_comments)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Stage 4: truncation fix
    for suffix in ['"}', '"]}', ']}', '}']:
        try:
            return json.loads(fixed + suffix)
        except json.JSONDecodeError:
            pass

    # Stage 5: generic regex field extraction — no field names, no domain knowledge
    log.warning("All parse attempts failed — using regex fallback")
    fields = {}
    for key, val in re.findall(r'"(\w+)"\s*:\s*"([^"]*)"', candidate):
        fields[key] = val
    for key, val in re.findall(r'"(\w+)"\s*:\s*(true|false)', candidate):
        fields[key] = val == "true"
    if fields:
        fields["_parse_method"] = "regex_fallback"
        return fields

    raise ValueError(f"JSON-Parsing fehlgeschlagen. Roh-Antwort (erste 300 Z.): {raw[:300]}")


def _interpret_number_token(raw: str) -> set:
    """Return all plausible float interpretations of a raw number string.

    Handles both locale conventions without choosing one:
    - Mixed separators ("1.000,00" / "1,000.00"): last separator is decimal.
    - Single separator ("3,4" / "1.000"): both interpretations are returned.
    """
    has_dot = "." in raw
    has_comma = "," in raw
    results = set()

    if has_dot and has_comma:
        last_dot = raw.rfind(".")
        last_comma = raw.rfind(",")
        if last_comma > last_dot:
            normalized = raw.replace(".", "").replace(",", ".")
        else:
            normalized = raw.replace(",", "")
        try:
            results.add(float(normalized))
        except ValueError:
            pass
    elif has_comma:
        try:
            results.add(float(raw.replace(",", ".")))  # comma as decimal (DE)
        except ValueError:
            pass
        try:
            results.add(float(raw.replace(",", "")))   # comma as thousands (EN)
        except ValueError:
            pass
    elif has_dot:
        try:
            results.add(float(raw))                    # period as decimal
        except ValueError:
            pass
        try:
            results.add(float(raw.replace(".", "")))   # period as thousands (DE)
        except ValueError:
            pass
    else:
        try:
            results.add(float(raw))
        except ValueError:
            pass

    return results


def source_confirms_value(value, source_text: str) -> bool:
    """Return True if source_text contains a number matching value within unit-scale tolerance.

    Handles both locale conventions (DE: "3,4" / EN: "3.4") without assuming one.
    Zero values always pass (deliberate zero, not an inference hallucination).
    Unit-scale tolerance: value 2.0 matches 2000 in source (and vice versa).
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return bool(source_text.strip())
    if v == 0:
        return True
    av = abs(v)
    nums: set = set()
    for raw in re.findall(r"\d[\d,\.]*", source_text):
        nums.update(_interpret_number_token(raw))
    return av in nums or (av * 1000) in nums or round(av / 1000, 6) in nums
