"""
Supplier database loaded from the AGV/AMR CSV.
Provides structured access and a rule-based matching algorithm.
"""
import csv
import re
import json
import logging
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger("haystacked.supplier")

CSV_PATH = Path(__file__).parent / "data" / "supplier_db.csv"

# ── Parse CSV ─────────────────────────────────────────────────────────────────
def _load() -> list[dict]:
    # Use csv.reader so quoted fields with embedded semicolons are handled
    # correctly (e.g. the "Example answers" column often contains lists like
    # '"VNA"; "Tugger"; "Stacker"' which break naive split(";")).
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        raw_rows = list(csv.reader(f, delimiter=";"))

    header   = [h.strip() for h in raw_rows[0]]
    products = [h for h in header[3:] if h.strip()]

    rows: dict[str, dict] = {}
    for raw in raw_rows[1:]:
        crit = raw[0].strip() if raw else ""
        if not crit:
            continue
        rows[crit] = {}
        for i, prod in enumerate(products):
            val = raw[i + 3].strip() if i + 3 < len(raw) else ""
            rows[crit][prod] = val

    suppliers = []
    for prod in products:
        s = {"product": prod}
        for crit, vals in rows.items():
            key = (crit.lower()
                   .replace(" ", "_").replace("/", "_")
                   .replace("(", "").replace(")", "").strip("_"))
            s[key] = vals.get(prod, "")
        suppliers.append(s)

    log.info("Supplier DB geladen: %d Produkte", len(suppliers))
    return suppliers


SUPPLIERS: list[dict] = _load()


# ── Numerical helpers ─────────────────────────────────────────────────────────
def _extract_number(s: str) -> Optional[float]:
    """Extract first float from a messy string like '4535 kg (towing)'."""
    m = re.search(r"[\d]+(?:[.,]\d+)?", s.replace(",", "."))
    if m:
        try:
            return float(m.group().replace(",", "."))
        except ValueError:
            return None
    return None


def _temp_range(s: str) -> Optional[Tuple[float, float]]:
    """Parse '0°-40°C' or '-25°C' into (min, max)."""
    nums = re.findall(r"-?\d+(?:\.\d+)?", s)
    if len(nums) >= 2:
        return float(nums[0]), float(nums[1])
    if len(nums) == 1:
        return float(nums[0]), float(nums[0])
    return None


def _matches_text(requirement: str, supplier_val: str) -> bool:
    """Case-insensitive substring check across semicolon-separated values."""
    if not requirement or not supplier_val or supplier_val.upper() == "N/A":
        return False
    req_lower = requirement.lower()
    sup_lower = supplier_val.lower()
    keywords = [k.strip() for k in req_lower.split()]
    return any(kw in sup_lower for kw in keywords if len(kw) > 2)


# ── Criterion tiers ───────────────────────────────────────────────────────────
# Must-haves: if a stated requirement is not met → supplier is disqualified.
# Nice-to-haves: matched criteria improve the score but never disqualify.
MUST_HAVE_SCORE = {
    "required_weight_capacity_kg": 25,
    "required_min_aisle_width_m":  20,
    "required_max_lift_height_m":  20,
    "required_temp_min_c":         15,
}
NICE_TO_HAVE_SCORE = {
    "required_max_speed_ms":         10,
    "required_navigation":            5,
    "required_process":               5,
    "required_wms_integration":       5,
    "required_conveyor_integration":  5,
    "required_vehicle_type":          5,
}
MAX_SCORE = sum(MUST_HAVE_SCORE.values()) + sum(NICE_TO_HAVE_SCORE.values())  # 110


def match_suppliers(req: dict, top_n: int = 5) -> list[dict]:
    """
    Score each supplier against requirements.
    Must-have failures set disqualified=True; nice-to-haves only affect score.
    Returns top_n results: qualified suppliers first (by score), then disqualified.
    """
    results = []

    weight_req   = _extract_number(str(req.get("required_weight_capacity_kg", "") or ""))
    aisle_req    = _extract_number(str(req.get("required_min_aisle_width_m",  "") or ""))
    lift_req     = _extract_number(str(req.get("required_max_lift_height_m",  "") or ""))
    speed_req    = _extract_number(str(req.get("required_max_speed_ms",        "") or ""))
    temp_min_req = _extract_number(str(req.get("required_temp_min_c",          "") or ""))

    for sup in SUPPLIERS:
        score       = 0
        reasons     = []
        knockouts   = []
        disqualified = False

        # ── MUST-HAVE: Weight capacity (25 pts) ───────────────────────────────
        if weight_req is not None:
            sup_w = _extract_number(sup.get("weight_capacity", ""))
            if sup_w is not None:
                if sup_w >= weight_req:
                    score += MUST_HAVE_SCORE["required_weight_capacity_kg"]
                    reasons.append(f"Traglast OK ({sup_w:.0f} kg ≥ {weight_req:.0f} kg)")
                else:
                    knockouts.append(f"Traglast zu gering ({sup_w:.0f} kg < {weight_req:.0f} kg)")
                    disqualified = True

        # ── MUST-HAVE: Min aisle width (20 pts) ───────────────────────────────
        if aisle_req is not None:
            sup_a = _extract_number(sup.get("min_aisle_width", ""))
            if sup_a is not None:
                if sup_a > 10:
                    sup_a = sup_a / 1000
                if sup_a <= aisle_req:
                    score += MUST_HAVE_SCORE["required_min_aisle_width_m"]
                    reasons.append(f"Gangbreite OK ({sup_a:.2f} m ≤ {aisle_req:.2f} m)")
                else:
                    knockouts.append(f"Gangbreite zu groß ({sup_a:.2f} m > {aisle_req:.2f} m)")
                    disqualified = True

        # ── MUST-HAVE: Max lift height (20 pts) ───────────────────────────────
        if lift_req is not None:
            sup_l = _extract_number(sup.get("max_lift_height", ""))
            if sup_l is not None:
                if sup_l > 50:
                    sup_l = sup_l / 1000
                if sup_l >= lift_req:
                    score += MUST_HAVE_SCORE["required_max_lift_height_m"]
                    reasons.append(f"Hubhöhe OK ({sup_l:.1f} m ≥ {lift_req:.1f} m)")
                else:
                    knockouts.append(f"Hubhöhe zu gering ({sup_l:.1f} m < {lift_req:.1f} m)")
                    disqualified = True

        # ── MUST-HAVE: Temperature range (15 pts) ─────────────────────────────
        sup_temp = _temp_range(sup.get("temperature_range", ""))
        if sup_temp and temp_min_req is not None:
            if sup_temp[0] <= temp_min_req:
                score += MUST_HAVE_SCORE["required_temp_min_c"]
                reasons.append(f"Temperatur OK (ab {sup_temp[0]:.0f}°C)")
            else:
                knockouts.append(f"Temperatur zu hoch (min {sup_temp[0]:.0f}°C)")
                disqualified = True

        # ── NICE-TO-HAVE: Speed (10 pts) ──────────────────────────────────────
        if speed_req is not None:
            sup_s = _extract_number(sup.get("max_speed", ""))
            if sup_s is not None:
                if sup_s >= speed_req:
                    score += NICE_TO_HAVE_SCORE["required_max_speed_ms"]
                    reasons.append(f"Geschwindigkeit OK ({sup_s:.1f} m/s)", )
                else:
                    reasons.append(f"Geschwindigkeit grenzwertig ({sup_s:.1f} m/s)")

        # ── NICE-TO-HAVE: Navigation (5 pts) ──────────────────────────────────
        nav_req = str(req.get("required_navigation", "") or "")
        if nav_req and _matches_text(nav_req, sup.get("navigation", "")):
            score += NICE_TO_HAVE_SCORE["required_navigation"]
            reasons.append(f"Navigation passt ({nav_req})")

        # ── NICE-TO-HAVE: Process (5 pts) ─────────────────────────────────────
        proc_req = str(req.get("required_process", "") or "")
        if proc_req and _matches_text(proc_req, sup.get("process", "")):
            score += NICE_TO_HAVE_SCORE["required_process"]
            reasons.append("Prozess passt")

        # ── NICE-TO-HAVE: WMS integration (5 pts) ─────────────────────────────
        if str(req.get("required_wms_integration", "")).lower() in ("yes", "ja", "true"):
            wms = sup.get("integration_with_wms", "")
            if wms and wms.upper() != "N/A" and "yes" in wms.lower():
                score += NICE_TO_HAVE_SCORE["required_wms_integration"]
                reasons.append("WMS-Integration vorhanden")

        # ── MUST-HAVE: Conveyor integration (5 pts, disqualifies if missing) ────
        # Tugger AGVs tow trailers floor-to-floor and cannot interface with
        # conveyor belts — if a tender requires conveyor integration, suppliers
        # without it (or Tugger-only products) are disqualified.
        if str(req.get("required_conveyor_integration", "")).lower() in ("yes", "ja", "true"):
            conv = sup.get("integration_with_conveyors", "")
            if conv and "yes" in conv.lower():
                score += NICE_TO_HAVE_SCORE["required_conveyor_integration"]
                reasons.append("Förderanlagen-Integration vorhanden")
            else:
                knockouts.append("Keine Förderanlagen-Integration (Conveyor-Interface erforderlich)")
                disqualified = True

        # ── NICE-TO-HAVE: Vehicle type (5 pts) ────────────────────────────────
        veh_req = str(req.get("required_vehicle_type", "") or "")
        if veh_req and _matches_text(veh_req, sup.get("vehicle_types", "")):
            score += NICE_TO_HAVE_SCORE["required_vehicle_type"]
            reasons.append(f"Fahrzeugtyp passt ({veh_req})")

        results.append({
            "product":        sup["product"],
            "company":        sup.get("company_name", ""),
            "score":          score,
            "max_score":      MAX_SCORE,
            "disqualified":   disqualified,
            "reasons":        reasons,
            "knockouts":      knockouts,
            "website":        sup.get("website", ""),
            "origin":         sup.get("origin", ""),
            "vehicle_types":  sup.get("vehicle_types", ""),
            "weight_capacity": sup.get("weight_capacity", ""),
            "max_lift_height": sup.get("max_lift_height", ""),
            "min_aisle_width": sup.get("min_aisle_width", ""),
            "max_speed":      sup.get("max_speed", ""),
            "navigation":     sup.get("navigation", ""),
            "description":    sup.get("company_application_description_and_key_strenghts", ""),
        })

    # Qualified first (by score desc), then disqualified (by score desc)
    qualified         = sorted([r for r in results if not r["disqualified"]], key=lambda x: -x["score"])
    disqualified_list = sorted([r for r in results if r["disqualified"]],     key=lambda x: -x["score"])
    ranked = qualified + disqualified_list

    log.info(
        "Matching: %d qualifiziert, %d disqualifiziert — Top-Scores: %s",
        len(qualified), len(disqualified_list),
        [r["score"] for r in ranked[:top_n]],
    )
    # Return top_n for display + full ranked list for debugging
    for i, r in enumerate(ranked):
        r["rank"] = i + 1
    return ranked[:top_n], ranked


def get_agv_criteria_for_prompt() -> str:
    """Return the list of AGV criteria the LLM should extract from a tender."""
    return """
Extrahiere AGV/AMR-spezifische Anforderungen als JSON:
{
  "is_agv_amr_tender": true,
  "required_vehicle_type": "VNA / Reach Truck / Tugger / Picking AMR / Underride AMR / etc.",
  "required_weight_capacity_kg": 1500,
  "required_max_speed_ms": 2.0,
  "required_min_aisle_width_m": 1.4,
  "required_max_lift_height_m": 12.0,
  "required_temp_min_c": 5,
  "required_temp_max_c": 30,
  "required_navigation": "SLAM / QR Code / Laser / Reflectors / Natural Features",
  "required_process": "Goods to Person / Picking / Inbound / Outbound / Replenishment",
  "required_wms_integration": "yes",
  "required_conveyor_integration": "yes",
  "required_outdoor": "no",
  "required_clean_room": "no",
  "required_load_types": "EUR pallets 1200x800",
  "required_quantity": 10,
  "agv_notes": "Weitere besondere Anforderungen"
}
Fehlende Werte als null setzen.
"""
