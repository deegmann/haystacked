#!/usr/bin/env python3
"""
Sequential, single-process benchmark: qwen2.5:7b vs qwen2.5:14b.

Runs ALL tenders through the full production /analyze pipeline (no golden-file
shortcuts) for each model, strictly one model and one server at a time.

Design invariants (each maps to a past failure mode that this avoids):
  - ONE process owns the whole run. No agents, no background tasks, no waiting
    loops that can "complete" early. Every wait is a blocking call.
  - This process is the SOLE owner of port 8000. It kills any stale listener
    before each server start and never runs two servers concurrently.
  - The OLLAMA_MODEL constant in app.py is edited ONLY while no server is
    running. uvicorn is launched WITHOUT --reload so an edit can
    never hot-restart a live worker mid-benchmark. A try/finally guarantees the
    original constant lines are restored on any exit (success, error, Ctrl-C).
  - Both models are verified present up front (`ollama show`). The script
    hard-fails rather than risk a silent auto-pull invalidating a run.

Usage:
    python3 scripts/benchmark_models.py
Outputs (persistent — never /tmp):
    tests/benchmark_results/benchmark_qwen2.5_7b_<YYYYMMDD_HHMMSS>.json
    tests/benchmark_results/benchmark_qwen2.5_14b_<YYYYMMDD_HHMMSS>.json
    tests/benchmark_results/logs/server_<model>_<YYYYMMDD_HHMMSS>.log
"""

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
APP_PY = ROOT / "app.py"
RESULTS_DIR = ROOT / "tests" / "benchmark_results"
SYNOLOGY_DIR = Path.home() / "SynologyDrive" / "homeDrive" / "Haystacked" / "benchmark_results"

PORT = 8000
BASE_URL = f"http://localhost:{PORT}"
ANALYZE_URL = f"{BASE_URL}/analyze"

# Per-tender HTTP timeout. 14b is slower than 7b's ~330s; give generous headroom.
ANALYZE_TIMEOUT = 4500.0   # 75 min — covers 14b@32768 worst-case
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

MODELS = [
    "qwen2.5:7b",
    "qwen2.5:14b",
]

# Rewrites the OLLAMA_MODEL constant in app.py between benchmark runs.
MODEL_LINE_RE = re.compile(r'^OLLAMA_MODEL\s*=\s*"[^"]*"\s*$', re.MULTILINE)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ───────────────────────── preflight ─────────────────────────

def verify_models_present() -> None:
    for model in MODELS:
        r = subprocess.run(
            ["ollama", "show", model],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            sys.exit(f"FATAL: model '{model}' not installed. "
                     f"Run `ollama pull {model}` first. Aborting (no auto-pull).")
        log(f"verified present: {model}")


def verify_tenders_present() -> None:
    for t in TENDERS:
        if not t.is_file():
            sys.exit(f"FATAL: tender PDF missing: {t}")
    log(f"verified {len(TENDERS)} tender PDFs present")


# ───────────────────── constant edit / revert ─────────────────────

def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def snapshot_constants() -> dict:
    """Capture the original full text of app.py for guaranteed revert."""
    snap = {APP_PY: read_text(APP_PY)}
    if not MODEL_LINE_RE.search(snap[APP_PY]):
        sys.exit(f"FATAL: could not find OLLAMA_MODEL line in {APP_PY}")
    return snap


def set_model_constant(model: str) -> None:
    """Rewrite the OLLAMA_MODEL line in app.py. Server MUST be stopped."""
    new_line = f'OLLAMA_MODEL = "{model}"'
    txt = read_text(APP_PY)
    new_txt, n = MODEL_LINE_RE.subn(new_line, txt)
    if n != 1:
        sys.exit(f"FATAL: expected exactly 1 OLLAMA_MODEL line in {APP_PY}, found {n}")
    APP_PY.write_text(new_txt, encoding="utf-8")
    log(f"set OLLAMA_MODEL = {model} in app.py")


def restore_constants(snap: dict) -> None:
    for p, txt in snap.items():
        p.write_text(txt, encoding="utf-8")
    log("reverted app.py to original constants")


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


def start_server(model: str) -> subprocess.Popen:
    """Launch uvicorn WITHOUT --reload (so edits can never hot-restart it)."""
    kill_port(PORT)
    log_dir = RESULTS_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"server_{model.replace(':', '_')}_{RUN_TS}.log"
    logf = open(log_path, "ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app",
         "--host", "0.0.0.0", "--port", str(PORT)],
        cwd=str(ROOT), stdout=logf, stderr=subprocess.STDOUT,
    )
    # Block until /db-status (or any GET) responds, or boot timeout.
    deadline = time.time() + SERVER_BOOT_TIMEOUT
    while time.time() < deadline:
        if proc.poll() is not None:
            sys.exit(f"FATAL: uvicorn exited during boot (rc={proc.returncode}); "
                     f"see {log_path}")
        try:
            httpx.get(f"{BASE_URL}/db-status", timeout=5.0)
            log(f"server up for {model} (pid {proc.pid})")
            return proc
        except Exception:
            time.sleep(2)
    proc.kill()
    sys.exit(f"FATAL: server for {model} did not boot within {SERVER_BOOT_TIMEOUT}s")


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
    # SSE events are separated by blank lines; each has event:/data: lines.
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


def analyze(tender: Path) -> dict:
    t0 = time.time()
    log(f"  → analyze {tender.name}")
    try:
        with open(tender, "rb") as fh:
            files = {"file": (tender.name, fh, "application/pdf")}
            # stream=False: read the entire SSE body, then parse. One blocking call.
            with httpx.Client(timeout=ANALYZE_TIMEOUT) as client:
                resp = client.post(ANALYZE_URL, files=files)
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

def run_model(model: str, out_path: Path) -> None:
    log(f"==================== MODEL: {model} ====================")
    set_model_constant(model)          # server is stopped here — safe
    proc = start_server(model)
    runs = []
    try:
        for tender in TENDERS:
            runs.append(analyze(tender))
    finally:
        stop_server(proc)
    summary = {
        "model": model,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "num_ctx": 32768,
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


def main() -> None:
    log("=== haystacked model benchmark: 7b then 14b, sequential ===")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    SYNOLOGY_DIR.mkdir(parents=True, exist_ok=True) if SYNOLOGY_DIR.parent.exists() else None
    verify_models_present()
    verify_tenders_present()
    ensure_ollama()
    snap = snapshot_constants()
    try:
        for model in MODELS:
            slug = model.replace(":", "_").replace(".", "_")
            out_path = RESULTS_DIR / f"benchmark_{slug}_{RUN_TS}.json"
            run_model(model, out_path)
    finally:
        # Guaranteed revert + guaranteed no orphaned server, on any exit path.
        kill_port(PORT)
        restore_constants(snap)
    log("=== benchmark complete; constants reverted; port 8000 free ===")


if __name__ == "__main__":
    main()
