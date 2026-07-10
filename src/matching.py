"""
AP-D1 — Data-Driven Matching Engine.

Matching operators are defined in config/fields.json, which is generated
from the AP0 xlsx (single source of truth). This file contains NO domain
knowledge — it is a pure rule engine interpreter.

To add a new field or change a K.O. condition:
    1. Edit the AP0 xlsx (Matching Operator column)
    2. Run: python3 scripts/generate_all.py
    3. Restart the app — no Python changes needed.

Operator semantics:
    KO_IF_LT         K.O. if supplier < tender  (e.g. payload, lifting height)
    KO_IF_GT         K.O. if supplier > tender  (e.g. aisle width, turning radius)
    KO_IF_NEQ        K.O. if supplier ≠ tender  (e.g. agv_type, route_type)
    KO_BOOL_REQUIRED K.O. if tender=required and supplier≠True
    KO_BOOL_EXCLUSIVE Bidirectional: required→must=True; not_required→must≠True (e.g. vna_capable)
    KO_SUBSET        K.O. if no overlap between tender list and supplier list

Null rule (LL-06): None on either side never triggers a hard K.O. for numeric/categorical
operators. For KO_BOOL_EXCLUSIVE, None supplier_val → no constraint (LL-06). Closed-world
assumption is declared per-field via value_if_null in the AP0 xlsx, not in this module.

NULL penalty: when a tender specifies a numeric KO requirement but the supplier has no
data for that field, a scoring penalty is applied (-15 pts per field) to rank confirmed
suppliers above unverified ones, without excluding them entirely.
"""
import json
import logging
from pathlib import Path
from typing import Optional

from src.models import FieldValue, Product, SupplierRecord
from src.field_spec import FieldSpec, load_fields, fields_by_field_name

log = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "config"
NULL_KO_PENALTY = 15

_SIGNED_UNITS: frozenset = frozenset(
    json.loads((Path(__file__).parent.parent / "config" / "unit_semantics.json").read_text())
    .get("signed_units", [])
)
assert _SIGNED_UNITS is not None, "unit_semantics.json failed to load — check config/"


# ── Config loading ────────────────────────────────────────────────────────────

def _load_vehicle_types() -> dict:
    p = CONFIG_DIR / "vehicle_types.json"
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


_fields = load_fields()  # dict[str, FieldSpec], keyed by UUID
_scope_registry = json.loads((Path(__file__).parent.parent / "config" / "scope_registry.json").read_text())
_LEGACY_MAP: dict[str, str] = _scope_registry.get("legacy_map", {})
assert _LEGACY_MAP, "scope_registry.json missing legacy_map — run generate_all.py"
_SHARED_SCOPE: str = next(
    (data["scope_id"] for data in _scope_registry["scopes"].values() if data.get("parent") == "*"),
    ""
)
assert _SHARED_SCOPE, "scope_registry.json: no scope with parent='*' found — run generate_all.py"

# Guardian S2: Startup-Assertion — every vt_map canonical value must resolve via legacy_map
_vt_map_values = set(_load_vehicle_types().get("vt_map", {}).values())
assert _vt_map_values <= set(_LEGACY_MAP), (
    f"vt_map values without scope in legacy_map: {_vt_map_values - set(_LEGACY_MAP)}"
)


def validate_tender_values(raw: dict) -> tuple[dict, list[str]]:
    """Validate LLM-extracted tender values against AP0 allowed_values.

    For Dropdown and Multi-Select fields that have an allowed_values list in
    fields.json (generated from AP0), any extracted value not matching
    an allowed entry is set to None.  This catches LLM hallucinations like
    'Floor delivery' where the AP0 requires 'Pallet EUR | Pallet ISO | …'.

    Matching is case-insensitive and uses substring containment so that
    'pallet eur' matches 'Pallet EUR'.

    Returns (cleaned_dict, warnings).
    """
    cleaned = dict(raw)
    warnings = []

    # Fields that are normalized by app.py after extraction — skip AP0 filter for them
    _SKIP_FILTER = {"required_agv_type", "required_vna_capable", "required_outdoor_capable"}

    for field_spec in _fields.values():
        allowed = field_spec.allowed_values
        tender_key = field_spec.tender_key
        if not allowed or not tender_key or tender_key in _SKIP_FILTER:
            continue
        val = cleaned.get(tender_key)
        if val is None:
            continue

        # Normalise: split multi-values on pipe, comma, or slash-with-spaces.
        # Slash-split handles LLM compound strings like "REST / OPC UA" → ["REST", "OPC UA"]
        normalised = str(val).replace("|", ",").replace(" / ", ",")
        vals = [v.strip() for v in normalised.split(",") if v.strip()]
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
    SQLite returns integers (0/1), so compare with == not `is`.
    LLM extraction may return Python True instead of 'required' — both are accepted.
    """
    t = str(tender).lower() if tender is not None else ""
    is_required = t == "required" or tender is True or tender == 1
    if is_required and supplier is not None and not bool(supplier):
        return True, "required but supplier does not support it"
    return False, ""


def _op_bool_exclusive(tender, supplier) -> tuple[bool, str]:
    """Bidirectional boolean K.O. (e.g. vna_capable).
    - tender=required  → supplier MUST be truthy (else K.O.)
    - tender=not_required → supplier must NOT be truthy (else K.O.)
    - tender=None / preferred → no K.O.
    SQLite stores booleans as integers (0/1); use bool() to normalise before comparing.
    None supplier_val → no constraint (LL-06).
    Closed-world assumption is declared per-field via value_if_null in AP0, not here.
    """
    t = str(tender).lower() if tender is not None else None
    # None supplier_val → no constraint (LL-06).
    # Closed-world assumption is declared per-field via value_if_null in AP0, not here.
    if supplier is None:
        return False, ""
    s = bool(supplier)
    if t == "required" and not s:
        return True, f"required but not confirmed (value: {supplier})"
    if t == "not_required" and s:
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
    """Wraps a TenderRun for use by the matching engine.
    Use from_dict() for ephemeral dict-based callers (/rematch, /match endpoints)."""

    def __init__(self, run: "TenderRun"):
        self._run = run

    @classmethod
    def from_dict(cls, raw: dict) -> "TenderRequirements":
        """Build from a UUID-keyed criteria dict (for /match and /rematch endpoints)."""
        from src.models import TenderRun, ExtractionValue
        values = {
            k: ExtractionValue(spec=None, value=v, source=None)
            for k, v in raw.items()
            if not str(k).endswith("_source") and not str(k).startswith("_")
        }
        run = TenderRun(
            run_id="ephemeral", source_file="", captured_at="",
            vehicle_type=None, in_scope=True,
            values=values, basic_info={},
        )
        return cls(run)

    def get(self, field_name: str):
        """Return the tender value for a field by AP0 field_name.
        Resolves field_name → uuid(s) via fields_by_field_name(), returns first non-None.
        Falls back to direct key lookup for non-UUID-keyed from_dict callers."""
        by_name = fields_by_field_name()
        specs = by_name.get(field_name, [])
        for spec in specs:
            ev = self._run.values.get(spec.uuid)
            if ev is not None and ev.value is not None:
                return ev.value
        # Fallback: direct key lookup (from_dict may store values under field_name or tender_key)
        ev = self._run.values.get(field_name)
        if ev is not None and ev.value is not None:
            data_type = specs[0].data_type if specs else "Text"
            return _COERCE.get(data_type, lambda v: v)(ev.value)
        return None


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
        self.null_gap_fields: list[str] = []
        self.null_pass_fields: list[str] = []  # KO fields skipped because tender had no requirement

    @property
    def product_name(self) -> str:
        return self.record.product.product_name

    @property
    def company_name(self) -> str:
        return self.record.product.company_name or ""

    def to_dict(self) -> dict:
        values = self.record.values
        prod   = self.record.product
        return {
            "product":         self.product_name,
            "company":         self.company_name,
            "score":           self.score,
            "max_score":       self.max_score,
            "rank":            getattr(self, "rank", 0),
            "disqualified":    self.disqualified,
            "disqualified_by": self.disqualified_by,
            "null_gap_fields":  self.null_gap_fields,
            "null_pass_fields": self.null_pass_fields,
            "score_details":   self.score_details,
            "agv_type":        prod.agv_type,
            "reasons":         [f"{d['field']}: +{d['points']} pts" for d in self.score_details if d['points'] > 0],
            "knockouts":       self.disqualified_by,
            "website":         prod.website if hasattr(prod, "website") and prod.website else "",
            "origin":          prod.country or "",
            "description":     prod.product_description or "",
            **{
                field_spec.field_name: (
                    " | ".join(v) if isinstance(v := _supplier_val(values, prod, field_spec), list) else v
                )
                for field_spec in _fields.values() if field_spec.level != "CONTEXT"
            },
        }


# ── Active requirement guard ──────────────────────────────────────────────────

def _is_active_requirement(tender_val, operator: str, unit: Optional[str] = None) -> bool:
    """Returns True only if tender_val is an active matching constraint.

    For boolean operators (KO_BOOL_REQUIRED, KO_BOOL_EXCLUSIVE): only True/1/'required'
    are active requirements. False/'not_required'/0 mean no constraint — null supplier
    is safe under LL-06 and must not generate a null_gap.
    For all other operators: any non-None tender value is an active constraint.
    """
    if tender_val is None:
        return False
    if operator in ("KO_BOOL_REQUIRED", "KO_BOOL_EXCLUSIVE"):
        t = str(tender_val).lower()
        return t == "required" or tender_val is True or tender_val == 1
    # KO_IF_LT only: 0 means no minimum requirement (e.g. flat floor = no gradient constraint).
    # KO_IF_GT is excluded — a 0 tender value there is a real (maximally restrictive) constraint.
    if operator == "KO_IF_LT" and unit not in _SIGNED_UNITS:
        try:
            if float(tender_val) == 0:
                return False
        except (TypeError, ValueError):
            pass
    return True


# ── Supplier field accessor ───────────────────────────────────────────────────

def _supplier_val(values: dict[str, FieldValue], prod: Product, spec: FieldSpec):
    fv = values.get(spec.uuid)
    if fv is not None:
        result = fv.value
    else:
        # Fallback: product-level fields not yet in values dict
        result = getattr(prod, spec.field_name, None)
    if result is None and spec.value_if_null is not None:
        return spec.value_if_null
    return result


# ── Main matcher ──────────────────────────────────────────────────────────────

class Matcher:
    def __init__(self):
        pass

    def match(self, suppliers: list[SupplierRecord], req: TenderRequirements, top_n: int = 10) -> tuple[list[MatchResult], list[MatchResult]]:
        results = [self._score_one(rec, req) for rec in suppliers]
        qualified    = sorted([r for r in results if not r.disqualified], key=lambda x: -x.score)
        disqualified = sorted([r for r in results if r.disqualified],     key=lambda x: -x.score)
        for i, r in enumerate(qualified + disqualified):
            r.rank = i + 1
        return (qualified + disqualified)[:top_n], qualified + disqualified

    def _score_one(self, rec: SupplierRecord, req: TenderRequirements) -> MatchResult:
        r      = MatchResult(rec)
        values = rec.values
        prod   = rec.product

        def ko_fail(msg: str):
            r.disqualified = True
            r.disqualified_by.append(msg)

        def add_score(pts: int, label: str, value=None):
            r.max_score += abs(pts)
            r.score_details.append({"field": label, "points": pts, "value": value})
            r.score += pts

        def add_max(pts: int):
            r.max_score += pts

        # ── OI-47: only SHARED + VT-specific fields of the supplier ──────────
        vt_scope = _LEGACY_MAP.get(prod.agv_type)
        if not vt_scope:
            log.error("agv_type %r not in legacy_map — supplier %s skipped", prod.agv_type, prod.product_id)
            r.disqualified = True
            r.disqualified_by.append(f"agv_type '{prod.agv_type}' not in scope_registry legacy_map")
            return r
        resolution = _scope_registry["resolution_order"].get(vt_scope, [])
        relevant = [f for f in _fields.values() if f.scope in resolution]

        # ── K.O. and Cond. K.O. rules (data-driven from fields.json) ─────────
        for field_spec in relevant:
            level    = field_spec.level
            operator = field_spec.operator

            if level not in ("KO", "COND_KO") or not operator:
                continue

            op_fn = OPERATORS.get(operator)
            if not op_fn:
                continue

            tender_val   = req.get(field_spec.field_name)
            supplier_val = _supplier_val(values, prod, field_spec)

            failed, msg = op_fn(tender_val, supplier_val)
            if failed:
                ko_fail(f"{field_spec.field_name}: {msg}")
                if level == "KO":
                    return r  # hard K.O. — stop evaluating immediately

        if r.disqualified:
            return r

        # ── NULL KO penalty ───────────────────────────────────────────────────
        # Numeric KO fields where tender has a requirement but supplier has no data:
        # not excluded (LL-06), but penalised to rank confirmed suppliers higher.
        NUMERIC_OPS = {"KO_IF_LT", "KO_IF_GT"}
        for field_spec in relevant:
            if field_spec.level != "KO" or field_spec.operator not in NUMERIC_OPS:
                continue
            if _is_active_requirement(req.get(field_spec.field_name), field_spec.operator, field_spec.unit) and _supplier_val(values, prod, field_spec) is None:
                add_score(-NULL_KO_PENALTY, f"{field_spec.field_name}_null_penalty", None)

        # ── NULL gap tracking (for UI — no score impact) ─────────────────────────────
        # Collect any KO or COND_KO field where tender has an active requirement but
        # supplier has no data. Superset of null penalty: includes COND_KO fields too.
        # Uses _is_active_requirement() so that False/'not_required' tender values do
        # not produce spurious null_gap chips (LL-06).
        for field_spec in relevant:
            if field_spec.level not in ("KO", "COND_KO"):
                continue
            if (_is_active_requirement(req.get(field_spec.field_name), field_spec.operator, field_spec.unit)
                    and _supplier_val(values, prod, field_spec) is None):
                if field_spec.field_name not in r.null_gap_fields:
                    r.null_gap_fields.append(field_spec.field_name)

        # ── NULL pass tracking (OI-39 — for UI, no score impact) ──────────────
        # KO fields where tender_val is None (no requirement extracted) → supplier
        # passes trivially. Distinct from explicit 'not_required'/False values.
        # Shown in UI as a "? N fields unchecked" hint on confirmed cards.
        for field_spec in relevant:
            if field_spec.level not in ("KO", "COND_KO") or not field_spec.operator:
                continue
            if req.get(field_spec.field_name) is None:
                if field_spec.field_name not in r.null_pass_fields:
                    r.null_pass_fields.append(field_spec.field_name)

        # ── Scoring (data-driven from fields.json) ────────────────────────────
        # No hardcoded AGV type names or numeric thresholds — all from AP0 via config.
        for field_spec in relevant:
            if not field_spec.scoring_weight:
                continue
            pts  = field_spec.scoring_weight
            rule = field_spec.score_function or "bool"
            t1   = field_spec.threshold_a
            t2   = field_spec.threshold_b
            val  = _supplier_val(values, prod, field_spec)

            if rule == "bool_cond":
                # Score full pts if tender requires this field, else deduct 2.
                add_max(pts)
                if val is True:
                    cond_met = str(req.get(field_spec.field_name) or "").lower() == "required"
                    add_score(pts if cond_met else max(0, pts - 2), field_spec.field_name, val)
            elif rule == "proportional":
                add_max(pts)
                if val is not None and val > 0:
                    max_count = t1 if t1 is not None else 20
                    add_score(
                        min(pts, int(pts * min(val / max_count, 1.0))), field_spec.field_name, val
                    )
            elif rule == "bool":
                add_max(pts)
                if val is True:
                    add_score(pts, field_spec.field_name, val)
            elif rule == "nonempty":
                add_max(pts)
                if val:
                    add_score(pts, field_spec.field_name, val)
            elif rule == "threshold_lower":
                add_max(pts)
                if val is not None and t1 is not None and val <= t1:
                    add_score(pts, field_spec.field_name, val)
            elif rule == "threshold_upper":
                add_max(pts)
                if val is not None and t1 is not None:
                    add_score(pts if val >= t1 else pts // 2, field_spec.field_name, val)
            elif rule == "tiered_lower":
                add_max(pts)
                if val is not None and t1 is not None and t2 is not None:
                    add_score(
                        pts if val <= t1 else (pts // 2 if val <= t2 else 0),
                        field_spec.field_name, val,
                    )
            elif rule == "tiered_upper":
                add_max(pts)
                if val is not None and t1 is not None and t2 is not None:
                    add_score(
                        pts if val >= t1 else (pts // 2 if val >= t2 else 0),
                        field_spec.field_name, val,
                    )

        return r


_matcher = Matcher()


def match_suppliers_new(
    req: TenderRequirements,
    suppliers: list[SupplierRecord],
    top_n: int = 10,
) -> tuple[list[MatchResult], list[MatchResult]]:
    """Public API used by app.py."""
    matcher = Matcher()
    return matcher.match(suppliers, req, top_n=top_n)
