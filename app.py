import json
import re
import httpx
import pdfplumber
import logging
import asyncio
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import io
import supplier_db
from src.json_repair import repair_and_parse, enforce_source_spans

# ── New structured matching engine (AP-I1) ────────────────────────────────────
try:
    from src.data_loader import load_suppliers
    from src.matching import match_suppliers_new, TenderRequirements, Matcher
    from src.context_builder import agv_type_keyword_fallback, build_system_context, AGV_KEYWORDS
    _DB_AVAILABLE = True
    _SUPPLIERS = load_suppliers()
    log_setup = logging.getLogger("haystacked")
    log_setup.info("SQLite DB loaded: %d active supplier records", len(_SUPPLIERS))
except FileNotFoundError:
    _DB_AVAILABLE = False
    _SUPPLIERS = []
    log_setup = logging.getLogger("haystacked")
    log_setup.warning("SQLite DB not found — run sync_airtable.py. Falling back to CSV matching.")

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("haystacked.log", encoding="utf-8"),
    ],
)
logging.getLogger("multipart").setLevel(logging.WARNING)
logging.getLogger("pdfminer").setLevel(logging.WARNING)
log = logging.getLogger("haystacked")
log.setLevel(logging.DEBUG)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="haystacked – Ausschreibungsanalyse")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

OLLAMA_URL      = "http://localhost:11434/api/generate"
OLLAMA_MODEL    = "qwen2.5:7b"
_OLLAMA_NUM_CTX = 32_768  # must match num_ctx in call_ollama() options
# ── Config loading — startup checksum auto-regenerates if AP0 xlsx changed ────
_CONFIG_DIR = Path(__file__).parent / "config"
_AP0_PATH   = Path(__file__).parent / "Spec" / "haystacked_AP0_field_spec_v0_10.xlsx"

def _check_and_regen():
    """Auto-regenerate all config files if AP0 xlsx has changed (checksum mismatch)."""
    import hashlib, importlib.util
    checksum_file = _CONFIG_DIR / "ap0_checksum.txt"
    if not _AP0_PATH.exists():
        return
    current = hashlib.md5(_AP0_PATH.read_bytes()).hexdigest()
    stored  = checksum_file.read_text().strip() if checksum_file.exists() else ""
    if current == stored:
        return
    log.info("AP0 xlsx changed (checksum mismatch) — regenerating config files…")
    spec = importlib.util.spec_from_file_location(
        "generate_all", Path(__file__).parent / "scripts" / "generate_all.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    exit_code = mod.generate(_AP0_PATH, _CONFIG_DIR.parent / "data" / "haystacked.db")
    if exit_code == 0:
        log.info("Config regenerated from AP0 v0.10")
    else:
        log.warning("Config regenerated with warnings — check consistency")

_check_and_regen()

# ── Vehicle types — loaded from generated config (no hardcoding) ──────────────
_vehicle_cfg    = json.loads((_CONFIG_DIR / "vehicle_types.json").read_text())
_field_levels   = json.loads((_CONFIG_DIR / "field_levels.json").read_text())
# _VALID_VEHICLE_TYPES kept for backward-compat (still used in VNA normalisation downstream)
_VALID_VEHICLE_TYPES = set(_field_levels.get("agv_type", {}).get("allowed_values", []))

# ── AP0 allowed-values index — built once at startup from field_levels.json ───
# Maps tender_key → (allowed_values_set, field_label) for every Dropdown/Multi-Select
# field that has an allowed_values list.  Used by the generalised LLM retry loop.
# Fields in _AP0_SKIP_VALIDATION are handled by downstream normalisation in app.py
# and must not be double-checked here.
_AP0_SKIP_VALIDATION: frozenset = frozenset({
    "required_vna",            # derived from vehicle_type / text_overrides
    "required_outdoor",        # boolean coerced separately
})
_AP0_CONSTRAINED_FIELDS: dict = {}   # tender_key → {"allowed": set, "allowed_list": list}
for _fl_key, _fl_meta in _field_levels.items():
    _av = _fl_meta.get("allowed_values")
    _tk = _fl_meta.get("tender_key", _fl_key)
    if _av and _tk not in _AP0_SKIP_VALIDATION:
        _AP0_CONSTRAINED_FIELDS[_tk] = {
            "allowed":      {v.lower() for v in _av},
            "allowed_list": _av,
        }
# Guard: if AP0 ever adds allowed_values to a skip-listed field, downstream coercion
# logic must be updated before removing it from _AP0_SKIP_VALIDATION.
for _sk in _AP0_SKIP_VALIDATION:
    assert _sk not in _AP0_CONSTRAINED_FIELDS, (
        f"{_sk} is in _AP0_SKIP_VALIDATION but AP0 now defines allowed_values for it — "
        f"review the downstream coercion logic and remove from skip list."
    )

# ── Numeric KO fields requiring source-span citation ─────────────────────────
# Built from field_levels.json — any Float/Integer field with KO_IF_LT or KO_IF_GT.
# The extraction template emits a companion <key>_source for each of these.
# If the companion is absent or null, the value is nulled (inference hallucination guard).
_NUMERIC_KO_TENDER_KEYS: frozenset = frozenset(
    _fl_meta.get("tender_key", _fl_key)
    for _fl_key, _fl_meta in _field_levels.items()
    if _fl_meta.get("operator") in ("KO_IF_LT", "KO_IF_GT")
    and _fl_meta.get("data_type") in ("Float", "Integer")
)

# ── Pass 4c: per-field extraction hints ──────────────────────────────────────
# Maps tender_key → {hint, sheet} for numeric KO fields — used in Pass 4c to
# build one focused LLM prompt per field instead of a single 40-field batch.
_hints_path = _CONFIG_DIR / "extraction_hints.json"
_extraction_hints: dict = json.loads(_hints_path.read_text()) if _hints_path.exists() else {}
# Only the numeric KO fields that have a hint and belong to a specific sheet.
# Sheet mapping determines which fields are relevant per vehicle type at runtime.
_NUMERIC_KO_FIELD_HINTS: dict = {
    k: v for k, v in _extraction_hints.items()
    if k in _NUMERIC_KO_TENDER_KEYS and v.get("hint") and v.get("sheet")
}

# Operator-driven extraction direction for Pass 4c prompts — derived from field_levels.json.
# KO_IF_LT means the supplier must meet or exceed the tender's threshold → extract MAXIMUM.
# KO_IF_GT means the supplier must not exceed the tender's limit → extract MINIMUM.
_4C_EXTRACTION_DIRECTION: dict = {}
for _fl_key, _fl_meta in _field_levels.items():
    _tk = _fl_meta.get("tender_key", _fl_key)
    _op = _fl_meta.get("operator")
    if _op == "KO_IF_LT":
        _4C_EXTRACTION_DIRECTION[_tk] = (
            "If multiple values are present, extract the MAXIMUM — "
            "the supplier must meet or exceed this threshold."
        )
    elif _op == "KO_IF_GT":
        _4C_EXTRACTION_DIRECTION[_tk] = (
            "If multiple values are present, extract the MINIMUM — "
            "the supplier must not exceed this constraint."
        )

assert _NUMERIC_KO_TENDER_KEYS, (
    "field_levels.json has no KO_IF_LT/KO_IF_GT Float/Integer fields — "
    "source-span enforcement is inactive. Run generate_all.py."
)
assert _4C_EXTRACTION_DIRECTION, (
    "field_levels.json has no KO_IF_LT/KO_IF_GT fields — "
    "Pass 4c has no extraction direction. Run generate_all.py."
)


def _find_invalid_ap0_fields(criteria: dict, skip: frozenset = frozenset()) -> dict:
    """Return {tender_key: (raw_value, allowed_list)} for every non-null field whose
    value is not found in the AP0 allowed_values list.  Case-insensitive substring
    match mirrors the logic in validate_tender_values().  Multi-value fields (pipe or
    comma separated) are checked element-by-element; only invalid elements are reported.
    Fields in `skip` are excluded (used in Pass 4b to skip fields already validated in 4a)."""
    violations: dict = {}
    for tk, meta in _AP0_CONSTRAINED_FIELDS.items():
        if tk in skip:
            continue
        val = criteria.get(tk)
        if val is None:
            continue
        parts = [p.strip() for p in str(val).replace("|", ",").split(",") if p.strip()]
        allowed_lower = meta["allowed"]
        invalid_parts = [
            p for p in parts
            if not any(p.lower() in al or al in p.lower() for al in allowed_lower)
        ]
        if invalid_parts:
            violations[tk] = (", ".join(invalid_parts), meta["allowed_list"])
    return violations


def _build_correction_prompt(violations: dict, original_text: str) -> str:
    """Build a targeted correction user-prompt from AP0 violation data.
    No field names or allowed values are hardcoded — everything comes from
    the violations dict which is derived from _field_levels (AP0 SSoT)."""
    lines = [
        "The previous extraction returned invalid values for the following fields.",
        "For each field, the invalid value and the complete list of allowed AP0 values are shown.",
        "Re-extract ONLY these fields from the document and return a JSON object containing",
        "only the corrected keys.  Use null if the document does not specify the field.",
        "Do not return any other keys.",
        "",
    ]
    for tk, (bad_val, allowed_list) in violations.items():
        lines.append(f"Field: {tk}")
        lines.append(f"  Invalid value extracted: {bad_val!r}")
        lines.append(f"  Allowed values: {', '.join(repr(a) for a in allowed_list)}")
        lines.append("")
    lines += [
        "DOCUMENT (excerpt — first 4000 chars):",
        original_text[:4000],
    ]
    return "\n".join(lines)
_VT_MAP_CFG     = _vehicle_cfg.get("vt_map", {})             # llm_output_lower → canonical
_VNA_CFG        = set(_vehicle_cfg.get("vna_subtypes", []))   # set of vna llm outputs
_VT_OVERRIDES   = _vehicle_cfg.get("text_overrides", [])      # [{regex, canonical, vna}]
_VNA_APPLICABLE = set(_vehicle_cfg.get("vna_applicable_types", []))  # C-5: types where VNA gate applies
_AGV_DETECT_KWS = _vehicle_cfg.get("agv_detection_keywords", [])     # C-1: is_agv_amr fallback keywords

_FIELD_TEXT_FALLBACKS = _vehicle_cfg.get("field_text_fallbacks", [])  # [{tender_key, regex, value, only_if_null}]
_SHARED_SHEET         = _vehicle_cfg.get("shared_sheet_name", "")  # C-6: AP0 shared sheet name
assert _SHARED_SHEET, "vehicle_types.json missing 'shared_sheet_name' — run generate_all.py"

# ── NACE — loaded from generated config ───────────────────────────────────────
_nace_cfg     = json.loads((_CONFIG_DIR / "nace_codes.json").read_text())
CATEGORY_LIST = "\n".join(_nace_cfg.get("codes", []))
log.info("NACE codes loaded: %d Prio-1 entries", len(_nace_cfg.get("codes", [])))

# ── Prompts ───────────────────────────────────────────────────────────────────

# ── Prompt loading — all industry knowledge lives in config/prompts/, not here ──
# To adapt haystacked for a new industry: edit the .txt files, no Python needed.

def _load_prompt(filename: str) -> str:
    p = Path(__file__).parent / "config" / "prompts" / filename
    return p.read_text(encoding="utf-8").strip()


def _fill(template: str, **kwargs) -> str:
    """Replace {key} placeholders in a prompt template without touching JSON braces.
    Uses explicit named replacement so JSON like {"field":null} is preserved."""
    for key, value in kwargs.items():
        template = template.replace("{" + key + "}", str(value) if value is not None else "")
    return template

MAIN_SYSTEM          = _load_prompt("basic_system.txt")
BASIC_USER_TEMPLATE  = _load_prompt("basic_template.txt")
CONTACT_SYSTEM       = _load_prompt("contact_system.txt")
CONTACT_USER_TEMPLATE= _load_prompt("contact_template.txt")
NACE_SYSTEM          = _load_prompt("nace_system.txt")
NACE_USER_TEMPLATE   = _load_prompt("nace_template.txt")
# AGV system prompt = extraction role + full industry README (loaded via context_builder)
# This gives the LLM domain knowledge about VNA, G2P, OEM rebadging, etc.
AGV_SYSTEM              = build_system_context() if _DB_AVAILABLE else _load_prompt("extraction_system.txt")
AGV_USER_TEMPLATE       = _load_prompt("extraction_template.txt")          # full fallback template
VEHICLE_TYPE_TEMPLATE   = _load_prompt("vehicle_type_template.txt")         # Pass 4a
# Pass 4b templates — loaded from vt_prompt_map in vehicle_types.json (AP0-driven, no hardcoded type names)
_AGV_TYPE_TEMPLATES = {
    canon: _load_prompt(fname)
    for canon, fname in _vehicle_cfg.get("vt_prompt_map", {}).items()
    if (_CONFIG_DIR / "prompts" / fname).exists()
}
# Fields determined in Pass 4a — excluded from 4b AP0 validation (loaded from vehicle_types.json)
_4A_SKIP = frozenset(_vehicle_cfg.get("4a_fields", []))
AGV_RETRY_SYSTEM     = _load_prompt("extraction_retry_system.txt")
AGV_RETRY_TEMPLATE   = _load_prompt("extraction_retry_template.txt")


# ── AGV value validation ──────────────────────────────────────────────────────
# Loaded from config/plausibility.json (generated by scripts/generate_all.py from AP0 xlsx).
# Edit Plausibility Min/Max/Tender Unit columns in the AP0 xlsx — never hardcode here.
_plausibility_cfg = json.loads((_CONFIG_DIR / "plausibility.json").read_text()) \
    if (_CONFIG_DIR / "plausibility.json").exists() else {}


def validate_agv_criteria(crit: dict) -> tuple:
    """Returns (cleaned_dict, warnings_list).

    Auto-converts LLM unit errors (e.g. mm→m) using conversion rules from plausibility.json.
    Sets implausible values to None.
    """
    warnings = []
    cleaned = dict(crit)
    for field, cfg in _plausibility_cfg.items():
        val = cleaned.get(field)
        if val is None:
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue

        lo, hi, unit, label = cfg["min"], cfg["max"], cfg["unit"], cfg["label"]
        conv = cfg.get("conversion")

        # Auto-convert using unit conversion rules from AP0 Unit Conversions sheet
        if conv and v > conv["threshold"]:
            v_converted = v * conv["factor"]
            if lo <= v_converted <= hi:
                warnings.append(
                    f"{label}: {v} {conv['llm_alias']} → {v_converted:.3g} {unit} (automatisch konvertiert)"
                )
                log.info("AGV unit conversion: %s %s → %s %s", label, v, v_converted, unit)
                cleaned[field] = v_converted
                continue

        if not (lo <= v <= hi):
            warnings.append(
                f"{label}: Wert {v} {unit} außerhalb plausiblem Bereich [{lo}–{hi} {unit}] → ignoriert"
            )
            log.warning("AGV-Plausibilität: %s", warnings[-1])
            cleaned[field] = None
    return cleaned, warnings


# ── PDF extraction ────────────────────────────────────────────────────────────
def extract_text_from_pdf(pdf_bytes: bytes) -> tuple[str, int]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        num_pages = len(pdf.pages)
        pages = []
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            log.debug("Seite %d: %d Z.", i + 1, len(text) if text else 0)
            if text:
                pages.append(text)
    full_text = "\n\n".join(pages)
    log.info("PDF: %d Seiten, %d Zeichen, %d Seiten mit Text", num_pages, len(full_text), len(pages))
    return full_text, num_pages


# ── Ollama call ───────────────────────────────────────────────────────────────
async def call_ollama(system: str, user: str, label: str) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "system": system,
        "prompt": user,
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 4096, "num_ctx": _OLLAMA_NUM_CTX},
    }
    log.info("Ollama [%s]: system=%d Z., prompt=%d Z.", label, len(system), len(user))
    t0 = datetime.now()
    async with httpx.AsyncClient(timeout=3600.0) as client:
        resp = await client.post(OLLAMA_URL, json=payload)
        resp.raise_for_status()
    elapsed = (datetime.now() - t0).total_seconds()
    raw = resp.json().get("response", "")
    log.info("Ollama [%s]: %.1fs, %d Z. Antwort", label, elapsed, len(raw))
    return raw


# ── SSE helper ────────────────────────────────────────────────────────────────
def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    filename  = file.filename
    pdf_bytes = await file.read()

    async def stream():
        t0 = datetime.now()
        log.info("=== Neue Analyse: %s ===", filename)

        yield sse("step", {"id": "upload", "status": "done", "message": f"'{filename}' empfangen"})

        if not filename.lower().endswith(".pdf"):
            yield sse("error", {"message": "Nur PDF-Dateien werden unterstützt."}); return

        size_kb = len(pdf_bytes) // 1024
        log.info("PDF-Größe: %d KB", size_kb)
        yield sse("log", {"message": f"PDF-Größe: {size_kb} KB"})

        if len(pdf_bytes) > 20 * 1024 * 1024:
            yield sse("error", {"message": "PDF zu groß (max. 20 MB)."}); return

        # ── PDF extraction ────────────────────────────────────────────────────
        yield sse("step", {"id": "extract", "status": "running", "message": "Text wird extrahiert…"})
        await asyncio.sleep(0)

        try:
            text, num_pages = extract_text_from_pdf(pdf_bytes)
        except Exception as e:
            log.exception("PDF-Extraktion fehlgeschlagen")
            yield sse("error", {"message": f"PDF konnte nicht gelesen werden: {e}"}); return

        if not text.strip():
            yield sse("error", {"message": "Kein Text gefunden (gescanntes Dokument?)"}); return

        # qwen2.5:7b has 128k token context; we activate 32k via num_ctx.
        # 50k chars ≈ 14k tokens — covers virtually all tender documents in full.
        max_chars = 50_000
        truncated = len(text) > max_chars
        if truncated:
            log.info("Text gekürzt: %d → %d Z.", len(text), max_chars)
            text = text[:max_chars] + "\n\n[... Dokument gekürzt ...]"

        yield sse("step", {"id": "extract", "status": "done",
                            "message": f"{num_pages} Seiten · {len(text):,} Zeichen" + (" · gekürzt" if truncated else "")})
        yield sse("log", {"message": f"Extrahiert: {num_pages} Seiten | {len(text):,} Z. | Gekürzt: {truncated}"})

        # ── LLM Step 1: Basic extraction ──────────────────────────────────────
        yield sse("step", {"id": "llm", "status": "running",
                            "message": f"Grunddaten extrahieren ({OLLAMA_MODEL})…"})
        await asyncio.sleep(0)

        # Use full available text for basic extraction so contact info
        # and summaries from later pages are visible to the model.
        basic_user = _fill(BASIC_USER_TEMPLATE, text=text)
        try:
            raw_basic = await call_ollama(MAIN_SYSTEM, basic_user, "basic")
        except httpx.ConnectError:
            yield sse("error", {"message": "Ollama nicht erreichbar — bitte './start.sh' nutzen."}); return
        except Exception as e:
            log.exception("LLM-Fehler (basic)")
            yield sse("error", {"message": f"LLM-Fehler: {e}"}); return

        t1 = (datetime.now() - t0).total_seconds()
        yield sse("step", {"id": "llm", "status": "done", "message": f"LLM-Analyse fertig ({t1:.1f}s)"})
        yield sse("log", {"message": f"Grunddaten: {t1:.1f}s | {len(raw_basic)} Z."})

        yield sse("step", {"id": "parse", "status": "running", "message": "Antwort wird geparst…"})
        await asyncio.sleep(0)

        try:
            result = repair_and_parse(raw_basic)
        except ValueError as e:
            log.error("Parse-Fehler: %s", e)
            yield sse("step", {"id": "parse", "status": "error", "message": str(e)})
            yield sse("error", {"message": str(e), "raw_preview": raw_basic[:500]}); return

        parse_method = result.pop("_parse_method", "direct")

        # Clean up string "null" values the LLM sometimes emits instead of JSON null
        for k, v in result.items():
            if v == "null" or v == "NULL":
                result[k] = None

        # Keyword fallback: if LLM missed is_agv_amr but doc contains clear AGV terms, force true
        if not result.get("is_agv_amr"):
            text_lower = text[:5000].lower()
            if any(kw in text_lower for kw in _AGV_DETECT_KWS):
                result["is_agv_amr"] = True
                log.info("AGV-Keyword-Fallback: is_agv_amr auf True gesetzt")

        # ── Contact fallback: targeted pass on document tail ──────────────────
        # Contact info is often at the end of a document. If the main extraction
        # missed contact fields and the document has a meaningful tail, run a
        # short focused call on the last 4000 chars.
        contact_missing = not any(result.get(f) for f in ("contact_name", "contact_email", "contact_phone"))
        full_text_len = result.get("text_length", len(text))  # not set yet, use len(text)
        if contact_missing and len(text) > 6000:
            tail = text[-4000:]
            try:
                raw_contact = await call_ollama(CONTACT_SYSTEM, _fill(CONTACT_USER_TEMPLATE, text=tail), "contact")
                contact_data = repair_and_parse(raw_contact)
                contact_data.pop("_parse_method", None)
                for field in ("contact_name", "contact_email", "contact_phone", "deadline", "tender_date"):
                    if contact_data.get(field) and not result.get(field):
                        result[field] = contact_data[field]
                        log.info("Kontakt-Fallback: %s = %s", field, contact_data[field])
            except Exception as e:
                log.warning("Kontakt-Fallback fehlgeschlagen: %s", e)

        # ── LLM Step 2: NACE classification (short, targeted) ────────────────
        yield sse("step", {"id": "parse", "status": "running", "message": "NACE klassifizieren…"})
        # Fallback chain: tender_category → project_name → generic
        tender_cat = (result.get("tender_category")
                      or result.get("project_name")
                      or "unknown service")
        # Fallback chain: buyer_industry → buyer name → generic
        buyer_ind  = (result.get("buyer_industry")
                      or result.get("buyer")
                      or "unknown industry")
        nace_user  = _fill(NACE_USER_TEMPLATE,
            tender_category=tender_cat, buyer_industry=buyer_ind,
            category_list=CATEGORY_LIST
        )
        try:
            raw_nace = await call_ollama(NACE_SYSTEM, nace_user, "nace")
            nace_data = repair_and_parse(raw_nace)
            nace_data.pop("_parse_method", None)
            in_scope = nace_data.pop("in_scope", True)
            result.update(nace_data)
            result["in_scope"] = bool(in_scope)
            log.info("NACE: tender=%s in_scope=%s", result.get("nace_tender"), result["in_scope"])
        except Exception as e:
            log.warning("NACE-Klassifizierung fehlgeschlagen: %s", e)
            result["in_scope"] = True  # don't hide result on classification error

        t2 = (datetime.now() - t0).total_seconds()
        scope_label = "" if result.get("in_scope", True) else " · außerhalb Scope"
        yield sse("step", {"id": "parse", "status": "done",
                            "message": f"Parsing OK ({parse_method}) | NACE: {result.get('nace_tender','–')}{scope_label}"})
        yield sse("log", {"message": f"Parse+NACE: {t2:.1f}s gesamt"})

        is_agv = bool(result.get("is_agv_amr", False))
        log.info("AGV/AMR-Tender erkannt: %s", is_agv)

        # ── LLM: AGV criteria extraction (if applicable) ──────────────────────
        agv_criteria = None
        matches = []
        matches_all = []

        if is_agv:
            yield sse("step", {"id": "agv", "status": "running",
                                "message": "Fahrzeugtyp wird klassifiziert…"})
            await asyncio.sleep(0)

            # ── Pass 4a: classify vehicle type only ───────────────────────────
            vt_user = _fill(VEHICLE_TYPE_TEMPLATE, text=text)
            vt_criteria: dict = {}
            _ap0_violations_4a: dict = {}
            try:
                for _attempt in range(3):
                    if _attempt == 0:
                        raw_vt = await call_ollama(AGV_SYSTEM, vt_user, "agv_4a")
                        try:
                            vt_criteria = repair_and_parse(raw_vt)
                        except ValueError:
                            log.warning("4a-Antwort kein JSON — Retry")
                            yield sse("log", {"message": "4a: Kein JSON → Retry…"})
                            raw_vt2 = await call_ollama(AGV_RETRY_SYSTEM,
                                                        _fill(AGV_RETRY_TEMPLATE, text=text), "agv_4a_retry")
                            vt_criteria = repair_and_parse(raw_vt2)
                    else:
                        correction_user = _build_correction_prompt(_ap0_violations_4a, text)
                        raw_vt = await call_ollama(AGV_RETRY_SYSTEM, correction_user,
                                                   f"agv_4a_correction{_attempt}")
                        try:
                            correction = repair_and_parse(raw_vt)
                        except ValueError:
                            correction = {}
                        for _tk in _ap0_violations_4a:
                            if _tk in correction:
                                vt_criteria[_tk] = correction[_tk]

                    vt_criteria.pop("_parse_method", None)
                    for k, v in list(vt_criteria.items()):
                        if v in ("null", "NULL", "None", "none", "N/A", "n/a", ""):
                            vt_criteria[k] = None

                    # Only validate required_vehicle_type in 4a
                    _all_violations = _find_invalid_ap0_fields(vt_criteria)
                    _ap0_violations_4a = {k: v for k, v in _all_violations.items()
                                          if k == "required_vehicle_type"}
                    if not _ap0_violations_4a:
                        break

                    _bad = list(_ap0_violations_4a.values())[0][0]
                    _allowed = list(_ap0_violations_4a.values())[0][1]
                    _msg = (f"required_vehicle_type='{_bad}' ungültig "
                            f"(erlaubt: {' / '.join(_allowed)}) — Versuch {_attempt + 1}/3")
                    log.warning(_msg)
                    yield sse("log", {"message": f"⚠ {_msg}"})
                    if _attempt == 2:
                        yield sse("warning", {"field": "required_vehicle_type",
                                              "message": f"{_msg} — Keyword-Fallback wird verwendet"})

            except Exception as e:
                log.exception("Pass 4a fehlgeschlagen")
                yield sse("log", {"message": f"⚠ 4a Fehler: {e} — Keyword-Fallback"})

            # Normalize vehicle type from 4a result
            raw_vt_str = vt_criteria.get("required_vehicle_type") or ""
            if isinstance(raw_vt_str, list):
                raw_vt_str = next(
                    (item for item in raw_vt_str if _VT_MAP_CFG.get(str(item).lower().strip())),
                    raw_vt_str[0] if raw_vt_str else ""
                ) or ""
            raw_vt_lower = str(raw_vt_str).lower().strip()
            canonical_agv_type = _VT_MAP_CFG.get(raw_vt_lower) or agv_type_keyword_fallback(text or "")

            # VNA detection: LLM output from 4a + text_overrides
            is_vna_subtype = raw_vt_lower in _VNA_CFG or bool(vt_criteria.get("required_vna"))
            for override in _VT_OVERRIDES:
                if override.get("regex") and re.search(override["regex"], text or ""):
                    if override.get("canonical"):
                        canonical_agv_type = override["canonical"]
                    if override.get("vna"):
                        is_vna_subtype = True
                    break

            vna_label = " (VNA)" if is_vna_subtype else ""
            log.info("Pass 4a: vehicle_type=%s%s", canonical_agv_type, vna_label)
            # Pre-compute 4c field set now that vehicle type is known; needed for progress total
            _4c_fields = {
                k: v for k, v in _NUMERIC_KO_FIELD_HINTS.items()
                if v["sheet"] in (_SHARED_SHEET, canonical_agv_type)
            }
            _agv_total = 2 + len(_4c_fields)   # 4a(1) + 4b(1) + N×4c
            yield sse("step", {"id": "agv", "status": "running",
                                "message": f"Fahrzeugtyp: {canonical_agv_type}{vna_label} — Kriterien werden extrahiert…",
                                "done": 1, "total": _agv_total})
            await asyncio.sleep(0)

            # ── Pass 4b: extract type-specific fields ─────────────────────────
            _TEXT_TOKEN_ESTIMATE = len(text) // 4
            _FIXED_OVERHEAD_TOKENS = 10_100  # AGV_SYSTEM (~5500) + 4b template (~4600)
            _TOTAL_ESTIMATE = _TEXT_TOKEN_ESTIMATE + _FIXED_OVERHEAD_TOKENS
            if _TOTAL_ESTIMATE > _OLLAMA_NUM_CTX:
                yield sse("log", {
                    "message": (
                        f"⚠ Dokument zu groß für zuverlässige Extraktion "
                        f"(~{_TOTAL_ESTIMATE:,} Token geschätzt, Limit: {_OLLAMA_NUM_CTX:,}). "
                        f"Bitte nur den technischen Spezifikationsteil hochladen "
                        f"(typischerweise 5–15 Seiten) statt des vollständigen Ausschreibungsdokuments. "
                        f"Ergebnisse können unvollständig sein."
                    )
                })

            template_4b = _AGV_TYPE_TEMPLATES.get(canonical_agv_type, AGV_USER_TEMPLATE)
            vna_context = _vehicle_cfg.get("vna_context_hint", "") if is_vna_subtype else ""
            agv_user_4b = _fill(template_4b, text=text,
                                vehicle_type=canonical_agv_type, vna_context=vna_context)

            agv_criteria: dict = {}
            _ap0_warnings: list = []
            _ap0_violations: dict = {}
            try:
                for _attempt in range(3):
                    if _attempt == 0:
                        raw_agv = await call_ollama(AGV_SYSTEM, agv_user_4b, "agv_4b")
                        try:
                            agv_criteria = repair_and_parse(raw_agv)
                        except ValueError:
                            log.warning("4b-Antwort kein JSON — Retry mit typ-spezifischem Template")
                            yield sse("log", {"message": "4b: Kein JSON → Retry mit typ-spezifischem Template…"})
                            raw_agv2 = await call_ollama(AGV_RETRY_SYSTEM, agv_user_4b, "agv_4b_retry")
                            agv_criteria = repair_and_parse(raw_agv2)
                    else:
                        correction_user = _build_correction_prompt(_ap0_violations, text)
                        raw_agv = await call_ollama(AGV_RETRY_SYSTEM, correction_user,
                                                    f"agv_4b_correction{_attempt}")
                        try:
                            correction = repair_and_parse(raw_agv)
                        except ValueError:
                            log.warning("4b AP0-Korrektur kein JSON — Versuch %d/3", _attempt + 1)
                            correction = {}
                        for _tk in _ap0_violations:
                            if _tk in correction:
                                agv_criteria[_tk] = correction[_tk]

                    agv_criteria.pop("_parse_method", None)
                    for k, v in list(agv_criteria.items()):
                        if v in ("null", "NULL", "None", "none", "N/A", "n/a", ""):
                            agv_criteria[k] = None

                    # AP0 validation for 4b fields — skip fields already validated in 4a
                    _ap0_violations = _find_invalid_ap0_fields(agv_criteria, skip=_4A_SKIP)
                    if not _ap0_violations:
                        break

                    _viol_summary = "; ".join(
                        f"{tk}='{bad}' (allowed: {', '.join(av)})"
                        for tk, (bad, av) in _ap0_violations.items()
                    )
                    log.warning("4b AP0-Feldvalidierung Versuch %d/3: %s", _attempt + 1, _viol_summary)
                    yield sse("log", {"message": f"AP0-Feldvalidierung Versuch {_attempt + 1}/3: {_viol_summary}"})
                    if _attempt == 2:
                        _ap0_warnings = [
                            f"{tk}: '{bad}' nach 3 Versuchen kein gültiger AP0-Wert "
                            f"(erlaubt: {', '.join(av)}) — Feld wird ignoriert"
                            for tk, (bad, av) in _ap0_violations.items()
                        ]

                for w in _ap0_warnings:
                    log.error("AP0-Feldvalidierung: %s", w)
                    _tk = w.split(":")[0]
                    yield sse("warning", {"field": _tk, "message": w})

            except Exception as e:
                log.exception("Pass 4b fehlgeschlagen")
                yield sse("log", {"message": f"⚠ 4b Fehler: {e}"})

            yield sse("step", {"id": "agv", "status": "running",
                                "message": "Pass 4b: Batch-Extraktion abgeschlossen",
                                "done": 2, "total": _agv_total})
            await asyncio.sleep(0)

            # ── Pass 4c: per-field extraction for numeric KO fields ──────────────
            # Each numeric KO field gets its own focused LLM call (one field + document).
            # Shorter prompt → more attention budget per field → fewer inference hallucinations.
            # Results override 4b values; source-span enforcement (below) still applies.
            # canonical_agv_type == AP0 sheet name ("Forklift AGV", "Tugger AGV", "Mobile AMR")
            if _4c_fields:
                yield sse("step", {"id": "agv", "status": "running",
                                   "message": f"Pass 4c: {len(_4c_fields)} numerische Felder einzeln…",
                                   "done": 2, "total": _agv_total})
                await asyncio.sleep(0)
                _4c_count    = 0
                _4c_abstained: set = set()   # fields where 4c returned null (used in enforcement below)
                for _4c_i, (_fk, _fmeta) in enumerate(_4c_fields.items(), start=1):
                    # Semantic definition only — NULL RULE / CONSERVATIVE EXTRACTION prose stripped
                    # to avoid tripling the null-bias already present in the system prompt.
                    _fhint_full = _fmeta["hint"]
                    _fhint_def  = _fhint_full.split("NULL RULE:")[0].strip()
                    _per_user = (
                        f"Vehicle type: {canonical_agv_type}. {vna_context}\n\n"
                        f"Find the value of '{_fk}' in the tender document.\n\n"
                        f"Field meaning: {_fhint_def}\n\n"
                        f"Step 1: Scan the document for any sentence, table cell, or labelled line "
                        f"that states this value directly.\n"
                        f"Step 2: If found, copy it verbatim as the source and extract the number "
                        f"(note: commas in numbers are thousands separators — '1,000' means 1000). "
                        f"{_4C_EXTRACTION_DIRECTION.get(_fk, '')}\n"
                        f"Step 3: If not found anywhere in the document text, output null for both "
                        f"— do NOT infer from vehicle type, warehouse layout, or industry standards.\n\n"
                        f"DOCUMENT:\n{text}\n\n"
                        f"Output ONLY this JSON:\n"
                        f'{{"{_fk}": <number or null>, "{_fk}_source": "<verbatim quote or null>"}}'
                    )
                    try:
                        _per_raw    = await call_ollama(AGV_SYSTEM, _per_user, f"agv_4c_{_fk}")
                        _per_parsed = repair_and_parse(_per_raw)
                        if _fk in _per_parsed:
                            _4c_val = _per_parsed[_fk]
                            _4c_src = _per_parsed.get(f"{_fk}_source")
                            if _4c_val is not None:
                                # 4c found a value → use it (focused extraction wins)
                                agv_criteria[_fk]              = _4c_val
                                agv_criteria[f"{_fk}_source"]  = _4c_src
                                _4c_count += 1
                            else:
                                # 4c explicitly returned null → abstained
                                _4c_abstained.add(_fk)
                            log.debug("4c %s: %s (src: %s)", _fk, _4c_val,
                                      str(_4c_src or "")[:60])
                        else:
                            # Field key absent from parsed dict (regex-fallback path) → abstained
                            _4c_abstained.add(_fk)
                            log.debug("4c %s: field absent in parse result → abstained", _fk)
                    except Exception as _pe:
                        # Parse or call failure → abstained so L2 can still check 4b value
                        _4c_abstained.add(_fk)
                        log.warning("4c '%s' fehlgeschlagen (→ abstained): %s", _fk, _pe)
                    yield sse("step", {"id": "agv", "status": "running",
                                       "message": f"Pass 4c ({_4c_i}/{len(_4c_fields)})",
                                       "done": 2 + _4c_i, "total": _agv_total})
                    await asyncio.sleep(0)
                log.info("Pass 4c: %d Felder neu extrahiert, %d abstained",
                         _4c_count, len(_4c_abstained))

            # ── Source-span enforcement (generic, field-agnostic) ────────────────
            # Layer 1: source absent/null → LLM had no explicit source → null value.
            # Layer 0: source present but not grounded in the real document → null
            #   (catches a fabricated value with a fabricated-but-self-consistent
            #   quote; runs unconditionally, not scoped to 4c abstention).
            # Layer 2 (scoped to 4c abstentions): 4c said null AND 4b source doesn't
            #   numerically confirm the value → 4b was likely hallucinating → null value.
            # See src/json_repair.py::enforce_source_spans for the full logic.
            _4c_abstained_ref = _4c_abstained if _4c_fields else set()
            agv_criteria, _span_messages = enforce_source_spans(
                agv_criteria, text, _NUMERIC_KO_TENDER_KEYS, _4c_abstained_ref
            )
            for _msg in _span_messages:
                yield sse("log", {"message": _msg})

            # Merge 4a results into agv_criteria
            agv_criteria["required_vehicle_type"] = vt_criteria.get("required_vehicle_type")
            agv_criteria["required_vna"]          = vt_criteria.get("required_vna")

            # Validate against AP0 allowed_values — reject values not in the allowed list
            from src.matching import validate_tender_values
            agv_criteria, av_warnings = validate_tender_values(agv_criteria)
            for w in av_warnings:
                log.info("AP0 allowed_values filter: %s", w)
                yield sse("log", {"message": f"⚠ AP0-Filter: {w}"})

            # Validate plausibility — set implausible values to null
            agv_criteria, val_warnings = validate_agv_criteria(agv_criteria)
            if val_warnings:
                for w in val_warnings:
                    yield sse("log", {"message": f"⚠ Plausibilität: {w}"})
            agv_criteria["_validation_warnings"] = val_warnings

            log.info("AGV-Kriterien (validiert): %s", json.dumps(agv_criteria, ensure_ascii=False)[:300])

            # Field text fallbacks: apply regex-based overrides for fields the LLM missed.
            # Rules loaded from config/vehicle_types.json → field_text_fallbacks (AP0-driven).
            for _fb in _FIELD_TEXT_FALLBACKS:
                _key  = _fb.get("tender_key")
                _rgx  = _fb.get("regex")
                _val  = _fb.get("value")
                if not _key or not _rgx or not _val:
                    continue
                if _fb.get("only_if_null") and agv_criteria.get(_key) is not None:
                    continue
                if re.search(_rgx, text or ""):
                    agv_criteria[_key] = _val
                    log.info("Field-text-fallback: %s = %s (regex: %s)", _key, _val, _rgx)

            # Run matching — prefer new SQLite engine, fall back to CSV
            if _DB_AVAILABLE and _SUPPLIERS:
                # canonical_agv_type and is_vna_subtype already set in Pass 4a;
                # re-derive here as safety net (idempotent for valid values).
                raw_vt = agv_criteria.get("required_vehicle_type") or ""
                if isinstance(raw_vt, list):
                    raw_vt = next(
                        (item for item in raw_vt if _VT_MAP_CFG.get(str(item).lower().strip())),
                        raw_vt[0] if raw_vt else "",
                    ) or ""
                raw_vt_lower = str(raw_vt).lower().strip()
                canonical_agv_type = _VT_MAP_CFG.get(raw_vt_lower) or canonical_agv_type

                for override in _VT_OVERRIDES:
                    if override.get("regex") and re.search(override["regex"], text or ""):
                        if override.get("canonical"):
                            canonical_agv_type = override["canonical"]
                        if override.get("vna"):
                            is_vna_subtype = True
                        break

                # Split navigation string into list (e.g. "SLAM, QR Code" → ["SLAM", "QR Code"])
                raw_nav = agv_criteria.get("required_navigation") or ""
                nav_list = [n.strip() for n in raw_nav.replace(";", ",").split(",") if n.strip()] if raw_nav else []

                # Store canonical type and VNA flag in agv_criteria for the frontend
                agv_criteria["required_vehicle_type_canonical"] = canonical_agv_type
                agv_criteria["_vna_subtype"] = is_vna_subtype
                if is_vna_subtype and not agv_criteria.get("required_vna"):
                    agv_criteria["required_vna"] = True

                new_req = dict(agv_criteria)
                new_req["required_vehicle_type"] = canonical_agv_type
                new_req["required_navigation"] = nav_list

                raw_lift_m = agv_criteria.get("required_max_lift_height_m")
                new_req["required_max_lift_height_m"] = int(float(raw_lift_m) * 1000) if raw_lift_m is not None else None
                raw_aisle_m = agv_criteria.get("required_min_aisle_width_m")
                new_req["required_min_aisle_width_m"] = int(float(raw_aisle_m) * 1000) if raw_aisle_m is not None else None

                raw_outdoor = agv_criteria.get("required_outdoor")
                if raw_outdoor is not None:
                    new_req["required_outdoor"] = (
                        "required" if str(raw_outdoor).lower() in ("yes", "true", "required") else "not_required"
                    )

                new_req["required_vna"] = (
                    "required"     if is_vna_subtype else
                    "not_required" if canonical_agv_type in _VNA_APPLICABLE else
                    None
                )
                matches, matches_all = match_suppliers_new(new_req, _SUPPLIERS, top_n=5)
            else:
                matches, matches_all = supplier_db.match_suppliers(agv_criteria, top_n=5)
            log.info("Matching: Top-Match %s (Score %d)", matches[0]["product"] if matches else "–",
                     matches[0]["score"] if matches else 0)

            yield sse("step", {"id": "agv", "status": "done",
                                "message": f"AGV-Analyse fertig · Top-Match: {matches[0]['product'] if matches else '–'}"})
            yield sse("log", {"message": f"AGV-Kriterien extrahiert | Top-Score: {matches[0]['score'] if matches else 0} | {len(matches_all)} Supplier bewertet"})

        # ── Final result ──────────────────────────────────────────────────────
        total = (datetime.now() - t0).total_seconds()
        result["filename"]     = filename
        result["text_length"]  = len(text)
        result["duration_s"]   = round(total, 1)
        result["parse_method"] = parse_method
        result["agv_criteria"] = agv_criteria
        result["matches"]      = matches
        result["matches_all"]  = matches_all if matches_all else []

        yield sse("log", {"message": f"Gesamt: {total:.1f}s"})
        yield sse("result", result)
        log.info("=== Fertig: %s in %.1fs ===", filename, total)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/db-status")
async def db_status():
    return {
        "sqlite_available": _DB_AVAILABLE,
        "supplier_count":   len(_SUPPLIERS),
        "message": "Using SQLite matching engine" if _DB_AVAILABLE else "Using CSV fallback — run sync_airtable.py",
    }


@app.post("/match")
async def match_endpoint(request: Request):
    """Direct matching API — accepts structured tender requirements JSON."""
    if not _DB_AVAILABLE or not _SUPPLIERS:
        return JSONResponse({"error": "SQLite DB not available. Run sync_airtable.py first."}, status_code=503)
    body = await request.json()
    top, all_results = match_suppliers_new(body, _SUPPLIERS, top_n=10)
    return {"top": top, "all": all_results, "total": len(all_results)}


@app.get("/api/field-meta")
async def field_meta():
    """Return AP0 field metadata for the frontend — labels, levels, data types.
    Loaded from config/field_levels.json (generated from AP0 xlsx, never hardcoded)."""
    field_levels_path = _CONFIG_DIR / "field_levels.json"
    if not field_levels_path.exists():
        return JSONResponse({"error": "field_levels.json not found — run generate_all.py"}, status_code=503)
    fl = json.loads(field_levels_path.read_text())
    # Build a label from the AP0 field name (snake_case → Title Case words)
    def _label(key: str) -> str:
        return " ".join(w.capitalize() for w in key.replace("_", " ").split())
    meta = {}
    for db_key, info in fl.items():
        tender_key = info.get("tender_key")
        meta[db_key] = {
            "label":      _label(db_key),
            "tender_key": tender_key,
            "level":      info.get("level"),
            "data_type":  info.get("data_type"),
            "operator":   info.get("operator"),
        }
        if tender_key and tender_key != db_key:
            meta[tender_key] = {
                "label":      _label(tender_key),
                "tender_key": tender_key,
                "level":      info.get("level"),
                "data_type":  info.get("data_type"),
                "operator":   info.get("operator"),
            }
    return meta


@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://localhost:11434/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
        model_ok = OLLAMA_MODEL in models
        return {
            "status": "ok" if model_ok else "degraded",
            "ollama": "running",
            "model": OLLAMA_MODEL,
            "model_available": model_ok,
            "models": models,
        }
    except Exception:
        return {"status": "degraded", "ollama": "not reachable", "model_available": False}
