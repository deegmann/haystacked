"""
Direkter Pipeline-Test für alle drei AGV-Ausschreibungen.
Führt LLM-Extraktion + Matching durch und gibt strukturierte Ergebnisse aus.

Usage: python3 scripts/test_pipeline.py
"""
import asyncio
import json
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import pdfplumber
import io

from src.data_loader import load_suppliers
from src.matching import match_suppliers_new, _field_levels
from src.context_builder import agv_type_keyword_fallback, build_system_context

ROOT = Path(__file__).parent.parent

# ── Load prompts & config ─────────────────────────────────────────────────────
def _load(f): return (ROOT / "config" / "prompts" / f).read_text(encoding="utf-8").strip()
def _fill(t, **kw):
    for k, v in kw.items():
        t = t.replace("{" + k + "}", str(v))
    return t

AGV_SYSTEM       = build_system_context()  # matches production app.py — extraction_system.txt is fallback-only
AGV_USER_TPL     = _load("extraction_template.txt")
OLLAMA_URL       = "http://localhost:11434/api/generate"
OLLAMA_MODEL     = "qwen2.5:7b"

import json as _json
_vt_cfg  = _json.loads((ROOT / "config" / "vehicle_types.json").read_text())
_VT_MAP  = _vt_cfg.get("vt_map", {})
_VNA_CFG             = set(_vt_cfg.get("vna_subtypes", []))
_VT_OVR              = _vt_cfg.get("text_overrides", [])
_VNA_APPLICABLE      = set(_vt_cfg.get("vna_applicable_types", []))
_FIELD_TEXT_FALLBACKS = _vt_cfg.get("field_text_fallbacks", [])

_plaus   = _json.loads((ROOT / "config" / "plausibility.json").read_text())
AGV_PLAUSIBILITY = {k: (v["min"], v["max"], v["unit"], v["label"])
                    for k, v in _plaus.items() if isinstance(v, dict)}
_MM_FIELDS = {k for k, v in _plaus.items() if isinstance(v, dict) and v.get("mm_to_m")}

SUPPLIERS = load_suppliers()

PDFS = [
    ROOT / "tenders" / "Mama.pdf",
    ROOT / "tenders" / "CompanyX.pdf",
    ROOT / "tenders" / "Dragonfly.pdf",
]


def extract_pdf(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        pages = [p.extract_text() for p in pdf.pages if p.extract_text()]
    return "\n\n".join(pages)[:50_000]


async def llm(system: str, prompt: str, label: str) -> str:
    payload = {
        "model": OLLAMA_MODEL, "system": system, "prompt": prompt,
        "stream": False, "options": {"temperature": 0.0, "num_predict": 2048, "num_ctx": 32768},
    }
    async with httpx.AsyncClient(timeout=180.0) as c:
        r = await c.post(OLLAMA_URL, json=payload)
        r.raise_for_status()
    return r.json().get("response", "")


def parse_json(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
    s = cleaned.find("{"); e = cleaned.rfind("}") + 1
    if s == -1: raise ValueError("No JSON")
    return json.loads(cleaned[s:e])


def validate(crit: dict) -> tuple[dict, list]:
    warnings, cleaned = [], dict(crit)
    for field, (lo, hi, unit, label) in AGV_PLAUSIBILITY.items():
        val = cleaned.get(field)
        if val is None: continue
        try: v = float(val)
        except: continue
        if field in _MM_FIELDS and v > 10:
            v2 = v / 1000
            if lo <= v2 <= hi:
                warnings.append(f"{label}: {v}mm → {v2:.2f}m (auto-konvertiert)")
                cleaned[field] = v2; continue
        if not (lo <= v <= hi):
            warnings.append(f"{label}: {v}{unit} außerhalb [{lo}–{hi}] → ignoriert")
            cleaned[field] = None
    return cleaned, warnings


async def run_one(pdf_path: Path) -> dict:
    name = pdf_path.name
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

    # 1. PDF text
    text = extract_pdf(pdf_path)
    print(f"  Extrahiert: {len(text):,} Zeichen")

    # 2. LLM AGV extraction
    print("  LLM-Extraktion läuft…")
    raw = await llm(AGV_SYSTEM, _fill(AGV_USER_TPL, text=text), "agv")
    try:
        crit = parse_json(raw)
    except Exception as e:
        print(f"  ✗ Parse-Fehler: {e}")
        return {"file": name, "error": str(e), "raw": raw[:500]}

    # Normalize LLM null-like strings → Python None
    for k, v in crit.items():
        if v in ("null", "NULL", "None", "none", "N/A", "n/a", ""):
            crit[k] = None

    # Validate against AP0 allowed_values
    from src.matching import validate_tender_values
    crit, av_warns = validate_tender_values(crit)
    for w in av_warns:
        print(f"  AP0-Filter: {w}")

    crit, val_warns = validate(crit)
    if val_warns:
        for w in val_warns:
            print(f"  ⚠ {w}")

    # 3. Normalize + build req dict
    raw_vt = crit.get("required_vehicle_type") or ""
    if isinstance(raw_vt, list):
        raw_vt = next(
            (item for item in raw_vt if _VT_MAP.get(str(item).lower().strip())),
            raw_vt[0] if raw_vt else "",
        ) or ""
    raw_vt_lower = str(raw_vt).lower().strip()
    canonical    = _VT_MAP.get(raw_vt_lower) or agv_type_keyword_fallback(text)
    is_vna       = raw_vt_lower in _VNA_CFG
    for ovr in _VT_OVR:
        if ovr.get("regex") and re.search(ovr["regex"], text):
            if ovr.get("canonical"): canonical = ovr["canonical"]
            if ovr.get("vna"):       is_vna = True
            break

    # Field text fallbacks — mirrors app.py logic
    for _fb in _FIELD_TEXT_FALLBACKS:
        _key, _rgx, _val = _fb.get("tender_key"), _fb.get("regex"), _fb.get("value")
        if not _key or not _rgx or not _val:
            continue
        if _fb.get("only_if_null") and crit.get(_key) is not None:
            continue
        if re.search(_rgx, text or ""):
            crit[_key] = _val
            print(f"  Field-text-fallback: {_key} = {_val}")

    raw_nav = crit.get("required_navigation") or ""
    nav_list = [n.strip() for n in raw_nav.replace(";", ",").split(",") if n.strip()] if raw_nav else []

    new_req = dict(crit)
    new_req["required_vehicle_type"]     = canonical
    new_req["required_navigation"]       = nav_list
    raw_lift = crit.get("required_max_lift_height_m")
    new_req["required_max_lift_height_m"] = int(float(raw_lift) * 1000) if raw_lift else None
    raw_aisle = crit.get("required_min_aisle_width_m")
    new_req["required_min_aisle_width_m"] = int(float(raw_aisle) * 1000) if raw_aisle else None
    raw_outdoor = crit.get("required_outdoor")
    if raw_outdoor is not None:
        new_req["required_outdoor"] = (
            "required" if str(raw_outdoor).lower() in ("yes", "true", "required") else "not_required"
        )
    new_req["required_vna"] = (
        "required"     if is_vna else
        "not_required" if canonical in _VNA_APPLICABLE else
        None
    )
    # required_drive_type comes from LLM via AP0 description rule (no override needed)

    # 4. Matching
    top, all_results = match_suppliers_new(new_req, SUPPLIERS, top_n=5)

    return {
        "file": name,
        "canonical_agv_type": canonical,
        "is_vna": is_vna,
        "extracted": {k: v for k, v in new_req.items() if v is not None and v != [] and not k.startswith("_")},
        "validation_warnings": val_warns,
        "top_matches": top,
        "total_evaluated": len(all_results),
        "disqualified": sum(1 for r in all_results if r.get("disqualified")),
    }


def print_result(res: dict):
    if "error" in res:
        print(f"\n  ✗ FEHLER: {res['error']}")
        return

    print(f"\n  AGV-Typ:    {res['canonical_agv_type']}  (VNA: {res['is_vna']})")
    print(f"\n  Extrahierte Anforderungen ({len(res['extracted'])} Felder):")
    for k, v in res["extracted"].items():
        print(f"    {k:45s} = {v}")

    if res["validation_warnings"]:
        print(f"\n  Plausibilitätswarnungen:")
        for w in res["validation_warnings"]:
            print(f"    ⚠ {w}")

    print(f"\n  Matching: {res['total_evaluated']} Supplier bewertet, {res['disqualified']} disqualifiziert")
    print(f"  Top-5 Ergebnisse:")
    for i, m in enumerate(res["top_matches"], 1):
        dq = " [DISQ]" if m.get("disqualified") else ""
        ko = f"  KO: {', '.join(m['disqualified_by'][:2])}" if m.get("disqualified_by") else ""
        reasons = ", ".join(m.get("reasons", [])[:3])
        print(f"    {i}. {m['company']:25s} | {m['product']:30s} | Score: {m['score']:3d}/{m['max_score']}{dq}{ko}")
        if reasons:
            print(f"       Scoring: {reasons}")


async def main():
    print("haystacked Pipeline-Test — alle drei Ausschreibungen")
    print(f"Supplier geladen: {len(SUPPLIERS)}")
    print(f"field_levels: {len(_field_levels)} Felder")

    results = []
    for pdf in PDFS:
        if not pdf.exists():
            print(f"\n✗ Nicht gefunden: {pdf}")
            continue
        res = await run_one(pdf)
        print_result(res)
        results.append(res)

    # Summary
    print(f"\n\n{'='*60}")
    print("ZUSAMMENFASSUNG")
    print(f"{'='*60}")
    for res in results:
        if "error" in res:
            print(f"  {res['file']:20s}  ✗ FEHLER")
        else:
            top = res["top_matches"][0] if res["top_matches"] else None
            top_str = f"{top['company']} / {top['product']} (Score {top['score']})" if top else "–"
            print(f"  {res['file']:20s}  {res['canonical_agv_type']:15s}  Top: {top_str}")


if __name__ == "__main__":
    asyncio.run(main())
