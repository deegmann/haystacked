#!/usr/bin/env python3
"""Variant-split migration -- fixes 17 blended DB rows / 40 real AGV/AMR variants.

Full plan: docs/variant_split_full_plan_20260824.md

Background: scripts/import_datasheet_project_20260822.py's live run (2026-08-24)
correctly split 3 explicitly-named Linde variant groups, but missed 17 other
DB rows that are each a silent blend of 2-4 genuinely distinct real products
(VisionNav, SAFELOG, AGILOX, Balyo, Linde, Toyota). Where a colliding field
was blank in the DB, the earlier script's ENRICH FILLS path wrote each
variant's candidate value sequentially with no collision check -- last write
silently won. This script fixes all 17 rows.

Per-group decision (see the plan doc's table for the full rationale):
  ANCHOR:      exactly one real variant's product_name is byte-identical to
               the existing DB row name -- that row is KEPT and PATCHED with
               the anchor variant's resolved field values; new rows are
               created only for the OTHER variant(s).
  FULL-RETIRE: no variant name matches the DB row name -- the existing row is
               DEACTIVATED (active=False) and N new rows are created, one per
               real variant.

Data source per variant (priority order, see plan doc "Data source per
variant" section):
  1. A RESOLVED conflicts[] triage_correct_value (from
     docs/datasheet_db_status_final.json) for this variant's own STATUS
     entry -- reused via import_datasheet_project_20260822.classify_conflict().
  2. The variant's own entry (matched by product_name) in its
     research_findings_opus_20260808_*.json file's `fields` dict.
  3. Fallback: the matching entry (by product_name, allowing for a company's
     own "AGV "-prefix naming difference between source files) in the
     research_findings_datasheet_20260806_*.json file.
  4. Never invent -- if absent from both, leave null.

  Guard: a field flagged VARIANT-SPLIT-NEEDED whose ONLY resolved value came
  from the datasheet-fallback tier (opus had nothing) is suppressed and
  flagged rather than trusted -- the same failure class that produced the
  original blended-row bug (a same-named source file can itself still
  conflate multiple sub-configs under one product name; confirmed on Linde
  C-MATIC max_payload during dry-run construction of this script).

Airtable-write conventions reused verbatim from
scripts/import_datasheet_project_20260822.py (imported as a library, not
reimplemented): schema pre-validation via the Meta API, retry-once-on-
UNKNOWN_FIELD_NAME, resumable/idempotent creation (live Airtable lookup by
product_name/company before creating), typecast=True, rate-limited requests.
This script populates that module's PLAN["new_inserts"] / PLAN["enrich_fills"]
/ PLAN["deactivate"] buckets directly and calls its execute_new_inserts() /
execute_fills() functions for the actual writes -- no Airtable I/O is
reimplemented here.

Usage:
    python3 scripts/variant_split_full_20260824.py --dry-run   # (default) preview only
    python3 scripts/variant_split_full_20260824.py --run       # actually write to Airtable
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

sys.path.insert(0, str(ROOT / "scripts"))
import import_datasheet_project_20260822 as base  # noqa: E402

AUDIT_PATH = DOCS / "variant_split_full_20260824_audit.jsonl"
base.AUDIT_PATH = AUDIT_PATH  # redirect the reused audit() helper to our own log

FIELD_BY_NAME = base.FIELD_BY_NAME
SCOPE_REGISTRY = json.loads((ROOT / "config" / "scope_registry.json").read_text())

DRY = True  # flipped in main()

# ───────────────────────────────────────────────────── 17-row decision table
GROUPS = [
    {"company": "AGILOX Services GmbH", "db_row": "AGILOX ONE", "decision": "ANCHOR",
     "anchor": "AGILOX ONE",
     "variants": ["AGILOX ONE", "AGILOX ONE (Doppelscherenhub)"]},
    {"company": "AGILOX Services GmbH", "db_row": "AGILOX ODM 600/800", "decision": "FULL-RETIRE",
     "variants": ["AGILOX ODM 600", "AGILOX ODM 800"]},
    {"company": "Balyo", "db_row": "LOWY / LOWY HD", "decision": "FULL-RETIRE",
     "variants": ["LOWY", "LOWY HD"]},
    {"company": "Linde Material Handling", "db_row": "Linde C-MATIC", "decision": "ANCHOR",
     "anchor": "Linde C-MATIC",
     "variants": ["Linde C-MATIC", "Linde C-MATIC 10"]},
    {"company": "SAFELOG GmbH", "db_row": "SAFELOG AGV L2", "decision": "FULL-RETIRE",
     "variants": ["SAFELOG L2 lift", "SAFELOG L2 core"]},
    {"company": "SAFELOG GmbH", "db_row": "SAFELOG AGV M4", "decision": "FULL-RETIRE",
     "variants": ["SAFELOG M4 core", "SAFELOG M4 lift", "SAFELOG M4 tow"]},
    {"company": "SAFELOG GmbH", "db_row": "SAFELOG AGV S3", "decision": "FULL-RETIRE",
     "variants": ["SAFELOG S3 tow", "SAFELOG S3 core"]},
    {"company": "SAFELOG GmbH", "db_row": "SAFELOG AGV X1", "decision": "FULL-RETIRE",
     "variants": ["SAFELOG X1 lift 1200", "SAFELOG X1 spin", "SAFELOG X1 core"]},
    {"company": "Toyota Material Handling Europe", "db_row": "Toyota Staxio SAE160 Autopilot",
     "decision": "FULL-RETIRE",
     "variants": ["Toyota Staxio SAE160 Autopilot (Triplex Hi-Lo)",
                  "Toyota Staxio SAE160 Autopilot (Duplex Tele)"]},
    {"company": "VisionNav Robotics", "db_row": "VisionNav VNSL14", "decision": "ANCHOR",
     "anchor": "VisionNav VNSL14",
     "variants": ["VisionNav VNSL14", "VisionNav VNSL14(V)-07", "VisionNav VNSL14(VL)-07"]},
    {"company": "VisionNav Robotics", "db_row": "VisionNav VNP15", "decision": "ANCHOR",
     "anchor": "VisionNav VNP15",
     "variants": ["VisionNav VNP15", "VisionNav VNP15(V)-07", "VisionNav VNP15(VL)-07"]},
    {"company": "VisionNav Robotics", "db_row": "VisionNav VNQ50", "decision": "ANCHOR",
     "anchor": "VisionNav VNQ50",
     "variants": ["VisionNav VNQ50", "VisionNav VNQ50(VL)-01"]},
    {"company": "VisionNav Robotics", "db_row": "VisionNav VNE40", "decision": "ANCHOR",
     "anchor": "VisionNav VNE40",
     "variants": ["VisionNav VNE40", "VisionNav VNE40(VL)-07"]},
    {"company": "VisionNav Robotics", "db_row": "VisionNav VNE20", "decision": "ANCHOR",
     "anchor": "VisionNav VNE20",
     "variants": ["VisionNav VNE20", "VisionNav VNE20(VL)-07"]},
    {"company": "VisionNav Robotics", "db_row": "VisionNav VNST20", "decision": "ANCHOR",
     "anchor": "VisionNav VNST20",
     "variants": ["VisionNav VNST20", "VisionNav VNST20(VL)-66"]},
    {"company": "VisionNav Robotics", "db_row": "VisionNav VNR16", "decision": "FULL-RETIRE",
     "variants": ["VisionNav VNR16(V)-01", "VisionNav VNR16(V)-07 (Manual Handheld)",
                  "VisionNav VNR16(V)-07 (Manual Seated)", "VisionNav VNR16(VL)-01"]},
    {"company": "VisionNav Robotics", "db_row": "VisionNav VNP20", "decision": "FULL-RETIRE",
     "variants": ["VisionNav VNP20(V)-07", "VisionNav VNP20(VL)-07"]},
]

STATUS_BY_KEY = {(p["company"], p["product_name"]): p for p in base.STATUS["products"]}

# ──────────────────────────────────────────────────────────────── my report
FLAGS = []
SKIPPED = []
ALLOWED_VALUE_WARNINGS = []
KO_GAPS = []
ANCHOR_PATCH_META = []   # {company, db_row, n_patch_fields}
NEW_INSERT_META = []     # {company, product_name, group_key, split_type, n_bm, n_prod}


def _flag(msg):
    FLAGS.append(msg)


# ────────────────────────────────────────────────────────── source loaders
_source_cache = {}


def load_source_file(rel_path):
    if not rel_path:
        return None
    if rel_path not in _source_cache:
        try:
            _source_cache[rel_path] = json.loads((ROOT / rel_path).read_text())
        except Exception:
            _source_cache[rel_path] = None
    return _source_cache[rel_path]


def _match_source_entry(source_data, variant_name):
    """Find a product entry in a research_findings file by exact product_name match, with a
    narrow fallback for the documented SAFELOG-style 'AGV ' infix naming difference between the
    per-company research files and the merged/STATUS dataset's canonical names (e.g. 'SAFELOG X1
    lift 1200' vs 'SAFELOG AGV X1 lift 1200'). No fuzzy/substring matching -- an unmatched name
    returns None rather than risk pulling a differently-scoped combined entry (e.g. AGILOX's
    'AGILOX ODM 600/800')."""
    if not source_data:
        return None
    products = source_data.get("products", [])
    for p in products:
        if p.get("product_name") == variant_name:
            return p
    parts = variant_name.split(" ", 1)
    if len(parts) == 2:
        agv_name = f"{parts[0]} AGV {parts[1]}"
        for p in products:
            if p.get("product_name") == agv_name:
                return p
    return None


def _ko_fields_for_product_type(product_type):
    leaf = SCOPE_REGISTRY["legacy_map"].get(product_type)
    if not leaf:
        return []
    chain = set(SCOPE_REGISTRY["resolution_order"].get(leaf, [leaf]))
    return sorted(
        f["field_name"] for f in FIELD_BY_NAME.values()
        if f["level"] == "KO" and (f["scope"] == "*" or f["scope"] in chain)
    )


# ────────────────────────────────────────────────── per-variant resolution
def resolve_variant_fields(status_entry):
    """Returns (fields: {field_name: value}, product_type, sources: {field: (kind, file, citation)})."""
    variant_name = status_entry["product_name"]
    opus_data = load_source_file(status_entry.get("opus_source_file"))
    ds_data = load_source_file(status_entry.get("sonnet_source_file"))
    opus_entry = _match_source_entry(opus_data, variant_name)
    ds_entry = _match_source_entry(ds_data, variant_name)

    fields = {}
    sources = {}
    if ds_entry:
        for k, v in ds_entry.get("fields", {}).items():
            if v is None:
                continue
            fields[k] = v
            sources[k] = ("datasheet", ds_entry.get("source_file"), ds_entry.get("field_sources", {}).get(k))
    datasheet_only_fields = set(fields.keys())
    if opus_entry:
        for k, v in opus_entry.get("fields", {}).items():
            if v is None:
                continue
            fields[k] = v
            sources[k] = ("opus", opus_entry.get("source_file"), opus_entry.get("field_sources", {}).get(k))
            datasheet_only_fields.discard(k)

    product_type = None
    if opus_entry and opus_entry.get("product_type"):
        product_type = opus_entry["product_type"]
    elif ds_entry and ds_entry.get("product_type"):
        product_type = ds_entry["product_type"]
    fields.pop("product_type", None)
    if product_type:
        fields["product_type"] = product_type

    for c in status_entry.get("conflicts", []):
        field = c["field"]
        verdict = c["triage_verdict"]
        if verdict == "RESOLVED":
            action, value = base.classify_conflict(c)
            if action in ("NOOP", "NOOP-FANOUT"):
                fields.pop(field, None)
                continue
            if action == "AMBIGUOUS":
                fields.pop(field, None)
                _flag(f"'{variant_name}': AMBIGUOUS RESOLVED conflict on '{field}' "
                      f"({c['triage_correct_value']!r}) -- left null, needs manual review.")
                continue
            spec = FIELD_BY_NAME.get(field, {})
            if action in ("WRITE-num", "WRITE-num-fallback") and spec.get("data_type") == "Integer":
                value = int(round(value))
            fields[field] = value
            sources[field] = ("triage_resolved", c.get("triage_source"), c["triage_correct_value"])
        elif verdict == "UNRESOLVED":
            fields.pop(field, None)
            _flag(f"'{variant_name}': UNRESOLVED K.O./conflict on '{field}' "
                  f"(DB={c['db_value']!r} vs extracted={c['datasheet_value']!r}) -- left null, "
                  f"needs manual review before or after this migration.")
        elif verdict == "VARIANT-SPLIT-NEEDED":
            if field in datasheet_only_fields:
                fields.pop(field, None)
                _flag(f"'{variant_name}': VARIANT-SPLIT-NEEDED field '{field}' only had a "
                      f"datasheet-fallback value (opus had none) -- too risky to trust a same-"
                      f"named source that may itself still blend sub-configs (same failure class "
                      f"as Linde C-MATIC max_payload). Left null. Triage note: "
                      f"{c['triage_correct_value']!r}")
            elif field not in fields:
                _flag(f"'{variant_name}': VARIANT-SPLIT-NEEDED field '{field}' has no per-variant "
                      f"value in either source -- left null. Triage note: {c['triage_correct_value']!r}")
            # else: field present cleanly from opus (or an exact-name datasheet match with no
            # fallback ambiguity) -- trust it, no action needed.
        elif verdict == "DB-CLEANUP":
            pass  # per-variant extracted value is already the canonical form; leave as-is.
        else:
            _flag(f"'{variant_name}': unknown triage_verdict '{verdict}' on '{field}' -- ignored.")

    return fields, product_type, sources


def _build_source_note(company, product_name, status_entry, sources, group_key, split_type):
    citations = {}
    for field, (kind, source_file, citation) in sources.items():
        if citation:
            citations[field] = f"[{kind}:{source_file}] {citation}"[:300]
    return (
        f"Variant-split migration (docs/variant_split_full_plan_20260824.md), {split_type} case, "
        f"group='{group_key}'. sonnet_source={status_entry.get('sonnet_source_file')}; "
        f"opus_source={status_entry.get('opus_source_file')}. "
        f"Field provenance: {json.dumps(citations, ensure_ascii=False)}"
    )[:9000]


# ──────────────────────────────────────────────────────────── plan building
def _plan_anchor_patch(company, db_row, variant_name, status_entry, fields, product_type):
    ext = base.resolve_extension(company, db_row)
    prod = base.resolve_product(company, db_row)
    if not ext or not prod:
        _flag(f"ANCHOR '{company}||{db_row}': could not resolve existing extension/product record "
              f"-- SKIPPED, needs manual review.")
        SKIPPED.append({"company": company, "db_row": db_row, "reason": "unresolved extension/product"})
        return

    bm_fields, prod_fields, co_fields, unknown = base._route_fields_by_entity(fields)
    if unknown:
        _flag(f"ANCHOR '{company}||{db_row}' ('{variant_name}'): unrouted fields (not in "
              f"fields.json) skipped: {unknown}")
    if co_fields:
        _flag(f"ANCHOR '{company}||{db_row}' ('{variant_name}'): Company-entity fields present, "
              f"not applied (out of scope for this migration): {co_fields}")

    subset_fields = {s["field"] for s in status_entry.get("multiselect_subset_of_db", [])}
    extends_by_field = {e["field"]: e for e in status_entry.get("multiselect_extends", [])}

    n_patch = 0
    for field, value in {**bm_fields, **prod_fields}.items():
        table_hint = "extensions" if field in bm_fields else "products"
        entity = "Base Model" if table_hint == "extensions" else "Product"
        current_raw = (ext.get(field, "") if table_hint == "extensions" else prod.get(field, ""))
        current = base.coerce_current(field, current_raw)

        spec = FIELD_BY_NAME.get(field, {})
        if spec.get("data_type") == "Multi-Select" and current is not None:
            if field in subset_fields:
                continue  # DB is already a documented superset -- never shrink it
            if field in extends_by_field:
                e = extends_by_field[field]
                value = list(dict.fromkeys(
                    (current or []) + [v for v in e["datasheet_value"] if v not in (current or [])]
                ))
            elif not base.values_equal(current, value):
                _flag(f"ANCHOR '{company}||{db_row}' ('{variant_name}'): Multi-Select field "
                      f"'{field}' differs from DB (DB={current!r} vs resolved={value!r}) with no "
                      f"multiselect_subset_of_db/multiselect_extends record -- NOT overwritten, "
                      f"needs manual review.")
                continue

        if base.values_equal(current, value):
            continue
        w = base.check_allowed(field, value)
        if w:
            ALLOWED_VALUE_WARNINGS.append(w)
        base.PLAN["enrich_fills"].append({
            "company": company, "db_row": db_row, "entity": entity,
            "field": field, "new": value, "old": current, "table_hint": table_hint,
        })
        n_patch += 1

    ANCHOR_PATCH_META.append({"company": company, "db_row": db_row, "variant": variant_name,
                               "n_patch_fields": n_patch})

    if product_type:
        gaps = [f for f in _ko_fields_for_product_type(product_type)
                if f not in fields and base.coerce_current(
                    f, (ext.get(f, "") if FIELD_BY_NAME[f]["entity"] == "Base Model" else prod.get(f, ""))
                ) is None]
        if gaps:
            KO_GAPS.append(f"ANCHOR '{company}||{db_row}' ('{variant_name}'): K.O. field(s) still "
                            f"null after patch: {gaps}")


def _plan_new_insert(company, product_name, status_entry, fields, product_type, sources,
                      group_key, split_type):
    if not product_type:
        _flag(f"NEW '{company}||{product_name}' ({group_key}, {split_type}): no product_type "
              f"resolved in either source -- CANNOT CREATE. SKIPPED.")
        SKIPPED.append({"company": company, "product_name": product_name, "reason": "no product_type"})
        return

    bm_fields, prod_fields, co_fields, unknown = base._route_fields_by_entity(fields)
    if unknown:
        _flag(f"NEW '{company}||{product_name}': unrouted fields (not in fields.json) skipped: {unknown}")
    if co_fields:
        _flag(f"NEW '{company}||{product_name}': Company-entity fields present, not applied "
              f"(out of scope for this migration): {co_fields}")

    for k, v in {**bm_fields, **prod_fields}.items():
        w = base.check_allowed(k, v)
        if w:
            ALLOWED_VALUE_WARNINGS.append(w)

    notes = _build_source_note(company, product_name, status_entry, sources, group_key, split_type)

    base.PLAN["new_inserts"].append({
        "company": company,
        "company_is_new": False,
        "base_model_name": product_name,
        "product_name": product_name,
        "product_type": product_type,
        "bm_fields": bm_fields,
        "prod_fields": prod_fields,
        "ext_fields": {**bm_fields},
        "shared_base_model": None,
        "notes": notes,
    })
    NEW_INSERT_META.append({"company": company, "product_name": product_name, "group_key": group_key,
                             "split_type": split_type, "product_type": product_type,
                             "n_bm": len(bm_fields), "n_prod": len(prod_fields)})

    gaps = [f for f in _ko_fields_for_product_type(product_type) if f not in fields]
    if gaps:
        KO_GAPS.append(f"NEW '{company}||{product_name}' ({group_key}): K.O. field(s) left null: {gaps}")


def _plan_deactivate(company, db_row):
    prod = base.resolve_product(company, db_row)
    if not prod:
        _flag(f"DEACTIVATE '{company}||{db_row}': could not resolve existing product record -- "
              f"SKIPPED, needs manual review.")
        SKIPPED.append({"company": company, "db_row": db_row, "reason": "unresolved product for deactivation"})
        return
    old_active = str(prod.get("active", "")).strip().lower() == "true"
    base.PLAN["deactivate"].append({
        "company": company, "db_row": db_row,
        "product_id": prod.get("product_id"),
        "field": "active", "old": old_active, "new": False,
        "reason": "FULL-RETIRE variant split -- superseded by new per-variant rows "
                  "(docs/variant_split_full_plan_20260824.md)",
    })


def process_group(group):
    company = group["company"]
    db_row = group["db_row"]
    decision = group["decision"]
    anchor_name = group.get("anchor")

    resolved = {}
    for vname in group["variants"]:
        se = STATUS_BY_KEY.get((company, vname))
        if not se:
            _flag(f"GROUP '{company}||{db_row}': variant STATUS entry '{vname}' not found in "
                  f"{DOCS.relative_to(ROOT) / 'datasheet_db_status_final.json'} -- SKIPPED.")
            SKIPPED.append({"company": company, "db_row": db_row, "variant": vname,
                             "reason": "STATUS entry not found"})
            continue
        fields, product_type, sources = resolve_variant_fields(se)
        resolved[vname] = (se, fields, product_type, sources)

    if decision == "ANCHOR":
        if anchor_name not in resolved:
            _flag(f"GROUP '{company}||{db_row}': ANCHOR variant '{anchor_name}' could not be "
                  f"resolved -- entire group SKIPPED.")
            SKIPPED.append({"company": company, "db_row": db_row, "reason": "anchor variant unresolved"})
            return
        se, fields, product_type, sources = resolved[anchor_name]
        _plan_anchor_patch(company, db_row, anchor_name, se, fields, product_type)
        for vname, (se2, fields2, pt2, src2) in resolved.items():
            if vname == anchor_name:
                continue
            _plan_new_insert(company, vname, se2, fields2, pt2, src2,
                              group_key=f"{company}||{db_row}", split_type="ANCHOR-sibling")
    else:  # FULL-RETIRE
        for vname, (se2, fields2, pt2, src2) in resolved.items():
            _plan_new_insert(company, vname, se2, fields2, pt2, src2,
                              group_key=f"{company}||{db_row}", split_type="FULL-RETIRE")
        _plan_deactivate(company, db_row)


# ───────────────────────────────────────────────────────────────── summary
def print_summary():
    n_new = len(base.PLAN["new_inserts"])
    n_patch = len(base.PLAN["enrich_fills"])
    n_deact = len(base.PLAN["deactivate"])
    n_anchor_groups = sum(1 for g in GROUPS if g["decision"] == "ANCHOR")
    n_retire_groups = sum(1 for g in GROUPS if g["decision"] == "FULL-RETIRE")

    print("\n" + "=" * 78)
    print("VARIANT-SPLIT MIGRATION -- PRE-RUN SUMMARY")
    print("=" * 78)
    print(f"Groups processed:                    {len(GROUPS)}  ({n_anchor_groups} ANCHOR, "
          f"{n_retire_groups} FULL-RETIRE)")
    print(f"New Base Model/Product/Ext rows to create: {n_new}")
    print(f"Anchor-row field patches:             {n_patch}")
    print(f"Product deactivations (FULL-RETIRE):  {n_deact}")
    print(f"Skipped items:                        {len(SKIPPED)}")
    print(f"AP0 allowed_values warnings:           {len(ALLOWED_VALUE_WARNINGS)}")
    print(f"K.O. field gaps (informational):       {len(KO_GAPS)}")
    print(f"Flags for Tech Lead review:            {len(FLAGS)}")

    print(f"\n--- ANCHOR PATCHES ({len(ANCHOR_PATCH_META)} rows) ---")
    for m in ANCHOR_PATCH_META:
        print(f"  {m['company']} / {m['db_row']} (anchor variant='{m['variant']}'): "
              f"{m['n_patch_fields']} field(s) changed")
    for it in base.PLAN["enrich_fills"]:
        print(f"    [{it['company']} / {it['db_row']}] {it['field']} ({it['entity']}): "
              f"{it['old']!r} -> {it['new']!r}")

    print(f"\n--- NEW ROW CREATIONS ({n_new}) ---")
    for m in NEW_INSERT_META:
        print(f"  {m['company']} :: {m['product_name']} ({m['product_type']}) "
              f"[{m['split_type']}, group={m['group_key']}] -- {m['n_bm']} base-model fields, "
              f"{m['n_prod']} product fields")

    print(f"\n--- PRODUCT DEACTIVATIONS ({n_deact}) ---")
    for it in base.PLAN["deactivate"]:
        print(f"  {it['company']} / {it['db_row']} (product_id={it['product_id']}): "
              f"active {it['old']!r} -> {it['new']!r}  ({it['reason']})")

    if SKIPPED:
        print(f"\n--- SKIPPED ({len(SKIPPED)}) ---")
        for s in SKIPPED:
            print(f"  ! {s}")

    if KO_GAPS:
        print(f"\n--- K.O. FIELD GAPS (informational, not blocking) ({len(KO_GAPS)}) ---")
        for g in KO_GAPS:
            print(f"  ! {g}")

    if ALLOWED_VALUE_WARNINGS:
        print(f"\n--- AP0 allowed_values WARNINGS ({len(ALLOWED_VALUE_WARNINGS)}) ---")
        for w in ALLOWED_VALUE_WARNINGS:
            print(f"  ! {w}")

    print(f"\n--- Flags for Tech Lead ({len(FLAGS)}) ---")
    for f in FLAGS:
        print(f"  ! {f}")


# ──────────────────────────────────────────────────────────────────── main
def main():
    global DRY
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="actually write to Airtable")
    ap.add_argument("--dry-run", action="store_true", help="preview only (default)")
    args = ap.parse_args()
    DRY = not args.run
    base.DRY = DRY
    print(f"MODE: {'LIVE' if args.run else 'DRY RUN'}")

    for group in GROUPS:
        process_group(group)

    if not DRY:
        if not base.TOKEN or not base.BASE_ID:
            sys.exit("ERROR: AIRTABLE_TOKEN / AIRTABLE_BASE_ID not set in .env")
        base.fetch_live_schema()
        base._attach_rec_ids()
        for it in base.PLAN["enrich_fills"] + base.PLAN["deactivate"]:
            if it.get("_rec_id") is None:
                _flag(f"UNRESOLVED rec_id at run-time for {it.get('company')}/"
                      f"{it.get('db_row')}::{it.get('field')} -- this patch will be SILENTLY "
                      f"SKIPPED by execute_fills(). Investigate before re-running.")

    print_summary()

    if not DRY:
        print("\n" + "=" * 78)
        print("EXECUTING LIVE WRITES")
        print("=" * 78)
        base.execute_new_inserts()
        base.execute_fills("ANCHOR PATCHES", base.PLAN["enrich_fills"], lambda it: it["table_hint"])
        base.execute_fills("PRODUCT DEACTIVATIONS", base.PLAN["deactivate"], lambda it: "products")
        print("\nDONE.")
    else:
        print("\nDRY RUN complete -- no Airtable calls were made. Re-run with --run after "
              "Tech Lead sign-off.")


if __name__ == "__main__":
    main()
