#!/usr/bin/env python3
"""
Sequential, single-process benchmark across selectable LLM models.

Runs ALL tenders through the full production /analyze pipeline (no golden-file
shortcuts) for each model, one model at a time. The server starts ONCE and stays
up for the whole run — model selection is now per-request (`model_id` form field
on POST /analyze), so there is no more need to stop the server and rewrite an
app.py constant between models (that hack — regex-rewriting OLLAMA_MODEL while
the server was stopped — is retired now that src/llm_client.py exists).

Design invariants (each maps to a past failure mode that this avoids):
  - ONE process owns the whole run. No agents, no background tasks, no waiting
    loops that can "complete" early. Every wait is a blocking call.
  - This process is the SOLE owner of port 8000. It kills any stale listener
    before starting the server and never runs two servers concurrently.
  - Local model_ids are verified present up front (`ollama show`). The script
    hard-fails rather than risk a silent auto-pull invalidating a run.
  - Cost safety: MODELS stays local-model-only by default. Adding a cloud
    (OpenRouter) model_id to a run requires the explicit --include-cloud flag —
    never a silent addition to the default list (§2.5).

Usage:
    python3 scripts/benchmark_models.py
    python3 scripts/benchmark_models.py --include-cloud
    python3 scripts/benchmark_models.py --models local-qwen2.5-7b,openrouter-qwen3.8-27b
Outputs (persistent — never /tmp):
    tests/benchmark_results/benchmark_<model_id>_<YYYYMMDD_HHMMSS>.json
    tests/benchmark_results/logs/server_<YYYYMMDD_HHMMSS>.log
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.llm_client import AVAILABLE_MODELS, DEFAULT_MODEL_ID  # noqa: E402

RESULTS_DIR = ROOT / "tests" / "benchmark_results"
SYNOLOGY_DIR = Path.home() / "SynologyDrive" / "homeDrive" / "Haystacked" / "benchmark_results"

PORT = 8000
BASE_URL = f"http://localhost:{PORT}"
ANALYZE_URL = f"{BASE_URL}/analyze"

# Per-tender HTTP timeout. Cloud models may be slower/faster than local; give
# generous headroom either way.
ANALYZE_TIMEOUT = 4500.0   # 75 min worst-case
SERVER_BOOT_TIMEOUT = 120.0

# Timestamp fixed at import time — all files from one run share the same suffix.
RUN_TS = time.strftime("%Y%m%d_%H%M%S")

TENDERS = [
    ROOT / "tenders" / "Beispielausschreibung_AGV_Nordlicht.pdf",
    ROOT / "tenders" / "Dragonfly.pdf",
    ROOT / "tenders" / "Mama.pdf",
    ROOT / "tenders" / "CompanyX.pdf",
    ROOT / "tenders" / "OeA-199-25 Leistungsbeschreibung.pdf",
]

# Local-model-only by default (cost safety, §2.5) — only the registered local
# model_id(s) from src.llm_client.AVAILABLE_MODELS. Extend with --include-cloud
# or --models, never by editing this default list to include a cloud entry.
MODELS = [DEFAULT_MODEL_ID]

_MODELS_BY_ID = {m.id: m for m in AVAILABLE_MODELS}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ───────────────────────── preflight ─────────────────────────

def verify_models_present(model_ids: list) -> None:
    for model_id in model_ids:
        model = _MODELS_BY_ID.get(model_id)
        if model is None:
            sys.exit(f"FATAL: unknown model_id '{model_id}' — not in "
                     f"src.llm_client.AVAILABLE_MODELS: {sorted(_MODELS_BY_ID)}")
        if model.provider == "ollama":
            r = subprocess.run(["ollama", "show", model.model_name],
                               capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit(f"FATAL: model '{model.model_name}' not installed. "
                         f"Run `ollama pull {model.model_name}` first. Aborting (no auto-pull).")
        elif model.provider == "openrouter" and not os.environ.get("OPENROUTER_API_KEY"):
            sys.exit(f"FATAL: model_id '{model_id}' is an OpenRouter model but "
                     f"OPENROUTER_API_KEY is not set.")
        log(f"verified present: {model_id} ({model.display_name})")


def verify_tenders_present() -> None:
    for t in TENDERS:
        if not t.is_file():
            sys.exit(f"FATAL: tender PDF missing: {t}")
    log(f"verified {len(TENDERS)} tender PDFs present")


# ───────────────────────── server lifecycle ─────────────────────────

def kill_port(port: int) -> None:
    """Kill any process listening on the port. Sole-owner guarantee."""
    r = subprocess.run(["lsof", "-ti", f"tcp:{port}"],
                       capture_output=True, text=True)
    pids = [pid for pid in r.stdout.split() if pid]
    for pid in pids:
        try:
            os.kill(int(pid), signal.SIGKILL)
            log(f"killed stale process {pid} on port {port}")
        except (ProcessLookupError, ValueError):
            pass
    if pids:
        time.sleep(2)


def ensure_ollama() -> None:
    try:
        httpx.get("http://localhost:11434/api/tags", timeout=5.0)
        return
    except Exception:
        log("ollama not reachable — starting `ollama serve`")
        subprocess.Popen(["ollama", "serve"],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        for _ in range(30):
            time.sleep(2)
            try:
                httpx.get("http://localhost:11434/api/tags", timeout=5.0)
                log("ollama up")
                return
            except Exception:
                continue
        sys.exit("FATAL: ollama did not come up")


def start_server() -> subprocess.Popen:
    """Launch uvicorn once for the whole run — no more per-model restart, since
    model selection is now a per-request `model_id` form field."""
    kill_port(PORT)
    log_dir = RESULTS_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"server_{RUN_TS}.log"
    logf = open(log_path, "ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app",
         "--host", "0.0.0.0", "--port", str(PORT)],
        cwd=str(ROOT), stdout=logf, stderr=subprocess.STDOUT,
    )
    deadline = time.time() + SERVER_BOOT_TIMEOUT
    while time.time() < deadline:
        if proc.poll() is not None:
            sys.exit(f"FATAL: uvicorn exited during boot (rc={proc.returncode}); "
                     f"see {log_path}")
        try:
            httpx.get(f"{BASE_URL}/db-status", timeout=5.0)
            log(f"server up (pid {proc.pid})")
            return proc
        except Exception:
            time.sleep(2)
    proc.kill()
    sys.exit(f"FATAL: server did not boot within {SERVER_BOOT_TIMEOUT}s")


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
    kill_port(PORT)
    log("server stopped")


# ───────────────────────── analyze one tender ─────────────────────────

def parse_sse_result(stream_text: str):
    """Extract the `event: result` payload from a full SSE response body."""
    result = None
    error = None
    for block in stream_text.split("\n\n"):
        ev, data_lines = None, []
        for line in block.splitlines():
            if line.startswith("event:"):
                ev = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())
        if not data_lines:
            continue
        payload = "\n".join(data_lines)
        if ev == "result":
            try:
                result = json.loads(payload)
            except json.JSONDecodeError:
                pass
        elif ev == "error":
            error = payload
    if result is None and error:
        return {"_error": error}
    return result


def analyze(tender: Path, model_id: str) -> dict:
    t0 = time.time()
    log(f"  → analyze {tender.name}")
    try:
        with open(tender, "rb") as fh:
            files = {"file": (tender.name, fh, "application/pdf")}
            data = {"model_id": model_id}
            with httpx.Client(timeout=ANALYZE_TIMEOUT) as client:
                resp = client.post(ANALYZE_URL, files=files, data=data)
        if resp.status_code == 400:
            log(f"  ✗ {tender.name}: HTTP 400 (unknown/unavailable model_id)")
            return {"tender": tender.name, "ok": False,
                    "reason": "http_400", "elapsed_s": round(time.time() - t0, 1),
                    "error": resp.text[:500]}
        body = resp.text
        result = parse_sse_result(body)
        elapsed = round(time.time() - t0, 1)
        if result is None:
            log(f"  ✗ {tender.name}: no result event ({elapsed}s)")
            return {"tender": tender.name, "ok": False,
                    "reason": "no_result_event", "elapsed_s": elapsed,
                    "raw_tail": body[-1000:]}
        if "_error" in result:
            log(f"  ✗ {tender.name}: pipeline error ({elapsed}s)")
            return {"tender": tender.name, "ok": False,
                    "reason": "pipeline_error", "elapsed_s": elapsed,
                    "error": result["_error"]}
        log(f"  ✓ {tender.name} ({elapsed}s, server={result.get('duration_s')}s)")
        return {"tender": tender.name, "ok": True, "elapsed_s": elapsed,
                "result": result}
    except Exception as e:
        elapsed = round(time.time() - t0, 1)
        log(f"  ✗ {tender.name}: exception {e!r} ({elapsed}s)")
        return {"tender": tender.name, "ok": False,
                "reason": "exception", "error": repr(e), "elapsed_s": elapsed}


# ───────────────────────── per-model run ─────────────────────────

def run_model(model_id: str, out_path: Path) -> None:
    model = _MODELS_BY_ID[model_id]
    log(f"==================== MODEL: {model_id} ({model.display_name}) ====================")
    runs = [analyze(tender, model_id) for tender in TENDERS]
    summary = {
        "model_id": model_id,
        "model_name": model.model_name,
        "provider": model.provider,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "context_tokens": model.context_tokens,
        "tenders": len(TENDERS),
        "ok_count": sum(1 for r in runs if r.get("ok")),
        "runs": runs,
    }
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    log(f"wrote {out_path}  ({summary['ok_count']}/{len(TENDERS)} ok)")
    if SYNOLOGY_DIR.exists():
        syn_path = SYNOLOGY_DIR / out_path.name
        syn_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        log(f"mirrored to Synology: {syn_path}")
    else:
        log(f"Synology not mounted — skipping mirror ({SYNOLOGY_DIR})")


def _resolve_model_ids(args) -> list:
    if args.models:
        return [m.strip() for m in args.models.split(",") if m.strip()]
    model_ids = list(MODELS)
    if args.include_cloud:
        model_ids += [m.id for m in AVAILABLE_MODELS if not m.is_local and m.id not in model_ids]
    return model_ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--include-cloud", action="store_true",
                        help="Also benchmark every OpenRouter cloud model_id in "
                             "AVAILABLE_MODELS (requires OPENROUTER_API_KEY). Never the "
                             "default — must be explicitly requested (§2.5).")
    parser.add_argument("--models", default=None,
                        help="Comma-separated list of model_ids to benchmark, overriding "
                             "the default local-only list entirely.")
    args = parser.parse_args()

    model_ids = _resolve_model_ids(args)
    log(f"=== haystacked model benchmark: {', '.join(model_ids)} ===")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    SYNOLOGY_DIR.mkdir(parents=True, exist_ok=True) if SYNOLOGY_DIR.parent.exists() else None
    verify_models_present(model_ids)
    verify_tenders_present()
    ensure_ollama()
    proc = start_server()
    try:
        for model_id in model_ids:
            out_path = RESULTS_DIR / f"benchmark_{model_id}_{RUN_TS}.json"
            run_model(model_id, out_path)
    finally:
        stop_server(proc)
    log("=== benchmark complete; port 8000 free ===")


if __name__ == "__main__":
    main()
