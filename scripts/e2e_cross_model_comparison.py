#!/usr/bin/env python3
"""
Cross-model E2E comparison runner for the LLM provider abstraction (R6).

Runs the full tender corpus through the real, running /analyze endpoint (real
pipeline, real hallucination guard) for a given model_id, then queries
data/haystacked.db for per-layer guard null counts (L0/L1/L2/L2_RESCUED) per
tender using the D1 provenance columns in tender_extraction_values. Writes an
incrementally-updated JSON report so partial progress survives a crash.

Does NOT clean up data/haystacked.db afterward — the caller is responsible for
`git checkout -- data/haystacked.db` once all data has been read out of it.

Requires the FastAPI server already running on localhost:8000 (see start.sh). For
a cloud model_id, requires a real OPENROUTER_API_KEY in .env and spends real
money — this is not a `pytest`-suite test and is never run automatically; see
conftest.py's `cloud` marker and docs/spec_llm_provider_abstraction_v0_1.md §2.5
for why this must stay a manual, explicitly-authorized run.

Usage:
    python3 scripts/e2e_cross_model_comparison.py --out docs/some_report.json
    python3 scripts/e2e_cross_model_comparison.py --model-id openrouter-qwen3.8-27b \
        --out docs/some_report.json

To also capture raw (pre-parse) completions for manual quality inspection, start
the server with HAYSTACKED_LLM_RAW_LOG=/path/to/file.log set (see
src/llm_client.py's _debug_log_raw()) before running this script — the raw log
is written by the server process, not by this script.

Precedent: docs/e2e_20260825_llm_provider_comparison/ — first real run, local
qwen2.5:7b vs. openrouter-qwen3.8-27b, full methodology and findings in that
folder's REPORT.md.
"""
import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import httpx
from scripts.capture_pipeline_run import _parse_sse_stream  # reuse proven SSE parser

SERVER_URL = "http://localhost:8000/analyze"
DB_PATH = REPO / "data" / "haystacked.db"

TENDERS = [
    REPO / "tenders" / "Beispielausschreibung_AGV_Nordlicht.pdf",
    REPO / "tenders" / "CompanyX.pdf",
    REPO / "tenders" / "Dragonfly.pdf",
    REPO / "tenders" / "Mama.pdf",
    REPO / "tenders" / "OeA-199-25 Leistungsbeschreibung.pdf",
    REPO / "tenders" / "tender_ik_cold_store.pdf",
    REPO / "tenders" / "tender_ik_deep_freeze.pdf",
    REPO / "tenders" / "tender_ik_process_cooling.pdf",
]


def log(msg: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def run_one(pdf_path: Path, model_id, timeout: float) -> dict:
    data = {}
    if model_id:
        data["model_id"] = model_id
    log(f"→ {pdf_path.name} (model={model_id or 'default'}) ...")
    t0 = time.time()
    pdf_bytes = pdf_path.read_bytes()
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                SERVER_URL,
                files={"file": (pdf_path.name, pdf_bytes, "application/pdf")},
                data=data,
            )
    except Exception as e:
        elapsed = time.time() - t0
        log(f"  TRANSPORT ERROR after {elapsed:.1f}s: {e}")
        return {"error": f"transport: {e}", "elapsed_s": round(elapsed, 1)}

    elapsed = time.time() - t0
    if resp.status_code == 400:
        log(f"  HTTP 400 after {elapsed:.1f}s: {resp.text[:300]}")
        return {"error": resp.json() if resp.text else "HTTP 400", "elapsed_s": round(elapsed, 1)}
    if resp.status_code != 200:
        log(f"  HTTP {resp.status_code} after {elapsed:.1f}s: {resp.text[:300]}")
        return {"error": f"HTTP {resp.status_code}: {resp.text[:300]}", "elapsed_s": round(elapsed, 1)}

    try:
        result = _parse_sse_stream(resp.text)
    except ValueError as e:
        log(f"  SSE PARSE ERROR after {elapsed:.1f}s: {e}")
        return {"error": f"sse_parse: {e}", "elapsed_s": round(elapsed, 1)}

    log(f"  done in {elapsed:.1f}s, analysis_id={result.get('analysis_id')}, "
        f"in_scope={result.get('in_scope')}, model_id={result.get('model_id')}")
    return {"result": result, "elapsed_s": round(elapsed, 1)}


def layer_counts(run_id: str) -> dict:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT nulled_by, COUNT(*) FROM tender_extraction_values WHERE run_id=? GROUP BY nulled_by",
        (run_id,),
    )
    counts = {(k if k else "not_nulled"): v for k, v in cur.fetchall()}
    cur.execute(
        "SELECT COUNT(*) FROM tender_extraction_values "
        "WHERE run_id=? AND provenance_json LIKE '%L2 rescue%'",
        (run_id,),
    )
    counts["L2_RESCUED"] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM tender_extraction_values WHERE run_id=?", (run_id,))
    total = cur.fetchone()[0]
    conn.close()
    counts["total_fields_tracked"] = total
    return counts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model-id", default=None, help="model_id for /analyze; omit for local default")
    p.add_argument("--out", required=True)
    p.add_argument("--timeout", type=float, default=1800.0)
    args = p.parse_args()

    out_path = Path(args.out)
    report = {
        "model_id_requested": args.model_id or "local-default",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "tenders": {},
    }

    for pdf in TENDERS:
        if not pdf.exists():
            log(f"SKIP missing file: {pdf}")
            continue
        r = run_one(pdf, args.model_id, args.timeout)
        entry = {"elapsed_s": r.get("elapsed_s")}
        if "error" in r:
            entry["error"] = r["error"]
        else:
            result = r["result"]
            entry["analysis_id"] = result.get("analysis_id")
            entry["vehicle_type"] = result.get("vehicle_type_canonical")
            entry["in_scope"] = result.get("in_scope")
            entry["actual_model_id"] = result.get("model_id")
            entry["nace_tender"] = result.get("nace_tender")
            if entry["analysis_id"]:
                entry["layer_counts"] = layer_counts(entry["analysis_id"])
            dc = result.get("domain_criteria") or {}
            non_null = {
                k: v for k, v in dc.items()
                if v is not None and not k.startswith("_") and not k.endswith("_source")
            }
            entry["non_null_field_count"] = len(non_null)
            matches = result.get("matches") or []
            entry["top_match"] = (
                {"product": matches[0].get("product"), "score": matches[0].get("score")}
                if matches else None
            )
        report["tenders"][pdf.name] = entry
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    report["finished_at"] = datetime.now().isoformat(timespec="seconds")
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    log(f"DONE. Report written to {out_path}")


if __name__ == "__main__":
    main()
