"""
AP-D1 — Data-Driven Matching Engine.

Matching operators are defined in config/field_levels.json, which is generated
from the AP0 xlsx (single source of truth). This file contains NO domain
knowledge — it is a pure rule engine interpreter.

To add a new field or change a K.O. condition:
    1. Edit the AP0 xlsx (Matching Operator column)
    2. Run: python3 scripts/generate_field_levels.py
    3. Restart the app — no Python changes needed.

Operator semantics:
    KO_IF_LT         K.O. if supplier < tender  (e.g. payload, lifting height)
    KO_IF_GT         K.O. if supplier > tender  (e.g. aisle width, turning radius)
    KO_IF_NEQ        K.O. if supplier ≠ tender  (e.g. agv_type, route_type)
    KO_BOOL_REQUIRED K.O. if tender=required and supplier≠True
    KO_BOOL_EXCLUSIVE Bidirectional: required→must=True; not_required→must≠True (e.g. vna_capable)
    KO_SUBSET        K.O. if no overlap between tender list and supplier list

Null rule (LL-06): None on either side never triggers a hard K.O. for numeric/categorical
operators. Exception: KO_BOOL_EXCLUSIVE treats None the same as False when tender=required
(VNA logic, LL-10).

NULL penalty: when a tender specifies a numeric KO requirement but the supplier has no
data for that field, a scoring penalty is applied (-15 pts per field) to rank confirmed
suppliers above unverified ones, without excluding them entirely.
"""
import json
from pathlib import Path
from typing import Optional

from src.models import Extension, Product, SupplierRecord

CONFIG_DIR = Path(__file__).parent.parent / "config"
NULL_KO_PENALTY = 15


# ── Config loading ────────────────────────────────────────────────────────────

def _load_field_levels() -> dict:
    p = CONFIG_DIR / "field_levels.json"
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


def _load_weights() -> dict:
    p = CONFIG_DIR / "scoring_weights.json"
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


def _load_vehicle_types() -> dict:
    p = CONFIG_DIR / "vehicle_types.json"
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


_field_levels = _load_field_levels()
_SCORING_BUCKET_MAP: dict = _load_vehicle_types().get("scoring_bucket_map", {})


def validate_tender_values(raw: dict) -> tuple[dict, list[str]]:
    """Validate LLM-extracted tender values against AP0 allowed_values.

    For Dropdown and Multi-Select fields that have an allowed_values list in
    field_levels.json (generated from AP0), any extracted value not matching
    an allowed entry is set to None.  This catches LLM hallucinations like
    'Floor delivery' where the AP0 requires 'Pallet EUR | Pallet ISO | …'.

    Matching is case-insensitive and uses substring containment so that
    'pallet eur' matches 'Pallet EUR'.

    Returns (cleaned_dict, warnings).
    """
    cleaned = dict(raw)
    warnings = []

    # Fields that are normalized by app.py after extraction — skip AP0 filter for them
    _SKIP_FILTER = {"required_vehicle_type", "required_vna", "required_outdoor"}

    for field, meta in _field_levels.items():
        allowed = meta.get("allowed_values")
        tender_key = meta.get("tender_key", field)
        if not allowed or tender_key in _SKIP_FILTER:
            continue
        val = cleaned.get(tender_key)
        if val is None:
            continue

        # Normalise: split multi-values and check each against allowed list
        vals = [v.strip() for v in str(val).replace("|", ",").split(",") if v.strip()]
        allowed_lower = [a.lower() for a in allowed]

        valid = []
        for v in vals:
            vl = v.lower()
            matched = any(vl in al or al in vl for al in allowed_lower)
            if matched:
                valid.append(v)
            else:
                warnings.append(
                    f"{tender_key}: '{v}' not in AP0 allowed values {allowed} → ignored"
                )

        cleaned[tender_key] = ", ".join(valid) if valid else None

    return cleaned, warnings


# ── Operator functions ────────────────────────────────────────────────────────

def _op_lt(tender, supplier) -> tuple[bool, str]:
    """K.O. if supplier value < tender value (e.g. payload capacity too low)."""
    if tender is None or supplier is None:
        return False, ""
    try:
        if float(supplier) < float(tender):
            return True, f"{supplier} < required {tender}"
    except (TypeError, ValueError):
        return False, ""  # non-numeric values: skip
    return False, ""


def _op_gt(tender, supplier) -> tuple[bool, str]:
    """K.O. if supplier value > tender value (e.g. needs wider aisle than available)."""
    if tender is None or supplier is None:
        return False, ""
    try:
        if float(supplier) > float(tender):
            return True, f"needs {supplier}, only {tender} available"
    except (TypeError, ValueError):
        return False, ""
    return False, ""


def _op_neq(tender, supplier) -> tuple[bool, str]:
    """K.O. if supplier value ≠ tender value (exact match required)."""
    if tender is None or supplier is None:
        return False, ""
    if isinstance(tender, list) or isinstance(supplier, list):
        return False, ""  # lists → use KO_SUBSET instead
    if str(tender).lower() != str(supplier).lower():
        return True, f"{supplier} ≠ required {tender}"
    return False, ""


def _op_bool_required(tender, supplier) -> tuple[bool, str]:
    """K.O. if tender=required and supplier is explicitly False.
    NULL is not excluded (LL-06: absence of data ≠ absence of capability).
    For bidirectional exclusion (e.g. vna_capable) use KO_BOOL_EXCLUSIVE instead.
    """
    if str(tender).lower() == "required" and supplier is False:
        return True, "required but supplier does not support it"
    return False, ""


def _op_bool_exclusive(tender, supplier) -> tuple[bool, str]:
    """Bidirectional boolean K.O. (e.g. vna_capable).
    - tender=required  → supplier MUST be True  (else K.O.)
    - tender=not_required → supplier must NOT be True (else K.O.)
    - tender=None / preferred → no K.O.
    """
    t = str(tender).lower() if tender is not None else None
    if t == "required" and supplier is not True:
        return True, f"required but not confirmed (value: {supplier})"
    if t == "not_required" and supplier is True:
        return True, "not required — VNA equipment unsuitable for standard-aisle tender"
    return False, ""


def _op_subset(tender, supplier) -> tuple[bool, str]:
    """K.O. if no overlap between tender list and supplier list.
    Uses substring matching for flexibility (e.g. 'SLAM' matches 'Natural Feature (SLAM)').
    """
    if not tender or not supplier:
        return False, ""  # empty = no constraint
    t_list = [str(x).strip().lower() for x in (tender if isinstance(tender, list) else [tender]) if x]
    s_list = [str(x).strip().lower() for x in (supplier if isinstance(supplier, list) else [supplier]) if x]
    if not t_list or not s_list:
        return False, ""
    matched = any(
        any(t in s or s in t for s in s_list)
        for t in t_list
    )
    if not matched:
        return True, f"{supplier} does not include any of {tender}"
    return False, ""


OPERATORS = {
    "KO_IF_LT":          _op_lt,
    "KO_IF_GT":          _op_gt,
    "KO_IF_NEQ":         _op_neq,
    "KO_BOOL_REQUIRED":  _op_bool_required,
    "KO_BOOL_EXCLUSIVE": _op_bool_exclusive,
    "KO_SUBSET":         _op_subset,
}


# ── Type helpers ─────────────────────────────────────────────────────────────

def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def _i(v) -> Optional[int]:
    try:
        return int(float(v)) if v is not None else None
    except (ValueError, TypeError):
        return None


def _ms(v) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    # Split on | or , — LLM may use either as list separator
    import re as _re
    return [x.strip() for x in _re.split(r"[|,]", str(v)) if x.strip()]


def _bool_to_req(v) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, bool):
        return "required" if v else "not_required"
    s = str(v).lower()
    if s in ("true", "1", "yes", "required"):
        return "required"
    if s in ("false", "0", "no", "not_required"):
        return "not_required"
    return None


def _is_preferred(val) -> bool:
    return str(val).lower() in ("preferred", "nice_to_have")


# ── Tender requirements model ─────────────────────────────────────────────────

_COERCE = {
    "Float":        _f,
    "Integer":      _i,
    "Multi-Select": _ms,
    "Boolean":      lambda v: v,
    "Dropdown":     lambda v: v,
    "Text":         lambda v: v,
}


class TenderRequirements:
    """Requirements parsed from the LLM extraction step.

    Data-driven: field → tender_key and data_type come from field_levels.json
    (generated from AP0 xlsx). No domain knowledge is hardcoded here.

    The rule engine calls req.get("navigation_type") and this class resolves
    the AP0 tender_key ("required_navigation") against the raw dict, then
    coerces to the correct type per AP0 data_type column.
    """

    def __init__(self, raw: dict):
        self.raw = raw

    def get(self, field: str):
        """Resolve AP0 field name → tender_key → raw value with type coercion."""
        meta = _field_levels.get(field, {})
        tender_key = meta.get("tender_key", field)
        raw_val = self.raw.get(tender_key)
        if raw_val is None:
            raw_val = self.raw.get(field)
        data_type = meta.get("data_type", "Text")
        coerce = _COERCE.get(data_type, lambda v: v)
        return coerce(raw_val)


# ── Match result ──────────────────────────────────────────────────────────────

class MatchResult:
    def __init__(self, record: SupplierRecord):
        self.record       = record
        self.score        = 0
        self.max_score    = 0
        self.ko_failures: list[str] = []
        self.cond_failures: list[str] = []
        self.score_details: list[dict] = []
        self.disqualified = False
        self.disqualified_by: list[str] = []

    @property
    def product_name(self) -> str:
        return self.record.product.product_name

    @property
    def company_name(self) -> str:
        return self.record.product.company_name or ""

    def to_dict(self) -> dict:
        ext  = self.record.extension
        prod = self.record.product
        return {
            "product":         self.product_name,
            "company":         self.company_name,
            "score":           self.score,
            "max_score":       self.max_score,
            "rank":            getattr(self, "rank", 0),
            "disqualified":    self.disqualified,
            "disqualified_by": self.disqualified_by,
            "score_details":   self.score_details,
            "agv_type":        ext.agv_type,
            "reasons":         [f"{d['field']}: +{d['points']} pts" for d in self.score_details if d['points'] > 0],
            "knockouts":       self.disqualified_by,
            "website":         prod.website if hasattr(prod, "website") and prod.website else "",
            "origin":          prod.country or "",
            "description":     prod.product_description or "",
            "navigation":      " | ".join(ext.navigation_type) if ext.navigation_type else "",
            "max_payload_kg":  ext.max_payload_kg,
            "lifting_height_mm": ext.lifting_height_mm,
            "min_aisle_width_mm": ext.min_aisle_width_mm,
            "max_speed_ms":    ext.max_speed_ms,
            "vda5050":         ext.vda5050_compatible,
            "battery_runtime_h": ext.battery_runtime_h,
            "autonomous_charging": ext.autonomous_charging,
            "reference_count": prod.reference_count,
            "lead_time_weeks": prod.lead_time_weeks,
            "service_coverage": prod.service_coverage,
        }


# ── Supplier field accessor ───────────────────────────────────────────────────

def _supplier_val(ext: Extension, prod: Product, field: str):
    """Get field value from supplier record — checks Extension first, then Product."""
    val = getattr(ext, field, None)
    if val is None:
        val = getattr(prod, field, None)
    return val


# ── Main matcher ──────────────────────────────────────────────────────────────

class Matcher:
    def __init__(self):
        self.weights = _load_weights()

    def _w(self, key: str, agv_type: str) -> int:
        """Weight lookup — reads scoring_bucket_map from vehicle_types.json (C-2)."""
        bucket   = _SCORING_BUCKET_MAP.get(agv_type, "")
        default  = self.weights.get("default",  {}).get(key, {})
        specific = self.weights.get(bucket,     {}).get(key, {})
        entry = specific if specific else default
        if isinstance(entry, dict):
            return entry.get("weight", 0)
        return int(entry) if entry else 0

    def match(self, suppliers: list[SupplierRecord], req: TenderRequirements, top_n: int = 10) -> tuple[list[MatchResult], list[MatchResult]]:
        results = [self._score_one(rec, req) for rec in suppliers]
        qualified    = sorted([r for r in results if not r.disqualified], key=lambda x: -x.score)
        disqualified = sorted([r for r in results if r.disqualified],     key=lambda x: -x.score)
        for i, r in enumerate(qualified + disqualified):
            r.rank = i + 1
        return (qualified + disqualified)[:top_n], qualified + disqualified

    def _score_one(self, rec: SupplierRecord, req: TenderRequirements) -> MatchResult:
        r   = MatchResult(rec)
        ext = rec.extension
        prod= rec.product

        def ko_fail(msg: str):
            r.disqualified = True
            r.disqualified_by.append(msg)

        def add_score(pts: int, label: str, value=None):
            r.max_score += abs(pts)
            r.score_details.append({"field": label, "points": pts, "value": value})
            r.score += pts

        def add_max(pts: int):
            r.max_score += pts

        # ── K.O. and Cond. K.O. rules (data-driven from field_levels.json) ───
        for field, meta in _field_levels.items():
            level    = meta.get("level")
            operator = meta.get("operator")

            if level not in ("KO", "COND_KO") or not operator:
                continue

            op_fn = OPERATORS.get(operator)
            if not op_fn:
                continue

            tender_val   = req.get(field)
            supplier_val = _supplier_val(ext, prod, field)

            failed, msg = op_fn(tender_val, supplier_val)
            if failed:
                ko_fail(f"{field}: {msg}")
                if level == "KO":
                    return r  # hard K.O. — stop evaluating immediately

        if r.disqualified:
            return r

        # ── NULL KO penalty ───────────────────────────────────────────────────
        # Numeric KO fields where tender has a requirement but supplier has no data:
        # not excluded (LL-06), but penalised to rank confirmed suppliers higher.
        NUMERIC_OPS = {"KO_IF_LT", "KO_IF_GT"}
        for field, meta in _field_levels.items():
            if meta.get("level") != "KO" or meta.get("operator") not in NUMERIC_OPS:
                continue
            if req.get(field) is not None and _supplier_val(ext, prod, field) is None:
                add_score(-NULL_KO_PENALTY, f"{field}_null_penalty", None)

        # ── Scoring (data-driven from scoring_weights.json + vehicle_types.json) ─
        # No hardcoded AGV type names or numeric thresholds — all from AP0 via config.
        agv_t  = ext.agv_type
        bucket = _SCORING_BUCKET_MAP.get(agv_t, "")

        for section in ("default", bucket):
            for field, cfg in self.weights.get(section, {}).items():
                if not isinstance(cfg, dict):
                    continue
                pts  = cfg.get("weight", 0)
                rule = cfg.get("rule", "bool")
                val  = _supplier_val(ext, prod, field)

                if rule == "bool_cond":
                    # Score full pts if tender requires this field, else deduct 2.
                    add_max(pts)
                    if val is True:
                        cond_met = str(req.get(field) or "").lower() == "required"
                        add_score(pts if cond_met else max(0, pts - 2), field, val)
                elif rule == "proportional":
                    add_max(pts)
                    if val is not None and val > 0:
                        max_count = cfg.get("t1", 20)
                        add_score(
                            min(pts, int(pts * min(val / max_count, 1.0))), field, val
                        )
                elif rule == "bool":
                    add_max(pts)
                    if val is True:
                        add_score(pts, field, val)
                elif rule == "nonempty":
                    add_max(pts)
                    if val:
                        add_score(pts, field, val)
                elif rule == "threshold_lower":
                    add_max(pts)
                    t1 = cfg.get("t1")
                    if val is not None and t1 is not None and val <= t1:
                        add_score(pts, field, val)
                elif rule == "threshold_upper":
                    add_max(pts)
                    t1 = cfg.get("t1")
                    if val is not None and t1 is not None:
                        add_score(pts if val >= t1 else pts // 2, field, val)
                elif rule == "tiered_lower":
                    add_max(pts)
                    t1, t2 = cfg.get("t1"), cfg.get("t2")
                    if val is not None and t1 is not None and t2 is not None:
                        add_score(
                            pts if val <= t1 else (pts // 2 if val <= t2 else 0),
                            field, val,
                        )
                elif rule == "tiered_upper":
                    add_max(pts)
                    t1, t2 = cfg.get("t1"), cfg.get("t2")
                    if val is not None and t1 is not None and t2 is not None:
                        add_score(
                            pts if val >= t1 else (pts // 2 if val >= t2 else 0),
                            field, val,
                        )

        # Preferred Cond. K.O. bonuses
        if _is_preferred(req.get("vda5050_compatible")) and ext.vda5050_compatible is True:
            add_score(3, "vda5050_preferred_bonus", True)
        if _is_preferred(req.get("outdoor_capable")) and ext.outdoor_capable is True:
            add_score(2, "outdoor_preferred_bonus", True)
        if _is_preferred(req.get("auto_hitch")) and ext.auto_hitch is True:
            add_score(2, "auto_hitch_preferred_bonus", True)

        return r


_matcher = Matcher()


def match_suppliers_new(
    req_dict: dict,
    suppliers: list[SupplierRecord],
    top_n: int = 10,
) -> tuple[list[dict], list[dict]]:
    """Public API used by app.py."""
    req = TenderRequirements(req_dict)
    top, all_results = _matcher.match(suppliers, req, top_n=top_n)
    return [r.to_dict() for r in top], [r.to_dict() for r in all_results]
