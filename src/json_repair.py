"""
Standalone JSON repair/parse utility for LLM responses (LL-03).

No domain knowledge — no field names, no AP0 allowed-values, no AGV logic.
All stages are field-name-agnostic. Do not add field-specific logic here.
"""
import json
import re
import logging
from collections import namedtuple

log = logging.getLogger("haystacked.json_repair")

# Internal to enforce_source_spans()'s contract only — not a shared cross-module
# class. One event per field actually nulled by the guard.
SpanEvent = namedtuple("SpanEvent", ["field", "layer", "value", "source"])


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

# Empirically validated by senior-architect (2026-07-28) via window sweep 10-90 chars
# against real pdfplumber-extracted CompanyX + Dragonfly document text: a bidirectional
# 20-90 char band cleanly separates correct value+unit pairs from fabricated anchor
# collisions. 80 chosen to match the proven band; independent from _GROUNDING_WINDOW_CHARS
# (different question: tight unit-token adjacency vs. fuzzy word co-location) — do not
# merge these constants even though they currently share a numeric value.
_UNIT_GROUNDING_WINDOW_CHARS = 80

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


def _phrase_words_around_value(source: str, targets: set, word_radius: int = 3) -> set:
    """Content words within `word_radius` words of the value's number in source.

    Narrows the co-location check to the specific phrase around the number
    (e.g. 'height of 3 meters') rather than the whole sentence (which can
    contain domain-plausible words like 'pallets' that coincidentally appear
    near any number in a pallet-AGV tender document).

    Uses word-based radius (not character-based) to avoid splitting words at
    phrase boundaries.  Returns an empty set when the value's number is not
    found in source or the phrase yields no content words; callers fall back
    to the full-source content words in that case.
    """
    src = str(source)
    word_spans = list(re.finditer(r"\S+", src))
    for num_m in re.finditer(r"\d[\d,\.]*", src):
        if not (_interpret_number_token(num_m.group()) & targets):
            continue
        # Identify which word-token contains this numeric match
        val_word_idx = next(
            (i for i, ws in enumerate(word_spans) if ws.start() <= num_m.start() < ws.end()),
            None,
        )
        if val_word_idx is None:
            continue
        start_i = max(0, val_word_idx - word_radius)
        end_i = min(len(word_spans), val_word_idx + word_radius + 1)
        phrase = " ".join(ws.group() for ws in word_spans[start_i:end_i])
        return _content_words(phrase)
    return set()


def source_is_grounded(value, source: str, document: str, window: int = _GROUNDING_WINDOW_CHARS) -> bool:
    """Return True if `source` (the LLM's self-reported quote) is actually grounded in
    `document` (the real extracted PDF text) — not just numerically self-consistent
    with `value`, which is all `source_confirms_value()` checks.

    Two necessary, binary conditions (no fraction, no calibrated cutoff):
      1. Anchor: value's digit-string (locale + x1000/x0.001 unit-scale tolerance,
         via the same `_interpret_number_token` used elsewhere in this module) must
         occur somewhere in the real document — not just in the LLM's own quote.
      2. Co-location: at least one distinctive word from the ±25-char phrase around
         the value's number in `source` must appear (word-boundary match) within
         `window` chars of at least one anchor occurrence in the document.
         Falls back to full-source content words when no qualifying phrase words exist
         (e.g. value surrounded only by units and prepositions in the quote).

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

    # Narrow co-location check to words adjacent to the value in the source,
    # falling back to full source when the local phrase yields no content words.
    phrase_words = _phrase_words_around_value(str(source), targets)
    quote_words = phrase_words if phrase_words else _content_words(str(source))
    if not quote_words:
        return False

    for pos in positions:
        window_text = document[max(0, pos - window): pos + window].lower()
        # Word-boundary match: prevents "lift" in source matching "forklift" in document
        if any(re.search(r'\b' + re.escape(w) + r'\b', window_text) for w in quote_words):
            return True
    return False


def document_supports_value_with_unit(value, unit: str, document: str, window: int = _UNIT_GROUNDING_WINDOW_CHARS) -> bool:
    """Return True if value's digit-string occurs in `document` with `unit` token
    within `window` chars (bidirectional adjacency check).

    Used as a rescue check before Layer 2 nulls a value whose source failed
    source_confirms_value(): a value+unit pair appearing together in the real
    document is stronger evidence of correctness than the source-span guard's
    citation-quality checks, which cannot distinguish a correct value with a
    broken citation (e.g. Pass 4b echoing the AP0 hint text as `_source`) from
    a fabricated one — both populations have equally uninformative sources when
    the citation channel itself is broken, not when the value itself is wrong.

    Deliberately does NOT apply the ×1000/÷1000 unit-scale tolerance that
    source_confirms_value()/source_is_grounded() use elsewhere in this module —
    this function requires an EXACT digit-string match (locale-normalized via
    _interpret_number_token only). Scale tolerance here would rescue a fabricated
    value that happens to be a ×1000 mismatch of a real number-with-unit elsewhere
    in the document (e.g. a fabricated 4.8 next to a genuine "4800 kg" occurrence) —
    this is exactly the regression test_T_TR_06_d1_l2_hint_echo_provenance_persists
    (tests/unit/test_tender_store.py) is designed to catch, and this function must
    keep failing it (i.e. must NOT rescue that fixture's fabricated value).

    Single-character alphabetic units (e.g. "m", "K", "h") always return False —
    they collide with unrelated document text too often (e.g. unit "m" matching
    "58,000 m²") to be a reliable signal. This is a generic length-based rule,
    not a per-field exception list — do not special-case specific field names or
    unit strings beyond this general check.

    Pure function — no field names, no AP0 value lists, no domain knowledge.
    Never add field-specific logic here, matching the same invariant already
    documented on source_confirms_value()/source_is_grounded() in this module.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    if v == 0:
        return True
    if not unit or (len(unit) == 1 and unit.isalpha()):
        return False

    av = abs(v)
    target = {av}

    positions = []
    for m in re.finditer(r"\d[\d,\.]*", document):
        if _interpret_number_token(m.group()) & target:
            positions.append(m.start())
    if not positions:
        return False

    unit_pattern = re.escape(unit)
    for pos in positions:
        window_text = document[max(0, pos - window): pos + window]
        if re.search(unit_pattern, window_text):
            return True
    return False


def _messages_from_events(events: list) -> list:
    """Derive human-readable log lines purely from SpanEvent fields — no field-name
    branches, no domain vocabulary. Single source of truth for "event -> text" so
    the log.warning() calls and the returned `messages` list can't drift apart.
    """
    messages = []
    for ev in events:
        snippet = str(ev.source or "")[:60]
        if ev.layer == "L2_RESCUED":
            messages.append(
                f"✓ Source-span L2_RESCUED: {ev.field}={ev.value} kept "
                f"(citation unconfirmed but value+unit found in document; rejected source: \"{snippet}\")"
            )
        else:
            messages.append(
                f"⚠ Source-span {ev.layer}: {ev.field}={ev.value} → null "
                f"(rejected source: \"{snippet}\")"
            )
    return messages


def enforce_source_spans(
    agv_criteria: dict,
    document_text: str,
    numeric_ko_keys,
    four_c_abstained: set,
    units: dict = None,
) -> tuple:
    """Null out numeric KO fields whose `<field>_source` fails the source-span guard.

    Runs three layers per field, in order (first match nulls the value and stops):
      Layer 1: source absent/empty -> null (no citation = inference).
      Layer 0: source present but not grounded in the real document -> null
               (catches a fabricated value with a fabricated-but-self-consistent
               quote; runs unconditionally, not scoped to 4c abstention).
      Layer 2 (4c-abstention only): source numerically inconsistent with its own
               claimed value -> null, UNLESS a rescue fires first: if the value's
               digit-string occurs in the real document with its unit token
               adjacent (bidirectional window, via document_supports_value_with_unit()),
               the value is kept instead of nulled. This handles the case where the
               citation channel itself is broken (e.g. Pass 4b echoing the AP0 field
               hint text as `_source` instead of a real document quote) for a value
               that is otherwise genuinely present in the document — a broken citation
               is not proof the value is wrong. The rescue is monotone: it can only
               convert a would-be-null into a kept value, never the reverse, so it
               cannot regress precision relative to not having the rescue at all.
               A rescue is recorded as a SpanEvent(layer="L2_RESCUED", ...) — this is
               NOT a null and callers must not treat it as one.

    `units`: optional dict of tender_key -> unit string, used only by the Layer 2
    rescue check above. Defaults to None (treated as {}), so existing callers that
    don't pass it get no rescues (behaviourally identical to before this parameter
    was added).

    Pure function — no async, no I/O — so tests can import and call it directly
    instead of replicating this logic inline.

    Returns (agv_criteria, messages, events):
      - messages: human-readable log lines for each field nulled or rescued, for
        the caller to surface (e.g. via SSE). Derived generically from `events`.
      - events: list of SpanEvent(field, layer, value, source) — one per field
        actually nulled OR rescued by this call, for callers that need structured
        data (e.g. D1 provenance attribution) rather than the display strings.
    """
    units = units or {}
    events: list = []
    for key in numeric_ko_keys:
        if agv_criteria.get(key) is None:
            continue
        value = agv_criteria[key]
        src_val = agv_criteria.get(f"{key}_source")
        if not src_val:
            log.warning("Source-span L1: %s=%s -> null (kein Quellenbeleg)", key, value)
            events.append(SpanEvent(field=key, layer="L1", value=value, source=src_val))
            agv_criteria[key] = None
        elif not source_is_grounded(value, str(src_val), document_text):
            log.warning("Source-span L0: %s=%s -> null (Zitat nicht im Dokument verankert)", key, value)
            events.append(SpanEvent(field=key, layer="L0", value=value, source=src_val))
            agv_criteria[key] = None
        elif key in four_c_abstained and not source_confirms_value(value, str(src_val)):
            unit = units.get(key, "")
            if document_supports_value_with_unit(value, unit, document_text):
                log.info("Source-span L2_RESCUED: %s=%s — citation unconfirmed but value+unit found in document, kept", key, value)
                events.append(SpanEvent(field=key, layer="L2_RESCUED", value=value, source=src_val))
            else:
                log.warning("Source-span L2: %s=%s — 4c abstained, Quelle bestätigt Wert nicht -> null", key, value)
                events.append(SpanEvent(field=key, layer="L2", value=value, source=src_val))
                agv_criteria[key] = None
    messages = _messages_from_events(events)
    return agv_criteria, messages, events
