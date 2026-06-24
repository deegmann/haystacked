"""
AP-I2 — Prompt Context Builder
Embeds the Industry Readme + field-level descriptions into the LLM system prompt.
Budget: ~20,000 tokens. Total context window: num_ctx=32768.
"""
import json
from pathlib import Path

BASE_DIR   = Path(__file__).parent.parent
# README lookup order: local config copy (always present), then Synology (if mounted)
_README_LOCAL  = BASE_DIR / "config" / "industry_readme.md"
_README_REMOTE = BASE_DIR.parent.parent.parent / "Library" / "CloudStorage" / "SynologyDrive-homeDrive" / "Haystacked" / "Specs" / "haystacked_industry_readme.md"
README         = _README_LOCAL if _README_LOCAL.exists() else _README_REMOTE
VEHICLE_TYPES  = BASE_DIR / "config" / "vehicle_types.json"

_FALLBACK_README = """
haystacked Industry Context:
- AGV/AMR classification is derived from properties (navigation, lift, rotation, grid) not from vendor labels.
- AGV vs AMR: infrastructure-bound (magnetic tape, QR codes, reflectors) = classic AGV; free-navigating (SLAM, contour) = AMR.
- G2P (Goods-to-Person): robots bring pods to fixed picking station (rotation_capable=true, grid_required=true).
- Tugger AGVs tow trailer trains. Cannot interface with conveyor belts without manual reloading.
- VNA = Very Narrow Aisle, requires min_aisle_width_mm <= 1800, vna_capable=true.
- Blank != Zero: NULL means unknown, never absent. NULL reference_count is NOT 0 references.
- OEM rebadging: same physical machine may be sold under multiple brand names.
- Battery: Li-Ion supports opportunity charging. Lead-Acid needs dedicated charging rooms.
- VDA 5050: open interface standard for mixed-vendor fleets, increasingly mandatory in Europe.
"""


def _load_readme() -> str:
    if README.exists():
        return README.read_text(encoding="utf-8")
    return _FALLBACK_README


def build_system_context() -> str:
    readme = _load_readme()
    from src.field_spec import load_fields
    _seen: set = set()
    ko_fields:   dict = {}
    cond_fields: dict = {}
    for _spec in load_fields().values():
        if _spec.field_name in _seen:
            continue
        _seen.add(_spec.field_name)
        if _spec.level == "KO":
            ko_fields[_spec.field_name] = _spec
        elif _spec.level == "COND_KO":
            cond_fields[_spec.field_name] = _spec

    field_section = ""
    if ko_fields:
        lines = []
        for field, spec in list(ko_fields.items()) + list(cond_fields.items()):
            desc  = spec.user_description or ""
            level = spec.level or ""
            lines.append(f"  {field} [{level}]: {desc}" if desc else f"  {field} [{level}]")
        field_section = "## Field-level descriptions (K.O. and Cond. K.O.)\n" + "\n".join(lines)

    context = f"""SYSTEM CONTEXT -- haystacked Matching Engine

## Industry domain knowledge
{readme}

{field_section}

## Critical matching rules
1. K.O. fields: a supplier failing even one K.O. criterion is fully excluded.
2. Cond. K.O. fields: score by default; hard filter ONLY when buyer marks them as "required".
3. Blank != zero: NULL means unknown, never absent. Do not infer a capability is absent because a field is empty. NULL reference_count is NOT 0 references.
4. OEM rebadging: same physical machine under multiple brand names shares technical specs.
5. AGV type classification: derive from properties, never from vendor label alone. Use navigation_type, lift capability, towing, workflow -- not product name.
6. Tugger AGVs cannot interface with conveyor belts -- if conveyors are required, Tugger is not appropriate.
7. VDA 5050 is an open fleet interface standard -- increasingly a hard requirement for large European buyers.
8. CONSERVATIVE VALUE EXTRACTION (critical): When a document lists multiple values for the same parameter, always extract the most demanding value. For minimum-capability fields (payload, lift height, operating hours, fleet size, maximum ambient temperature): extract the MAXIMUM value found -- the supplier must meet or exceed this. For maximum-constraint fields (aisle width, minimum ambient temperature): extract the MINIMUM value found -- the supplier must fit within this limit. Never average or omit ambiguous values -- always pick the worst case for the supplier.
9. ANTI-HALLUCINATION (critical): Before outputting any non-null value you must be able to identify the exact sentence in the document that states it. Do NOT infer specifications from warehouse type or AGV type -- a VNA warehouse does NOT imply IP65, cold-storage temperature, high humidity, ramp gradient, or VDA 5050 unless these are written in the document. Do NOT read numbers from dates, filenames, revision codes, version strings, or project metadata as specification values -- '25th May 2022' is a date, NOT a temperature; 'v1.3' is a version, NOT a floor flatness value. If a field's value is not directly stated in the document text, output null -- never apply typical industry values.
"""
    return context


def _load_agv_keywords() -> dict:
    """Load keyword map from vehicle_types.json (generated from AP0 xlsx)."""
    if VEHICLE_TYPES.exists():
        with open(VEHICLE_TYPES) as f:
            cfg = json.load(f)
        return cfg.get("keyword_map", {})
    return {}

AGV_KEYWORDS = _load_agv_keywords()


def agv_type_keyword_fallback(text: str) -> "str | None":
    """Independent from LLM. Checks first 5,000 chars. Per LL-05."""
    excerpt = text[:5000].lower()
    scores  = {
        t: sum(1 for kw in kws if kw in excerpt)
        for t, kws in AGV_KEYWORDS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None
