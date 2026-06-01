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
FIELD_DESC     = BASE_DIR / "config" / "field_descriptions.json"
FIELD_LVL      = BASE_DIR / "config" / "field_levels.json"
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


def _load_field_descriptions() -> dict:
    if FIELD_DESC.exists():
        with open(FIELD_DESC) as f:
            return json.load(f)
    return {}


def _load_field_levels() -> dict:
    if FIELD_LVL.exists():
        with open(FIELD_LVL) as f:
            return json.load(f)
    return {}


def build_system_context() -> str:
    readme     = _load_readme()
    field_desc = _load_field_descriptions()
    levels     = _load_field_levels()

    ko_fields   = {k: v for k, v in levels.items() if v == "KO"}
    cond_fields = {k: v for k, v in levels.items() if v == "COND_KO"}

    field_section = ""
    if field_desc or ko_fields:
        lines = []
        for field in list(ko_fields) + list(cond_fields):
            desc = field_desc.get(field, "")
            level = levels.get(field, "")
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
"""
    return context


EXTRACTION_SYSTEM = """You are a technical procurement specialist. Extract AGV/AMR requirements from tender documents into structured JSON.
Output ONLY valid JSON. No markdown fences, no explanations.
Use JSON null (not the string "null") when a value is not found.
Dates: DD.MM.YYYY format."""

AGV_TYPE_SYSTEM = """You are a warehouse automation specialist. Classify the AGV type from tender requirements.
Output ONLY valid JSON with exactly one field: {"agv_type": "Forklift AGV" | "Tugger AGV" | "Mobile AMR" | null}
No markdown, no explanation."""

RANKING_SYSTEM = """You are a warehouse automation expert writing concise supplier evaluation summaries in English.
For each supplier in the ranking, write 2-3 sentences explaining why they rank where they do, referencing specific technical specs.
Output ONLY valid JSON."""

def _load_agv_keywords() -> dict:
    """Load keyword fallback map from vehicle_types.json (generated from AP0 xlsx)."""
    if VEHICLE_TYPES.exists():
        with open(VEHICLE_TYPES) as f:
            cfg = json.load(f)
        return cfg.get("keyword_map", {})
    # Fallback if config not yet generated
    return {
        "Forklift AGV": ["stapler", "forklift", "vna", "hubgeraet", "gabelstapler",
                         "reach truck", "schmalgangstapler", "palette", "gabeln", "high-bay"],
        "Tugger AGV":   ["tugger", "schlepper", "routenzug", "milk run", "trailer train"],
        "Mobile AMR":   ["amr", "mobile robot", "unterfahrfahrzeug", "goods-to-person",
                         "picking robot", "lagerroboter", "autonomer"],
    }

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
