"""OI-115c Phase 3E — LIVE Airtable field rename via the Metadata API.

Renames the 36 Base Model Extensions fields whose AP0 field_name lost its unit
suffix in Phase 3C, so Airtable field names match AP0 / sqlite_schema.json again
and `sync_airtable.py`'s Phase-3B header guard stops being the only thing
standing between a fresh sync and a silent 36-column data wipe.

Modes
-----
  --snapshot   Write the pre-rename schema snapshot (rollback source). Do first.
  --probe      Rename-then-revert `_test_field_delete_me`. Proves write scope.
  --dry-run    Resolve + plan the 36 PATCHes, issue none.
  --apply      Issue the 36 PATCHes, frozen order, halt on first non-2xx.
  --verify     Read-only post-rename verification against the snapshot.
  --revert     Restore OLD names from the snapshot. HUMAN-TRIGGERED ONLY.

Invariants
----------
* Field IDs are resolved FRESH from GET /v0/meta/bases/{id}/tables on every run.
  Never from a cached list.
* A rename touches no record data. Airtable field IDs are immutable across
  renames, which is why the snapshot alone is a complete rollback source.
* On the first non-2xx: HALT. No auto-rollback (a rollback PATCH uses the same
  token/network that just failed; a half-done rollback converts a deterministic
  resumable prefix into an arbitrary state). --apply is idempotent: re-running
  skips fields already carrying their new name.
* Every PATCH is appended to the JSONL audit log before the next one is issued.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from oi115c_rename_map import RENAME  # noqa: E402

BME_TABLE_ID = "tblinb1Zn0Ihc977M"          # Base Model Extensions
PROBE_FIELD = "_test_field_delete_me"        # not in extensions_columns → inert
PROBE_TEMP = "_test_field_delete_me_probe"
SNAPSHOT = REPO / "Spec" / "airtable_schema_snapshot_pre_oi115c_3e.json"
AUDIT_LOG = REPO / "docs" / "oi115c_3e_rename_log.jsonl"
PATCH_PAUSE_S = 0.30                          # 5 req/s per base → 3.3 req/s


# ── plumbing ────────────────────────────────────────────────────────────────

def load_env() -> tuple[str, str]:
    env = {}
    for line in (REPO / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v.strip().strip('"').strip("'")
    try:
        return env["AIRTABLE_TOKEN"], env["AIRTABLE_BASE_ID"]
    except KeyError as e:
        sys.exit(f"ERROR: {e} missing from {REPO / '.env'}")


TOKEN, BASE = load_env()


def _call(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload = json.loads(raw or b"{}")
        except Exception:
            payload = {"raw": raw.decode("utf-8", "replace")[:500]}
        return e.code, payload


def get_schema() -> dict:
    status, data = _call("GET", f"https://api.airtable.com/v0/meta/bases/{BASE}/tables")
    if status != 200:
        sys.exit(f"ERROR: GET tables -> HTTP {status}: {json.dumps(data)[:400]}")
    return data


def bme_fields(schema: dict) -> dict[str, str]:
    """name -> field_id for the Base Model Extensions table."""
    t = next((t for t in schema["tables"] if t["id"] == BME_TABLE_ID), None)
    if t is None:
        sys.exit(f"ERROR: table {BME_TABLE_ID} not found in live base {BASE}")
    return {f["name"]: f["id"] for f in t["fields"]}


def patch_field(field_id: str, new_name: str) -> tuple[int, dict]:
    return _call(
        "PATCH",
        f"https://api.airtable.com/v0/meta/bases/{BASE}/tables/{BME_TABLE_ID}/fields/{field_id}",
        {"name": new_name},
    )


def audit(entry: dict) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return None


# ── modes ───────────────────────────────────────────────────────────────────

def mode_snapshot(force: bool) -> int:
    if SNAPSHOT.exists() and not force:
        sys.exit(f"ERROR: {SNAPSHOT} already exists. Use --force to overwrite "
                 "(you almost certainly do NOT want to overwrite a pre-rename snapshot).")
    schema = get_schema()
    SNAPSHOT.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    n = sum(len(t["fields"]) for t in schema["tables"])
    print(f"OK  snapshot -> {SNAPSHOT}")
    print(f"    {len(schema['tables'])} tables, {n} fields total, "
          f"{SNAPSHOT.stat().st_size} bytes")
    for t in schema["tables"]:
        print(f"      {t['id']}  {t['name']:<28} {len(t['fields'])} fields")
    audit({"mode": "snapshot", "path": str(SNAPSHOT), "tables": len(schema["tables"]), "fields": n})
    return 0


def mode_probe() -> int:
    """Definitive empirical test of schema.bases:write. Zero blast radius."""
    print("=== PROBE: rename-then-revert on an inert field ===")
    names = bme_fields(get_schema())
    if PROBE_FIELD not in names:
        print(f"FAIL  probe field '{PROBE_FIELD}' not present in BME. "
              f"Do NOT substitute a real field. Abort.")
        return 2
    fid = names[PROBE_FIELD]
    print(f"  probe field id = {fid}")

    # 1. forward
    st, body = patch_field(fid, PROBE_TEMP)
    print(f"  PATCH -> '{PROBE_TEMP}' : HTTP {st}  {json.dumps(body)[:200]}")
    audit({"mode": "probe", "step": "forward", "field_id": fid,
           "old": PROBE_FIELD, "new": PROBE_TEMP, "http": st, "body": body})
    if st != 200 or body.get("id") != fid or body.get("name") != PROBE_TEMP:
        print("FAIL  forward PATCH did not return 200 with {id: <same>, name: <new>}.")
        print("      => token lacks schema.bases:write (or the table is locked).")
        print("      => Phase 3E LIVE RENAME IS BLOCKED. Do not proceed. See rollback plan.")
        return 3

    # 2. independent read-back
    live = bme_fields(get_schema())
    if PROBE_TEMP not in live or live[PROBE_TEMP] != fid or PROBE_FIELD in live:
        print("FAIL  read-back did not confirm the rename. Manual inspection required.")
        return 4
    print("  read-back confirms rename is live")

    # 3. revert
    st2, body2 = patch_field(fid, PROBE_FIELD)
    print(f"  PATCH -> '{PROBE_FIELD}' : HTTP {st2}  {json.dumps(body2)[:200]}")
    audit({"mode": "probe", "step": "revert", "field_id": fid,
           "old": PROBE_TEMP, "new": PROBE_FIELD, "http": st2, "body": body2})
    if st2 != 200 or body2.get("name") != PROBE_FIELD:
        print(f"FAIL  revert failed. '{PROBE_TEMP}' is LIVE in Airtable — rename it back "
              f"by hand in the UI. Write scope IS proven, but resolve this first.")
        return 5

    # 4. read-back of revert
    live2 = bme_fields(get_schema())
    if PROBE_FIELD not in live2 or live2[PROBE_FIELD] != fid or PROBE_TEMP in live2:
        print("FAIL  revert read-back inconsistent. Manual inspection required.")
        return 6
    if len(live2) != len(names):
        print(f"FAIL  BME field count changed {len(names)} -> {len(live2)}. Investigate.")
        return 7

    print(f"\nPROBE PASSED — schema.bases:write is confirmed, base is writable, "
          f"BME still {len(live2)} fields, probe field restored.")
    return 0


def _plan(names: dict[str, str]) -> tuple[list[dict], list[dict], list[str]]:
    """Returns (todo, already_done, unexpected) in frozen alphabetical-by-old order."""
    todo, done, unexpected = [], [], []
    for old in sorted(RENAME):
        new = RENAME[old]
        if old in names:
            todo.append({"field_id": names[old], "old": old, "new": new})
        elif new in names:
            done.append({"field_id": names[new], "old": old, "new": new})
        else:
            unexpected.append(old)
    return todo, done, unexpected


def mode_apply(dry_run: bool) -> int:
    tag = "DRY-RUN" if dry_run else "APPLY"
    print(f"=== {tag}: 36-field rename, frozen order (alphabetical by old name) ===")
    names = bme_fields(get_schema())
    todo, done, unexpected = _plan(names)

    print(f"  BME live fields       : {len(names)}")
    print(f"  RENAME map entries    : {len(RENAME)}")
    print(f"  to rename (old name)  : {len(todo)}")
    print(f"  already renamed (skip): {len(done)} -> {[d['new'] for d in done]}")
    print(f"  no Airtable field     : {len(unexpected)} -> {unexpected}")

    # Expected steady state: 36 renameable + 2 that have never existed in Airtable.
    if sorted(unexpected) != ["tugger_min_aisle_width_mm", "typical_project_value_eur"]:
        print("HALT  the set of map entries with no Airtable field is not the expected 2.")
        print("      Someone changed the base. Re-run --snapshot and re-verify before proceeding.")
        return 10

    collisions = [t for t in todo if t["new"] in names]
    if collisions:
        print(f"HALT  {len(collisions)} new name(s) already exist as a DIFFERENT field "
              f"(Airtable will 422): {[c['new'] for c in collisions]}")
        return 11

    if dry_run:
        for i, t in enumerate(todo, 1):
            print(f"  {i:2d}. {t['field_id']}  {t['old']}  ->  {t['new']}")
        print(f"\nDRY-RUN OK. {len(todo)} PATCHes planned, "
              f"~{len(todo) * PATCH_PAUSE_S:.0f}s + latency wall clock.")
        return 0

    audit({"mode": "apply", "event": "start", "planned": len(todo),
           "skipped_already_renamed": len(done)})
    t0 = time.time()
    ok = 0
    for i, t in enumerate(todo, 1):
        st, body = patch_field(t["field_id"], t["new"])
        rec = {"mode": "apply", "seq": i, "field_id": t["field_id"],
               "old": t["old"], "new": t["new"], "http": st,
               "returned_name": body.get("name"), "returned_id": body.get("id")}
        audit(rec)
        mark = "ok " if st == 200 else "ERR"
        print(f"  [{mark}] {i:2d}/{len(todo)}  HTTP {st}  {t['old']} -> {t['new']}")
        if st != 200 or body.get("name") != t["new"] or body.get("id") != t["field_id"]:
            print(f"\nHALT at #{i}. Response: {json.dumps(body)[:400]}")
            print(f"  SUCCEEDED ({ok}): {[x['new'] for x in todo[:i - 1]]}")
            print(f"  FAILED       : {t['old']}")
            print(f"  NOT ATTEMPTED ({len(todo) - i}): {[x['old'] for x in todo[i:]]}")
            print("  NO automatic rollback. Airtable is now in a MIXED state; the "
                  "Phase-3B header guard will correctly refuse any sync. "
                  "Recovery: fix the cause, re-run --apply (idempotent). "
                  "Abandon: --revert.")
            audit({"mode": "apply", "event": "halt", "seq": i, "succeeded": ok,
                   "failed": t["old"], "not_attempted": [x["old"] for x in todo[i:]]})
            return 12
        ok += 1
        if i < len(todo):
            time.sleep(PATCH_PAUSE_S)

    dt = time.time() - t0
    print(f"\nAPPLY COMPLETE — {ok}/{len(todo)} renamed in {dt:.1f}s "
          f"({len(done)} were already renamed).")
    audit({"mode": "apply", "event": "complete", "renamed": ok, "seconds": round(dt, 1)})
    return 0


def mode_verify() -> int:
    print("=== VERIFY (read-only) ===")
    if not SNAPSHOT.exists():
        sys.exit(f"ERROR: {SNAPSHOT} missing — run --snapshot before the rename, not after.")
    snap = json.loads(SNAPSHOT.read_text())
    live = get_schema()

    snap_ids = {t["id"]: {f["id"]: f["name"] for f in t["fields"]} for t in snap["tables"]}
    live_ids = {t["id"]: {f["id"]: f["name"] for f in t["fields"]} for t in live["tables"]}

    fails = []

    if set(snap_ids) != set(live_ids):
        fails.append(f"table set changed: {set(snap_ids) ^ set(live_ids)}")

    for tid in sorted(set(snap_ids) & set(live_ids)):
        s, l = snap_ids[tid], live_ids[tid]
        if set(s) != set(l):
            fails.append(f"{tid}: field ID set changed "
                         f"(+{[l[k] for k in set(l) - set(s)]} "
                         f"-{[s[k] for k in set(s) - set(l)]}) "
                         f"— a field was DELETED/RECREATED, not renamed")
        renamed = {k: (s[k], l[k]) for k in set(s) & set(l) if s[k] != l[k]}
        if tid == BME_TABLE_ID:
            expected = {fid: (s[fid], RENAME[s[fid]]) for fid in s if s[fid] in RENAME}
            if renamed != expected:
                unexpected = {k: v for k, v in renamed.items() if expected.get(k) != v}
                missing = {k: v for k, v in expected.items() if renamed.get(k) != v}
                fails.append(f"BME renames != expected. "
                             f"unexpected={unexpected} missing={missing}")
            else:
                print(f"  OK  BME: exactly {len(renamed)} fields renamed, "
                      f"all field IDs preserved, {len(l)} fields total")
        elif renamed:
            fails.append(f"{tid} ({[t['name'] for t in live['tables'] if t['id'] == tid][0]}): "
                         f"unexpected renames {renamed}")

    names = bme_fields(live)
    still_old = [o for o in RENAME if o in names]
    missing_new = [RENAME[o] for o in RENAME
                   if RENAME[o] not in names
                   and o not in ("tugger_min_aisle_width_mm", "typical_project_value_eur")]
    if still_old:
        fails.append(f"OLD names still live: {still_old}")
    if missing_new:
        fails.append(f"NEW names absent: {missing_new}")

    if fails:
        print("\nVERIFY FAILED:")
        for f in fails:
            print(f"  - {f}")
        return 20
    print(f"  OK  0 old names remain, 36 new names live, no field deleted/recreated")
    print("\nVERIFY PASSED — rename is complete and data-preserving.")
    audit({"mode": "verify", "result": "pass"})
    return 0


def mode_revert(yes: bool) -> int:
    print("=== REVERT (snapshot-driven, human-triggered) ===")
    if not SNAPSHOT.exists():
        sys.exit(f"ERROR: {SNAPSHOT} missing — cannot revert without the pre-rename snapshot.")
    snap = json.loads(SNAPSHOT.read_text())
    snap_bme = next(t for t in snap["tables"] if t["id"] == BME_TABLE_ID)
    want = {f["id"]: f["name"] for f in snap_bme["fields"]}

    live = get_schema()
    live_bme = next(t for t in live["tables"] if t["id"] == BME_TABLE_ID)
    todo = [(f["id"], f["name"], want[f["id"]]) for f in live_bme["fields"]
            if f["id"] in want and f["name"] != want[f["id"]]]

    print(f"  {len(todo)} field(s) differ from the snapshot:")
    for fid, cur, orig in todo:
        print(f"    {fid}  {cur}  ->  {orig}")
    if not todo:
        print("  nothing to revert.")
        return 0
    if not yes:
        print("\n  Re-run with --yes to actually issue these PATCHes.")
        return 0

    for i, (fid, cur, orig) in enumerate(todo, 1):
        st, body = patch_field(fid, orig)
        audit({"mode": "revert", "seq": i, "field_id": fid, "old": cur,
               "new": orig, "http": st, "returned_name": body.get("name")})
        print(f"  [{'ok ' if st == 200 else 'ERR'}] {i}/{len(todo)}  HTTP {st}  {cur} -> {orig}")
        if st != 200:
            print(f"HALT during revert at #{i}: {json.dumps(body)[:400]}")
            print("  Remaining fields must be renamed by hand in the Airtable UI, "
                  "using the snapshot as the reference.")
            return 30
        if i < len(todo):
            time.sleep(PATCH_PAUSE_S)
    print("\nREVERT COMPLETE.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="OI-115c Phase 3E live Airtable rename")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--snapshot", action="store_true")
    g.add_argument("--probe", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--verify", action="store_true")
    g.add_argument("--revert", action="store_true")
    p.add_argument("--force", action="store_true", help="allow --snapshot to overwrite")
    p.add_argument("--yes", action="store_true", help="arm --revert")
    a = p.parse_args()

    if a.snapshot:
        return mode_snapshot(a.force)
    if a.probe:
        return mode_probe()
    if a.dry_run:
        return mode_apply(dry_run=True)
    if a.apply:
        return mode_apply(dry_run=False)
    if a.verify:
        return mode_verify()
    if a.revert:
        return mode_revert(a.yes)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
