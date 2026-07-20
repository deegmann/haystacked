"""
Tender analysis persistence layer.
Builds TenderRun from pipeline output and stores to SQLite.
"""
import dataclasses
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.models import ExtractionValue, TenderRun
from src.field_spec import FieldSpec, fields_by_tender_key
from src.matching import MatchResult

DB_PATH = Path(__file__).parent.parent / "data" / "haystacked.db"

# Allowlist of keys copied from the pipeline `result` dict into basic_info.
# Never use dict(result) — internal keys (_parse_method, agv_criteria, etc.) must not leak.
_BASIC_INFO_KEYS = frozenset({
    "buyer", "project_name", "buyer_industry", "tender_category",
    "is_agv_amr", "detected_domain", "summary",
    "contact_name", "contact_email", "contact_phone",
    "deadline", "tender_date",
    "nace_tender", "in_scope",
})

_CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS tender_runs (
    run_id           TEXT PRIMARY KEY,
    source_file      TEXT NOT NULL,
    captured_at      TEXT NOT NULL,
    vehicle_type     TEXT,
    in_scope         INTEGER NOT NULL DEFAULT 0,
    basic_info_json  TEXT NOT NULL DEFAULT '{}'
)
"""

_CREATE_VALUES = """
CREATE TABLE IF NOT EXISTS tender_extraction_values (
    run_id      TEXT NOT NULL,
    field_uuid  TEXT NOT NULL,
    value_json  TEXT,      -- JSON-encoded; "null" (string) = explicitly null, not absent
    source      TEXT,
    spec_json   TEXT,      -- JSON snapshot of FieldSpec at time of run; NULL for pre-Phase-3b rows
    PRIMARY KEY (run_id, field_uuid),
    FOREIGN KEY (run_id) REFERENCES tender_runs(run_id)
)
"""

_CREATE_MATCH_RESULTS = """
CREATE TABLE IF NOT EXISTS tender_run_match_results (
    run_id             TEXT NOT NULL,
    product_id         TEXT NOT NULL,
    product_name       TEXT,
    score              INTEGER NOT NULL DEFAULT 0,
    disqualified       INTEGER NOT NULL DEFAULT 0,
    disqualified_by    TEXT,          -- JSON array of reason strings
    score_details      TEXT,          -- JSON array of {field, points, value}
    PRIMARY KEY (run_id, product_id),
    FOREIGN KEY (run_id) REFERENCES tender_runs(run_id)
)
"""


def init_db(db_path: Path = DB_PATH) -> None:
    """Create tender tables if they don't exist. Idempotent.
    Migrates pre-Phase-3b rows: adds spec_json column if absent."""
    con = sqlite3.connect(db_path)
    con.execute(_CREATE_RUNS)
    con.execute(_CREATE_VALUES)
    con.execute(_CREATE_MATCH_RESULTS)
    # Migration: add spec_json column to existing tables (pre-Phase-3b DBs have 4-column schema)
    existing_cols = {row[1] for row in con.execute("PRAGMA table_info(tender_extraction_values)")}
    if "spec_json" not in existing_cols:
        con.execute("ALTER TABLE tender_extraction_values ADD COLUMN spec_json TEXT")
    con.commit()
    con.close()


def build_tender_run(
    run_id: str,
    source_file: str,
    new_req: dict,         # post-conversion tender criteria (tender_key-keyed + _source keys)
    agv_criteria: dict,    # pre-conversion dict — used ONLY to extract _source citations
    result: dict,          # full pipeline result dict — allowlisted keys go into basic_info
    vehicle_type: Optional[str],
    in_scope: bool,
) -> TenderRun:
    """Build a TenderRun from the pipeline output at the matching boundary."""
    tk_to_specs = fields_by_tender_key()  # tender_key → list[FieldSpec]
    values: dict[str, ExtractionValue] = {}

    for tender_key, specs in tk_to_specs.items():
        raw_val = new_req.get(tender_key)
        source  = agv_criteria.get(f"{tender_key}_source")
        for spec in specs:
            values[spec.uuid] = ExtractionValue(
                spec   = spec,
                value  = raw_val,
                source = source,
            )

    basic_info = {k: result.get(k) for k in _BASIC_INFO_KEYS if k in result}

    return TenderRun(
        run_id       = run_id,
        source_file  = source_file,
        captured_at  = datetime.now(timezone.utc).isoformat(timespec="seconds"),
        vehicle_type = vehicle_type,
        in_scope     = in_scope,
        values       = values,
        basic_info   = basic_info,
    )


def persist_tender_run(
    run: TenderRun,
    match_results: list = None,   # list of MatchResult objects
    db_path: Path = DB_PATH,
) -> None:
    """Write TenderRun to SQLite. Replaces any existing run with the same run_id."""
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            "INSERT OR REPLACE INTO tender_runs VALUES (?,?,?,?,?,?)",
            (
                run.run_id, run.source_file, run.captured_at,
                run.vehicle_type, int(run.in_scope),
                json.dumps(run.basic_info, ensure_ascii=False),
            ),
        )
        con.execute(
            "DELETE FROM tender_extraction_values WHERE run_id = ?", (run.run_id,)
        )
        con.executemany(
            "INSERT INTO tender_extraction_values VALUES (?,?,?,?,?)",
            [
                (
                    run.run_id,
                    ev.spec.uuid if ev.spec else uuid_key,
                    json.dumps(ev.value, ensure_ascii=False),
                    ev.source,
                    json.dumps(dataclasses.asdict(ev.spec), ensure_ascii=False) if ev.spec else None,
                )
                for uuid_key, ev in run.values.items()
            ],
        )
        if match_results:
            con.execute("DELETE FROM tender_run_match_results WHERE run_id = ?", (run.run_id,))
            con.executemany(
                "INSERT INTO tender_run_match_results VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        run.run_id,
                        mr.record.product.product_id,
                        mr.record.product.product_name,
                        mr.score,
                        int(mr.disqualified),
                        json.dumps(mr.disqualified_by, ensure_ascii=False),
                        json.dumps(mr.score_details, ensure_ascii=False),
                    )
                    for mr in match_results
                ],
            )
        con.commit()
    finally:
        con.close()


def load_tender_run(run_id: str, db_path: Path = DB_PATH) -> Optional[TenderRun]:
    """Load a persisted TenderRun. Returns None if not found.
    Orphaned UUIDs (removed from AP0 since persistence) are loaded with spec=None handled gracefully."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT * FROM tender_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None

        ev_rows = con.execute(
            "SELECT field_uuid, value_json, source, spec_json FROM tender_extraction_values WHERE run_id = ?",
            (run_id,)
        ).fetchall()

        values: dict[str, ExtractionValue] = {}
        for ev_row in ev_rows:
            uuid = ev_row["field_uuid"]
            spec = None
            if ev_row["spec_json"]:
                try:
                    spec = FieldSpec(**json.loads(ev_row["spec_json"]))
                except Exception:
                    pass  # malformed snapshot — treat as orphaned
            values[uuid] = ExtractionValue(
                spec   = spec,
                value  = json.loads(ev_row["value_json"]) if ev_row["value_json"] is not None else None,
                source = ev_row["source"],
            )

        return TenderRun(
            run_id       = row["run_id"],
            source_file  = row["source_file"],
            captured_at  = row["captured_at"],
            vehicle_type = row["vehicle_type"],  # display label only — do NOT pass to vt_map or AP0 lookup
            in_scope     = bool(row["in_scope"]),
            values       = values,
            basic_info   = json.loads(row["basic_info_json"]),
        )
    finally:
        con.close()
