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


# Empirically safe band is [15, 90] chars across the full tender corpus (Nordlicht,
# CompanyX, Dragonfly, Mama): the thinnest genuine field needs >=15, the one known
# coincidental-collision leak (a fabricated small integer near unrelated boilerplate)
# first appears at >=95. 80 sits with margin on both sides. This is a generic
# text-layout property (how far a number sits from its describing words), not a
# fitted cutoff — there is no fraction here to retune when a new document shows up.
_GROUNDING_WINDOW_CHARS = 80

# Deliberately SHORT — function words only (DE+EN articles/prepositions/auxiliaries).
# Domain words like "maximum"/"minimum"/"weight" must survive this filter: genuine
# quotes sometimes share only boilerplate vocabulary with the source document.
_FUNCTION_WORDS = frozenset({
    "the", "a", "an", "is", "of", "to", "for", "and", "or", "in", "on", "at",
    "must", "up", "from", "are", "be", "that", "this", "with", "as", "it",
    "its", "have", "has", "will", "shall", "not", "than", "into", "per",
    "der", "die", "das", "und", "oder", "ist", "sind", "für", "von", "bis",
    "auf", "mit", "bei", "ein", "eine", "einer", "im", "am", "zu", "zur",
    "zum", "muss", "müssen", "nicht", "als", "wird", "werden",
})


def _content_words(text: str) -> set:
    """Distinctive words from a quote: length > 3, function words dropped."""
    return {
        w.lower()
        for w in re.findall(r"[A-Za-zÄÖÜäöüß]+", text)
        if len(w) > 3 and w.lower() not in _FUNCTION_WORDS
    }


def source_is_grounded(value, source: str, document: str, window: int = _GROUNDING_WINDOW_CHARS) -> bool:
    """Return True if `source` (the LLM's self-reported quote) is actually grounded in
    `document` (the real extracted PDF text) — not just numerically self-consistent
    with `value`, which is all `source_confirms_value()` checks.

    Two necessary, binary conditions (no fraction, no calibrated cutoff):
      1. Anchor: value's digit-string (locale + x1000/x0.001 unit-scale tolerance,
         via the same `_interpret_number_token` used elsewhere in this module) must
         occur somewhere in the real document — not just in the LLM's own quote.
      2. Co-location: at least one distinctive word from `source` must appear within
         `window` chars of at least one anchor occurrence in the document.

    Zero values always pass (LL-06: a deliberate zero is not an inference hallucination).
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return True
    if v == 0:
        return True
    if not source or not str(source).strip():
        return False

    av = abs(v)
    targets = {av, av * 1000, round(av / 1000, 6)}

    positions = []
    for m in re.finditer(r"\d[\d,\.]*", document):
        if _interpret_number_token(m.group()) & targets:
            positions.append(m.start())
    if not positions:
        return False

    quote_words = _content_words(str(source))
    if not quote_words:
        return False

    for pos in positions:
        window_text = document[max(0, pos - window): pos + window].lower()
        if any(w in window_text for w in quote_words):
            return True
    return False


def enforce_source_spans(
    agv_criteria: dict,
    document_text: str,
    numeric_ko_keys,
    four_c_abstained: set,
) -> tuple:
    """Null out numeric KO fields whose `<field>_source` fails the source-span guard.

    Runs three layers per field, in order (first match nulls the value and stops):
      Layer 1: source absent/empty -> null (no citation = inference).
      Layer 0: source present but not grounded in the real document -> null
               (catches a fabricated value with a fabricated-but-self-consistent
               quote; runs unconditionally, not scoped to 4c abstention).
      Layer 2 (4c-abstention only): source numerically inconsistent with its own
               claimed value -> null.

    Pure function — no async, no I/O — so tests can import and call it directly
    instead of replicating this logic inline.

    Returns (agv_criteria, messages) where messages is a list of human-readable
    log lines for each field nulled, for the caller to surface (e.g. via SSE).
    """
    messages = []
    for key in numeric_ko_keys:
        if agv_criteria.get(key) is None:
            continue
        value = agv_criteria[key]
        src_val = agv_criteria.get(f"{key}_source")
        if not src_val:
            log.warning("Source-span L1: %s=%s -> null (kein Quellenbeleg)", key, value)
            messages.append(f"⚠ Kein Quellenbeleg: {key}={value} → null")
            agv_criteria[key] = None
        elif not source_is_grounded(value, str(src_val), document_text):
            log.warning("Source-span L0: %s=%s -> null (Zitat nicht im Dokument verankert)", key, value)
            messages.append(f"⚠ Quelle nicht im Dokument verankert: {key}={value} → null")
            agv_criteria[key] = None
        elif key in four_c_abstained and not source_confirms_value(value, str(src_val)):
            log.warning("Source-span L2: %s=%s — 4c abstained, Quelle bestätigt Wert nicht -> null", key, value)
            messages.append(f"⚠ 4c Abstention: {key}={value} → null")
            agv_criteria[key] = None
    return agv_criteria, messages
