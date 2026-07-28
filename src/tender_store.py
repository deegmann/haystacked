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
    "detected_domain", "summary",
    "contact_name", "contact_email", "contact_phone",
    "deadline", "tender_date",
    "nace_tender", "in_scope",
})

# D1 provenance vocabularies — CLOSED and APPEND-ONLY. Both describe pipeline
# STAGES, never fields or vehicle types. A new entry must name a new extraction/
# validation/matching *step* (e.g. a future pipeline pass). A hypothetical entry
# named after a field or domain concept (e.g. "vna_check") would be an
# AP0-boundary violation — do not add one.
# "dialog" is reserved for future /rematch-driven user corrections — not yet
# wired; /rematch does not currently call build_tender_run()/persist_tender_run()
# at all (separate backlog item, OI-54). Do not treat its presence here as an
# indication that dialog-sourced provenance is already tracked.
_PRODUCED_BY_VALUES = frozenset({"4a", "4b", "4c", "fallback", "replay", "dialog"})
_NULLED_BY_VALUES = frozenset({"L0", "L1", "L2", "allowed_values", "plausibility"})

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
    run_id           TEXT NOT NULL,
    field_uuid       TEXT NOT NULL,
    value_json       TEXT,      -- JSON-encoded; "null" (string) = explicitly null, not absent
    source           TEXT,
    spec_json        TEXT,      -- JSON snapshot of FieldSpec at time of run; NULL for pre-Phase-3b rows
    produced_by      TEXT,      -- D1: which pass produced this value; see _PRODUCED_BY_VALUES. NULL = untracked (pre-D1 rows).
    nulled_by        TEXT,      -- D1: which guard/validation layer nulled this value, if any; see _NULLED_BY_VALUES. NULL = not nulled or untracked.
    provenance_json  TEXT,      -- D1/D1a: loose diagnostic dict (raw_value, raw_source, pre_4c_value,
                                 -- pre_4c_source, pass_4c_state, notes). "notes" is write-only — no pipeline
                                 -- code may ever read, parse, or branch on it. NULL for pre-D1 rows.
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
    Migrates pre-Phase-3b rows: adds spec_json column if absent.
    Migrates pre-D1 rows: adds produced_by/nulled_by/provenance_json columns if absent."""
    con = sqlite3.connect(db_path)
    con.execute(_CREATE_RUNS)
    con.execute(_CREATE_VALUES)
    con.execute(_CREATE_MATCH_RESULTS)
    # Migration: add spec_json column to existing tables (pre-Phase-3b DBs have 4-column schema)
    existing_cols = {row[1] for row in con.execute("PRAGMA table_info(tender_extraction_values)")}
    if "spec_json" not in existing_cols:
        con.execute("ALTER TABLE tender_extraction_values ADD COLUMN spec_json TEXT")
    # Migration: add D1 provenance columns to existing tables (pre-D1 DBs lack them)
    existing_cols = {row[1] for row in con.execute("PRAGMA table_info(tender_extraction_values)")}
    for _col in ("produced_by", "nulled_by", "provenance_json"):
        if _col not in existing_cols:
            con.execute(f"ALTER TABLE tender_extraction_values ADD COLUMN {_col} TEXT")
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
    field_provenance: Optional[dict] = None,  # D1: tender_key -> {produced_by, nulled_by, provenance}
) -> TenderRun:
    """Build a TenderRun from the pipeline output at the matching boundary."""
    tk_to_specs = fields_by_tender_key()  # tender_key → list[FieldSpec]
    values: dict[str, ExtractionValue] = {}
    field_provenance = field_provenance or {}

    for tender_key, specs in tk_to_specs.items():
        raw_val = new_req.get(tender_key)
        source  = agv_criteria.get(f"{tender_key}_source")
        _prov   = field_provenance.get(tender_key) or {}
        _produced_by_val = _prov.get("produced_by")
        _nulled_by_val   = _prov.get("nulled_by")
        assert _produced_by_val is None or _produced_by_val in _PRODUCED_BY_VALUES, (
            f"build_tender_run: produced_by={_produced_by_val!r} for field "
            f"{tender_key!r} not in _PRODUCED_BY_VALUES {sorted(_PRODUCED_BY_VALUES)}"
        )
        assert _nulled_by_val is None or _nulled_by_val in _NULLED_BY_VALUES, (
            f"build_tender_run: nulled_by={_nulled_by_val!r} for field "
            f"{tender_key!r} not in _NULLED_BY_VALUES {sorted(_NULLED_BY_VALUES)}"
        )
        for spec in specs:
            values[spec.uuid] = ExtractionValue(
                spec        = spec,
                value       = raw_val,
                source      = source,
                produced_by = _produced_by_val,
                nulled_by   = _nulled_by_val,
                provenance  = _prov.get("provenance"),
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
            """
            INSERT OR REPLACE INTO tender_runs
                (run_id, source_file, captured_at, vehicle_type, in_scope, basic_info_json)
            VALUES
                (:run_id, :source_file, :captured_at, :vehicle_type, :in_scope, :basic_info_json)
            """,
            {
                "run_id": run.run_id,
                "source_file": run.source_file,
                "captured_at": run.captured_at,
                "vehicle_type": run.vehicle_type,
                "in_scope": int(run.in_scope),
                "basic_info_json": json.dumps(run.basic_info, ensure_ascii=False),
            },
        )
        con.execute(
            "DELETE FROM tender_extraction_values WHERE run_id = ?", (run.run_id,)
        )
        con.executemany(
            """
            INSERT INTO tender_extraction_values
                (run_id, field_uuid, value_json, source, spec_json,
                 produced_by, nulled_by, provenance_json)
            VALUES
                (:run_id, :field_uuid, :value_json, :source, :spec_json,
                 :produced_by, :nulled_by, :provenance_json)
            """,
            [
                {
                    "run_id": run.run_id,
                    "field_uuid": ev.spec.uuid if ev.spec else uuid_key,
                    "value_json": json.dumps(ev.value, ensure_ascii=False),
                    "source": ev.source,
                    "spec_json": json.dumps(dataclasses.asdict(ev.spec), ensure_ascii=False) if ev.spec else None,
                    "produced_by": ev.produced_by,
                    "nulled_by": ev.nulled_by,
                    "provenance_json": json.dumps(ev.provenance, ensure_ascii=False) if ev.provenance is not None else None,
                }
                for uuid_key, ev in run.values.items()
            ],
        )
        if match_results:
            con.execute("DELETE FROM tender_run_match_results WHERE run_id = ?", (run.run_id,))
            con.executemany(
                """
                INSERT INTO tender_run_match_results
                    (run_id, product_id, product_name, score,
                     disqualified, disqualified_by, score_details)
                VALUES
                    (:run_id, :product_id, :product_name, :score,
                     :disqualified, :disqualified_by, :score_details)
                """,
                [
                    {
                        "run_id": run.run_id,
                        "product_id": mr.record.product.product_id,
                        "product_name": mr.record.product.product_name,
                        "score": mr.score,
                        "disqualified": int(mr.disqualified),
                        "disqualified_by": json.dumps(mr.disqualified_by, ensure_ascii=False),
                        "score_details": json.dumps(mr.score_details, ensure_ascii=False),
                    }
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
            "SELECT field_uuid, value_json, source, spec_json, "
            "produced_by, nulled_by, provenance_json "
            "FROM tender_extraction_values WHERE run_id = ?",
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
            provenance = None
            if ev_row["provenance_json"]:
                try:
                    provenance = json.loads(ev_row["provenance_json"])
                except Exception:
                    pass  # malformed provenance blob — treat as absent

            values[uuid] = ExtractionValue(
                spec        = spec,
                value       = json.loads(ev_row["value_json"]) if ev_row["value_json"] is not None else None,
                source      = ev_row["source"],
                produced_by = ev_row["produced_by"],
                nulled_by   = ev_row["nulled_by"],
                # loose dict — never reconstructed into a typed object (see rationale above)
                provenance  = provenance,
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
