"""Tests for src/tender_store — round-trip integrity and contract validation."""
import json
import tempfile
from pathlib import Path
import pytest
from src.tender_store import init_db, build_tender_run, persist_tender_run, load_tender_run
from src.field_spec import load_fields, fields_by_tender_key
from src.json_repair import enforce_source_spans

# --- T-TR-01: Round-trip integrity ---
def test_T_TR_01_round_trip():
    """build → persist → load returns same values and basic_info. spec snapshot present."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        init_db(db)
        specs = fields_by_tender_key()
        # Build a minimal new_req with one known tender_key
        first_tk = next(iter(specs))
        new_req = {first_tk: 42.0, f"{first_tk}_source": "line 3: 42 kg"}
        result = {"buyer": "Acme GmbH", "project_name": "Test", "in_scope": True}
        run = build_tender_run("run-001", "test.pdf", new_req, new_req, result, "Forklift AGV", True)
        persist_tender_run(run, db_path=db)
        loaded = load_tender_run("run-001", db)
        assert loaded is not None
        assert loaded.run_id == "run-001"
        assert loaded.vehicle_type == "Forklift AGV"
        assert loaded.basic_info["buyer"] == "Acme GmbH"
        # Find the ExtractionValue for our tender_key
        uuid = specs[first_tk][0].uuid
        assert loaded.values[uuid].value == 42.0
        assert loaded.values[uuid].source == "line 3: 42 kg"
        # spec snapshot present and correct
        assert loaded.values[uuid].spec is not None
        assert loaded.values[uuid].spec.uuid == uuid

# --- T-TR-02: Orphaned UUID tolerance ---
def test_T_TR_02_orphaned_uuid_loads_gracefully():
    """load_tender_run handles UUIDs not in current fields.json without raising. spec is None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        init_db(db)
        import sqlite3
        con = sqlite3.connect(db)
        con.execute(
            "INSERT INTO tender_runs "
            "(run_id, source_file, captured_at, vehicle_type, in_scope, basic_info_json) "
            "VALUES (?,?,?,?,?,?)",
            ("run-orphan", "f.pdf", "2026-01-01T00:00:00+00:00", None, 0, "{}"))
        con.execute(
            "INSERT INTO tender_extraction_values "
            "(run_id, field_uuid, value_json, source, spec_json) "
            "VALUES (?,?,?,?,?)",
            ("run-orphan", "deadbeef-0000-0000-0000-000000000000", "99.0", None, None))
        con.commit()
        con.close()
        loaded = load_tender_run("run-orphan", db)
        assert loaded is not None
        assert "deadbeef-0000-0000-0000-000000000000" in loaded.values
        assert loaded.values["deadbeef-0000-0000-0000-000000000000"].value == 99.0
        assert loaded.values["deadbeef-0000-0000-0000-000000000000"].spec is None

# --- T-TR-03: basic_info key stability ---
def test_T_TR_03_basic_info_allowlist():
    """build_tender_run only copies allowlisted keys into basic_info."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        init_db(db)
        dirty_result = {
            "buyer": "Acme", "project_name": "P1", "in_scope": True,
            "_parse_method": "json",          # internal key — must NOT appear
            "agv_criteria": {"x": 1},         # internal key — must NOT appear
            "matches": [],                     # internal key — must NOT appear
        }
        run = build_tender_run("run-002", "f.pdf", {}, {}, dirty_result, None, True)
        assert "_parse_method" not in run.basic_info
        assert "agv_criteria" not in run.basic_info
        assert "matches" not in run.basic_info
        assert run.basic_info["buyer"] == "Acme"

# --- T-TR-04: vehicle_type not used for config lookup in load ---
def test_T_TR_04_load_does_not_use_vehicle_type_for_config():
    """load_tender_run returns vehicle_type as a plain string — not used to look up AP0/vt_map."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        init_db(db)
        run = build_tender_run("run-003", "f.pdf", {}, {}, {}, "Forklift AGV", False)
        persist_tender_run(run, db_path=db)
        loaded = load_tender_run("run-003", db)
        # vehicle_type is a plain string — not transformed, not looked up
        assert loaded.vehicle_type == "Forklift AGV"
        assert isinstance(loaded.vehicle_type, str)


# --- T-TR-05: match results persist without crashing ---
def test_T_TR_05_match_results_persist():
    """persist_tender_run(run, match_results=...) writes to tender_run_match_results without error."""
    import sqlite3
    from unittest.mock import MagicMock
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        init_db(db)
        run = build_tender_run("run-004", "f.pdf", {}, {}, {}, "Forklift AGV", True)
        # Minimal mock MatchResult
        mr = MagicMock()
        mr.record.product.product_id = "prod-1"
        mr.record.product.product_name = "TestProduct"
        mr.score = 42
        mr.disqualified = False
        mr.disqualified_by = []
        mr.score_details = [{"field": "navigation_type", "points": 5, "value": "SLAM"}]
        persist_tender_run(run, match_results=[mr], db_path=db)
        # Verify row written
        con = sqlite3.connect(db)
        row = con.execute(
            "SELECT * FROM tender_run_match_results WHERE run_id = ?", ("run-004",)
        ).fetchone()
        con.close()
        assert row is not None
        assert row[1] == "prod-1"
        assert row[3] == 42


# --- T-TR-06 (D1 acceptance): 4b hint-echo source, 4c abstains, L2 nulls it —
# full pipeline-mechanics path persists produced_by="4b", nulled_by="L2", and
# provenance_json with the pre-null raw value/source. ---
def test_T_TR_06_d1_l2_hint_echo_provenance_persists():
    """Fixture reproduces the CompanyX-style failure mode: Pass 4b fabricates a
    field's source by echoing generic descriptive prose (not a real document
    quote) instead of citing the document; Pass 4c abstains on the same field;
    Layer 2 then nulls the value because the fabricated source contains no
    digit confirming it numerically. This drives the exact same production
    functions (enforce_source_spans, build_tender_run, persist_tender_run,
    load_tender_run) the live pipeline uses — only the Ollama calls are
    replaced by fixture data, per the D1 acceptance-test allowance.
    """
    tender_key = "required_max_payload_kg"

    # Real document text: the actual number appears, unrelated to the fabricated quote.
    document_text = "Maximum payload 4800 kg specified for heavy duty operation onsite."

    # Pass 4b's fabricated value + hint-echoed source (generic descriptive prose,
    # not a verbatim document quote — no digit anywhere in it).
    fabricated_value = 4.8
    hint_echo_source = (
        "The maximum permissible payload capacity of the vehicle, expressed in "
        "kilograms, describing the heaviest load the AGV can carry during operation."
    )

    agv_criteria = {
        tender_key: fabricated_value,
        f"{tender_key}_source": hint_echo_source,
    }

    # D1 step (a): pre-4c snapshot (what 4b produced, before 4c/guard can touch it).
    pre_4c_snapshot = {
        tender_key: (agv_criteria[tender_key], agv_criteria[f"{tender_key}_source"]),
    }
    produced_by = {tender_key: "4b"}

    # D1 step (b): Pass 4c abstains explicitly (returned null for this field).
    four_c_abstained = {tender_key}
    four_c_state = {tender_key: "explicit_null"}

    # Source-span guard: L1 (source present) and L0 (grounded — "payload"/"operation"/
    # "maximum" co-locate with the anchored "4800" in the document) both pass; L2 fires
    # because the fabricated source has no digit confirming 4.8/4800/0.0048.
    agv_criteria, messages, events = enforce_source_spans(
        dict(agv_criteria), document_text, {tender_key}, four_c_abstained
    )
    assert agv_criteria[tender_key] is None, "L2 must null the fabricated value in this fixture"
    assert len(events) == 1 and events[0].field == tender_key and events[0].layer == "L2"

    # D1 step (c): attribute the null to its guard layer.
    nulled_by = {ev.field: ev.layer for ev in events}

    # D1 step (e): assemble the per-field provenance dict as app.py does.
    raw_value, raw_source = pre_4c_snapshot[tender_key]
    field_provenance = {
        tender_key: {
            "produced_by": produced_by.get(tender_key),
            "nulled_by": nulled_by.get(tender_key),
            "provenance": {
                "raw_value": raw_value,
                "raw_source": raw_source,
                "pass_4c_state": four_c_state.get(tender_key),
                "notes": None,
            },
        }
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        init_db(db)
        new_req = dict(agv_criteria)
        run = build_tender_run(
            run_id="run-d1-acceptance",
            source_file="CompanyX.pdf",
            new_req=new_req,
            agv_criteria=agv_criteria,
            result={"buyer": "CompanyX", "in_scope": True},
            vehicle_type="Forklift AGV",
            in_scope=True,
            field_provenance=field_provenance,
        )
        persist_tender_run(run, db_path=db)
        loaded = load_tender_run("run-d1-acceptance", db)

        uuid = fields_by_tender_key()[tender_key][0].uuid
        ev = loaded.values[uuid]
        assert ev.value is None, "the field itself is null after L2 (matching engine sees blank, not zero)"
        assert ev.produced_by == "4b"
        assert ev.nulled_by == "L2"
        assert ev.provenance is not None
        assert ev.provenance["raw_value"] == fabricated_value
        assert ev.provenance["raw_source"] == hint_echo_source
        assert ev.provenance["pass_4c_state"] == "explicit_null"
