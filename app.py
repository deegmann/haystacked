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

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b"

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
_VT_MAP_CFG     = _vehicle_cfg.get("vt_map", {})             # llm_output_lower → canonical
_VNA_CFG        = set(_vehicle_cfg.get("vna_subtypes", []))   # set of vna llm outputs
_VT_OVERRIDES   = _vehicle_cfg.get("text_overrides", [])      # [{regex, canonical, vna}]
_VNA_APPLICABLE = set(_vehicle_cfg.get("vna_applicable_types", []))  # C-5: types where VNA gate applies
_AGV_DETECT_KWS = _vehicle_cfg.get("agv_detection_keywords", [])     # C-1: is_agv_amr fallback keywords

# ── VNA drive type — resolved once in generate_all.py, stored in vehicle_types.json ──
# No substring-match at runtime. generate_all.py sets vna_drive_type by scanning
# field_levels["drive_type"]["allowed_values"]; if AP0 renames it, generate_all.py warns.
_VNA_DRIVE_TYPE      = _vehicle_cfg.get("vna_drive_type")
if _VNA_DRIVE_TYPE is None:
    log.warning("vna_drive_type missing from vehicle_types.json — run generate_all.py. VNA drive_type override disabled.")
_FIELD_TEXT_FALLBACKS = _vehicle_cfg.get("field_text_fallbacks", [])  # [{tender_key, regex, value, only_if_null}]

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
AGV_SYSTEM           = build_system_context() if _DB_AVAILABLE else _load_prompt("extraction_system.txt")
AGV_USER_TEMPLATE    = _load_prompt("extraction_template.txt")
AGV_RETRY_SYSTEM     = _load_prompt("extraction_retry_system.txt")
AGV_RETRY_TEMPLATE   = _load_prompt("extraction_retry_template.txt")


# ── AGV value validation ──────────────────────────────────────────────────────
# Loaded from config/plausibility.json (generated by scripts/generate_all.py from AP0 xlsx).
# Never hardcode these ranges here — edit PLAUSIBILITY_RANGES in generate_all.py instead.
_plausibility_cfg = json.loads((_CONFIG_DIR / "plausibility.json").read_text()) \
    if (_CONFIG_DIR / "plausibility.json").exists() else {}

# Build AGV_PLAUSIBILITY in the same format as before: key → (min, max, unit, label)
# The mm_to_m flag is also passed through for auto-conversion.
AGV_PLAUSIBILITY: dict[str, tuple] = {
    k: (v["min"], v["max"], v["unit"], v["label"])
    for k, v in _plausibility_cfg.items()
}
_MM_TO_M_FIELDS: set[str] = {k for k, v in _plausibility_cfg.items() if v.get("mm_to_m")}

def validate_agv_criteria(crit: dict) -> tuple:
    """
    Returns (cleaned_dict, warnings_list).
    Auto-converts mm→m where applicable (controlled by plausibility.json mm_to_m flag),
    sets implausible values to None.
    """
    MM_FIELDS = _MM_TO_M_FIELDS  # loaded from config/plausibility.json

    warnings = []
    cleaned = dict(crit)
    for field, (lo, hi, unit, label) in AGV_PLAUSIBILITY.items():
        val = cleaned.get(field)
        if val is None:
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue

        # Auto-convert mm → m for dimensional fields
        if field in MM_FIELDS and v > 10:
            v_converted = v / 1000
            if lo <= v_converted <= hi:
                warnings.append(f"{label}: {v} mm → {v_converted:.2f} m (automatisch konvertiert)")
                log.info("AGV mm→m: %s %s → %s m", label, v, v_converted)
                cleaned[field] = v_converted
                continue

        if not (lo <= v <= hi):
            warnings.append(
                f"{label}: Wert {v} {unit} außerhalb plausiblem Bereich [{lo}–{hi} {unit}] → ignoriert"
            )
            log.warning("AGV-Plausibilität: %s", warnings[-1])
            cleaned[field] = None
    return cleaned, warnings


# ── JSON repair ───────────────────────────────────────────────────────────────
def repair_and_parse(raw: str) -> dict:
    log.debug("RAW LLM (%d chars): %s", len(raw), raw[:1000])

    cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()

    start = cleaned.find("{")
    end   = cleaned.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("Kein JSON-Objekt in der Antwort")
    candidate = cleaned[start:end]

    # 1. direct
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # 2. remove JS comments
    no_comments = re.sub(r"//[^\n]*", "", candidate)
    try:
        return json.loads(no_comments)
    except json.JSONDecodeError:
        pass

    # 3. fix unescaped newlines inside strings
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

    # 4. truncation fix
    for suffix in ['"}', '"]}', ']}', '}']:
        try:
            return json.loads(fixed + suffix)
        except json.JSONDecodeError:
            pass

    # 5. regex field extraction
    log.warning("All parse attempts failed — using regex fallback")
    fields = {}
    for field in ["buyer", "project_name", "project_location", "tender_date", "deadline",
                  "contact_name", "contact_email", "contact_phone",
                  "buyer_industry", "nace_buyer", "tender_category", "nace_tender",
                  "nace_tender_name", "priority", "confidence", "summary"]:
        m = re.search(rf'"{field}"\s*:\s*"([^"]*)"', candidate)
        if m:
            fields[field] = m.group(1)
    for bool_field in ["is_agv_amr"]:
        m = re.search(rf'"{bool_field}"\s*:\s*(true|false)', candidate)
        if m:
            fields[bool_field] = m.group(1) == "true"
    if fields:
        fields["_parse_method"] = "regex_fallback"
        return fields

    raise ValueError(f"JSON-Parsing fehlgeschlagen. Roh-Antwort (erste 300 Z.): {raw[:300]}")


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
        "options": {"temperature": 0.0, "num_predict": 2048, "num_ctx": 32768},
    }
    log.info("Ollama [%s]: system=%d Z., prompt=%d Z.", label, len(system), len(user))
    t0 = datetime.now()
    async with httpx.AsyncClient(timeout=180.0) as client:
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
                                "message": "AGV-Kriterien werden extrahiert…"})
            await asyncio.sleep(0)

            agv_user = _fill(AGV_USER_TEMPLATE, text=text)
            try:
                raw_agv = await call_ollama(AGV_SYSTEM, agv_user, "agv")
                try:
                    agv_criteria = repair_and_parse(raw_agv)
                except ValueError:
                    log.warning("AGV-Antwort kein JSON — Retry mit Original-Dokument")
                    yield sse("log", {"message": "AGV-Antwort war kein JSON → Retry mit Originaldokument…"})
                    retry_user = _fill(AGV_RETRY_TEMPLATE, text=text)
                    raw_agv2 = await call_ollama(AGV_RETRY_SYSTEM, retry_user, "agv_retry")
                    agv_criteria = repair_and_parse(raw_agv2)
                agv_criteria.pop("_parse_method", None)

                # Normalize LLM null-like strings → Python None
                for k, v in agv_criteria.items():
                    if v in ("null", "NULL", "None", "none", "N/A", "n/a", ""):
                        agv_criteria[k] = None

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
                    # Normalize LLM vehicle type → canonical (loaded from vehicle_types.json)
                    raw_vt = agv_criteria.get("required_vehicle_type") or ""
                    if isinstance(raw_vt, list):
                        # LLM returned a list — pick first element that maps to a canonical type
                        raw_vt = next(
                            (item for item in raw_vt if _VT_MAP_CFG.get(str(item).lower().strip())),
                            raw_vt[0] if raw_vt else "",
                        ) or ""
                    raw_vt_lower = str(raw_vt).lower().strip()
                    canonical_agv_type = _VT_MAP_CFG.get(raw_vt_lower) or agv_type_keyword_fallback(text or "")

                    # VNA detection: check LLM output AND text overrides from vehicle_types.json
                    # (LL-05: keyword fallback supplements LLM — avoids hard-coding in Python)
                    is_vna_subtype = raw_vt_lower in _VNA_CFG
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
                    # If VNA detected via text override (LLM may have returned null for required_vna),
                    # write required_vna=True back so matching engine applies the VNA K.O. filter.
                    if is_vna_subtype and not agv_criteria.get("required_vna"):
                        agv_criteria["required_vna"] = True

                    # Build req from agv_criteria (already uses AP0 tender JSON keys).
                    # Only override fields that need unit conversion or logic-derived values.
                    new_req = dict(agv_criteria)

                    # Normalize vehicle type to canonical
                    new_req["required_vehicle_type"] = canonical_agv_type

                    # Navigation: split comma/semicolon string → list
                    new_req["required_navigation"] = nav_list

                    # Unit conversions: LLM outputs meters, supplier DB uses mm
                    raw_lift_m = agv_criteria.get("required_max_lift_height_m")
                    new_req["required_max_lift_height_m"] = int(float(raw_lift_m) * 1000) if raw_lift_m else None
                    raw_aisle_m = agv_criteria.get("required_min_aisle_width_m")
                    new_req["required_min_aisle_width_m"] = int(float(raw_aisle_m) * 1000) if raw_aisle_m else None

                    # outdoor: LLM may output "yes"/"no" → normalize to "required"/"not_required"/None
                    raw_outdoor = agv_criteria.get("required_outdoor")
                    if raw_outdoor is not None:
                        new_req["required_outdoor"] = (
                            "required" if str(raw_outdoor).lower() in ("yes", "true", "required") else "not_required"
                        )

                    # VNA flag: logic-derived from text analysis (overrides LLM value)
                    # KO_BOOL_EXCLUSIVE: required → supplier must be vna_capable=True
                    #                    not_required → supplier must NOT be vna_capable=True
                    #                    None → no constraint (non-Forklift types)
                    new_req["required_vna"] = (
                        "required"     if is_vna_subtype else
                        "not_required" if canonical_agv_type in _VNA_APPLICABLE else
                        None
                    )
                    # drive_type is CONTEXT level — no matching operator, injection removed.
                    # VNA is hard-gated via vna_capable (KO_BOOL_EXCLUSIVE) in field_levels.json.
                    matches, matches_all = match_suppliers_new(new_req, _SUPPLIERS, top_n=5)
                else:
                    matches, matches_all = supplier_db.match_suppliers(agv_criteria, top_n=5)
                log.info("Matching: Top-Match %s (Score %d)", matches[0]["product"] if matches else "–",
                         matches[0]["score"] if matches else 0)

                yield sse("step", {"id": "agv", "status": "done",
                                    "message": f"AGV-Analyse fertig · Top-Match: {matches[0]['product'] if matches else '–'}"})
                yield sse("log", {"message": f"AGV-Kriterien extrahiert | Top-Score: {matches[0]['score'] if matches else 0} | {len(matches_all)} Supplier bewertet"})

            except Exception as e:
                log.exception("AGV-Analyse fehlgeschlagen")
                yield sse("step", {"id": "agv", "status": "error", "message": f"AGV-Analyse fehlgeschlagen: {e}"})

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
        return {"status": "ok", "ollama": "running", "models": models}
    except Exception:
        return {"status": "degraded", "ollama": "not reachable"}
