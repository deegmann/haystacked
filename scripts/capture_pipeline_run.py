#!/usr/bin/env python3
"""Capture a live pipeline run against the running FastAPI server.

Posts a PDF to the /analyze endpoint, parses the SSE stream, extracts the
agv_criteria, match_results, and vehicle_type from the JSON payload, and saves
a structured JSON to tests/tenders/golden_run_tender_XXX.json.

Usage:
    python3 scripts/capture_pipeline_run.py tenders/Beispielausschreibung_AGV_Nordlicht.pdf
    python3 scripts/capture_pipeline_run.py tenders/Dragonfly.pdf --out tests/tenders/golden_run_tender_001.json
    python3 scripts/capture_pipeline_run.py tenders/Mama.pdf --dry-run

The script does NOT run the LLM itself — it calls the already-running FastAPI
server at http://localhost:8000.

Output file format:
    {
      "source_file": "<filename>",
      "vehicle_type": "...",
      "agv_criteria": { ... },
      "match_results": [ ... ],
      "captured_at": "2026-06-04T12:34:56",
      "duration_s": 330.1
    }
"""
import argparse
import json
import sys
import re
from datetime import datetime
from pathlib import Path


SERVER_URL = "http://localhost:8000/analyze"


def _derive_tender_id(pdf_path: Path) -> str:
    """Derive a tender ID from the PDF filename.

    Examples:
        Dragonfly.pdf              → tender_dragonfly
        Mama.pdf                   → tender_mama
        Beispielausschreibung_AGV_Nordlicht.pdf → tender_nordlicht
        CompanyX.pdf               → tender_companyx
    """
    stem = pdf_path.stem.lower()
    # Extract the last meaningful word (handles long German filenames)
    parts = re.split(r"[_\-\s]+", stem)
    slug = parts[-1] if parts else stem
    # Strip non-alphanumeric
    slug = re.sub(r"[^a-z0-9]", "", slug)
    return f"tender_{slug}"


def _parse_sse_stream(response_text: str) -> dict:
    """Parse an SSE response body and extract the 'result' event payload.

    Returns the parsed JSON dict from the first 'event: result' block found.
    Raises ValueError if no result event is found.
    """
    result_payload = None
    current_event = None
    current_data_lines = []

    for line in response_text.splitlines():
        line = line.rstrip()
        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
            current_data_lines = []
        elif line.startswith("data:"):
            current_data_lines.append(line[len("data:"):].strip())
        elif line == "":
            # End of SSE message
            if current_event == "result" and current_data_lines:
                data_str = "\n".join(current_data_lines)
                try:
                    result_payload = json.loads(data_str)
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"Failed to parse SSE result payload: {e}\n"
                        f"Raw data: {data_str[:500]}"
                    )
                break  # Stop at first result event
            current_event = None
            current_data_lines = []

    if result_payload is None:
        raise ValueError(
            "No 'event: result' found in SSE stream. "
            "Check that the server is running and the analysis completed."
        )
    return result_payload


def capture(pdf_path: Path, out_path: Path, dry_run: bool = False) -> dict:
    """POST the PDF to the server, parse the SSE stream, and save the golden run.

    Returns the structured capture dict.
    """
    try:
        import httpx
    except ImportError:
        print("ERROR: httpx is required. Install with: pip install httpx", file=sys.stderr)
        sys.exit(1)

    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Posting {pdf_path.name} to {SERVER_URL} ...")
    t0 = datetime.now()

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    # Use a long timeout — AGV analysis takes ~330s
    with httpx.Client(timeout=600.0) as client:
        response = client.post(
            SERVER_URL,
            files={"file": (pdf_path.name, pdf_bytes, "application/pdf")},
        )

    elapsed = (datetime.now() - t0).total_seconds()
    print(f"Response received in {elapsed:.1f}s (HTTP {response.status_code})")

    if response.status_code != 200:
        print(f"ERROR: Server returned HTTP {response.status_code}", file=sys.stderr)
        print(response.text[:1000], file=sys.stderr)
        sys.exit(1)

    result = _parse_sse_stream(response.text)

    agv_criteria = result.get("agv_criteria") or {}
    match_results = result.get("matches") or []
    matches_all   = result.get("matches_all") or []

    # Extract vehicle type: top-level result key (set by app.py after Pass 4a)
    vehicle_type = (
        result.get("vehicle_type_canonical")
        or agv_criteria.get("required_agv_type")
        or "unknown"
    )

    capture_doc = {
        "source_file":    pdf_path.name,
        "vehicle_type":   vehicle_type,
        "agv_criteria":   agv_criteria,
        "match_results":  match_results,
        "matches_all":    matches_all,
        "captured_at":    datetime.now().isoformat(timespec="seconds"),
        "duration_s":     round(elapsed, 1),
    }

    # Summary
    non_null = {k: v for k, v in agv_criteria.items()
                if v is not None and not k.startswith("_") and not k.endswith("_source")}
    print(f"\n=== Extraction summary ===")
    print(f"Vehicle type : {vehicle_type}")
    print(f"Non-null fields ({len(non_null)}):")
    for k, v in sorted(non_null.items()):
        print(f"  {k}: {v}")
    print(f"\nMatches returned: {len(match_results)} top / {len(matches_all)} total evaluated")
    if match_results:
        top = match_results[0]
        print(f"Top match: {top.get('product', '?')} (score {top.get('score', '?')})")

    if dry_run:
        print(f"\n[dry-run] Would write to: {out_path}")
        print(json.dumps(capture_doc, ensure_ascii=False, indent=2)[:2000])
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(capture_doc, f, ensure_ascii=False, indent=2)
        print(f"\nSaved golden run to: {out_path}")

    return capture_doc


def main():
    global SERVER_URL
    parser = argparse.ArgumentParser(
        description="Capture a pipeline run from the running FastAPI server and save as golden run JSON.",
    )
    parser.add_argument(
        "pdf",
        type=Path,
        help="Path to the PDF tender file (e.g. tenders/Mama.pdf)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Output path for the golden run JSON. "
            "Defaults to tests/tenders/golden_run_<tender_id>.json"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be saved without writing to disk",
    )
    parser.add_argument(
        "--server",
        default=SERVER_URL,
        help=f"Server URL (default: {SERVER_URL})",
    )
    args = parser.parse_args()

    SERVER_URL = args.server

    pdf_path = args.pdf
    tender_id = _derive_tender_id(pdf_path)

    if args.out:
        out_path = args.out
    else:
        out_path = Path(__file__).parent.parent / "tests" / "tenders" / f"golden_run_{tender_id}.json"

    capture(pdf_path, out_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
