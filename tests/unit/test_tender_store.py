"""Tests for src/tender_store — round-trip integrity and contract validation."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from src.tender_store import (
    init_db, build_tender_run, persist_tender_run, load_tender_run, _basic_info_keys,
    read_run_criteria,
)
from src.field_spec import load_fields, fields_by_tender_key
from src.json_repair import enforce_source_spans
from app import _assemble_field_provenance, _attribute_nulls

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
        # OI-96: basic_info must never contain keys outside the AP0-derived allowlist —
        # a future silent basic_schema addition must surface here, not pass silently.
        # NOTE: this check is tautological (basic_info is built BY comprehending over
        # _basic_info_keys()); the real independent guard is T_TR_03c below.
        assert set(run.basic_info.keys()) <= _basic_info_keys()

# --- T-TR-03b: OI-96 — project_location and missing_info now persist ---
def test_T_TR_03b_project_location_and_missing_info_now_persist():
    """OI-96 intentional behavior change: project_location and missing_info are part
    of the AP0-derived basic_schema and must now appear in basic_info when present
    in the pipeline result (previously excluded by the old literal allowlist)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        init_db(db)
        result = {
            "buyer": "Acme",
            "project_location": "Munich, Germany",
            "missing_info": ["lifting_height_mm"],
        }
        run = build_tender_run("run-002b", "f.pdf", {}, {}, result, None, True)
        assert run.basic_info.get("project_location") == "Munich, Germany"
        assert run.basic_info.get("missing_info") == ["lifting_height_mm"]

# --- T-TR-03c: OI-96 real guard against silent basic_schema drift ---
def test_T_TR_03c_basic_info_keys_match_ap0_source():
    """OI-96 real guard: _basic_info_keys() must equal basic_schema keys (read
    independently, not via the production derivation) unioned with the known
    pipeline-meta keys — catches silent basic_schema drift that the tautological
    subset check in T_TR_03 cannot."""
    cfg_path = Path(__file__).parent.parent.parent / "config" / "nace_codes.json"
    cfg = json.loads(cfg_path.read_text())
    expected_schema_keys = frozenset(e["key"] for e in cfg["basic_schema"])
    expected = expected_schema_keys | frozenset({"detected_domain", "nace_tender", "in_scope"})
    assert _basic_info_keys() == expected

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

    domain_criteria = {
        tender_key: fabricated_value,
        f"{tender_key}_source": hint_echo_source,
    }

    # D1 step (a): pre-4c snapshot (what 4b produced, before 4c/guard can touch it).
    pre_4c_snapshot = {
        tender_key: (domain_criteria[tender_key], domain_criteria[f"{tender_key}_source"]),
    }
    produced_by = {tender_key: "4b"}

    # D1 step (b): Pass 4c abstains explicitly (returned null for this field).
    four_c_abstained = {tender_key}
    four_c_state = {tender_key: "explicit_null"}

    # Source-span guard: L1 (source present) and L0 (grounded — "payload"/"operation"/
    # "maximum" co-locate with the anchored "4800" in the document) both pass; L2 fires
    # because the fabricated source has no digit confirming 4.8/4800/0.0048.
    domain_criteria, messages, events = enforce_source_spans(
        dict(domain_criteria), document_text, {tender_key}, four_c_abstained
    )
    assert domain_criteria[tender_key] is None, "L2 must null the fabricated value in this fixture"
    assert len(events) == 1 and events[0].field == tender_key and events[0].layer == "L2"

    # D1 step (c): attribute the null to its guard layer, and (D1a/F3) capture
    # the actually-rejected (value, source) pair from the same SpanEvent.
    nulled_by = {ev.field: ev.layer for ev in events}
    rejected = {ev.field: (ev.value, ev.source) for ev in events}

    # D1a step (e): assemble the per-field provenance dict via the real,
    # module-level production function — no longer reimplemented inline here.
    field_provenance = _assemble_field_provenance(
        produced_by, nulled_by, rejected, pre_4c_snapshot, four_c_state
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        init_db(db)
        new_req = dict(domain_criteria)
        run = build_tender_run(
            run_id="run-d1-acceptance",
            source_file="CompanyX.pdf",
            new_req=new_req,
            domain_criteria=domain_criteria,
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
        # 4c abstained (never produced a value) in this fixture, so raw_value/raw_source
        # still equal the 4b snapshot — same numbers as pre_4c_value/pre_4c_source below.
        assert ev.provenance["raw_value"] == fabricated_value
        assert ev.provenance["raw_source"] == hint_echo_source
        assert ev.provenance["pre_4c_value"] == fabricated_value
        assert ev.provenance["pre_4c_source"] == hint_echo_source
        assert ev.provenance["pass_4c_state"] == "explicit_null"


# ── D1a: closed-vocabulary runtime enforcement (F1 / DoD 1) ──────────────────
def test_T_TR_07_build_tender_run_rejects_invalid_produced_by():
    """build_tender_run() must raise AssertionError for an out-of-vocabulary
    produced_by value — a typo must never silently persist (F1)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        init_db(db)
        specs = fields_by_tender_key()
        first_tk = next(iter(specs))
        field_provenance = {first_tk: {"produced_by": "typo_stage"}}
        with pytest.raises(AssertionError):
            build_tender_run(
                "run-bad-produced-by", "test.pdf", {}, {}, {}, "Forklift AGV", True,
                field_provenance=field_provenance,
            )


def test_T_TR_07b_build_tender_run_rejects_invalid_nulled_by():
    """build_tender_run() must raise AssertionError for an out-of-vocabulary
    nulled_by value (F1)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        init_db(db)
        specs = fields_by_tender_key()
        first_tk = next(iter(specs))
        field_provenance = {first_tk: {"nulled_by": "L99"}}
        with pytest.raises(AssertionError):
            build_tender_run(
                "run-bad-nulled-by", "test.pdf", {}, {}, {}, "Forklift AGV", True,
                field_provenance=field_provenance,
            )


def test_T_TR_07c_build_tender_run_accepts_existing_call_sites():
    """Confirms the new assertion does not break existing call sites: omitted
    field_provenance (→ None values) and in-vocabulary values must both pass."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        init_db(db)
        specs = fields_by_tender_key()
        first_tk = next(iter(specs))
        # No field_provenance at all — must not raise.
        build_tender_run("run-ok-1", "test.pdf", {}, {}, {}, "Forklift AGV", True)
        # In-vocabulary values — must not raise.
        build_tender_run(
            "run-ok-2", "test.pdf", {}, {}, {}, "Forklift AGV", True,
            field_provenance={first_tk: {"produced_by": "4b", "nulled_by": "L2"}},
        )


# ── D1a: "4a" and "replay" round-trip through persistence (F2 / DoD 2, 3) ────
def test_T_TR_08_produced_by_4a_round_trip():
    """A field tagged produced_by='4a' (required_product_type merge point, either
    the LLM-classification or the OI-107 single-leaf-shortcut sub-path) must
    round-trip through build_tender_run → persist_tender_run → load_tender_run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        init_db(db)
        specs = fields_by_tender_key()
        first_tk = next(iter(specs))
        field_provenance = _assemble_field_provenance(
            produced_by={first_tk: "4a"}, nulled_by={}, rejected={},
            pre_4c_snapshot={}, four_c_state={},
        )
        run = build_tender_run(
            "run-4a", "test.pdf", {first_tk: "Forklift AGV"}, {}, {}, "Forklift AGV", True,
            field_provenance=field_provenance,
        )
        persist_tender_run(run, db_path=db)
        loaded = load_tender_run("run-4a", db)
        uuid = specs[first_tk][0].uuid
        assert loaded.values[uuid].produced_by == "4a"


def test_T_TR_09_produced_by_replay_round_trip():
    """A replayed run's fields must persist produced_by='replay' end to end."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        init_db(db)
        specs = fields_by_tender_key()
        first_tk = next(iter(specs))
        field_provenance = _assemble_field_provenance(
            produced_by={first_tk: "replay"}, nulled_by={}, rejected={},
            pre_4c_snapshot={}, four_c_state={},
        )
        run = build_tender_run(
            "run-replay", "cached.json", {first_tk: "Forklift AGV"}, {}, {}, "Forklift AGV", True,
            field_provenance=field_provenance,
        )
        persist_tender_run(run, db_path=db)
        loaded = load_tender_run("run-replay", db)
        uuid = specs[first_tk][0].uuid
        assert loaded.values[uuid].produced_by == "replay"


# ── D1a: malformed provenance_json must not crash load_tender_run (F4 / DoD 7) ─
def test_T_TR_10_load_tender_run_malformed_provenance_json():
    """A malformed provenance_json blob must not raise — provenance falls back to None."""
    import sqlite3
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        init_db(db)
        con = sqlite3.connect(db)
        con.execute(
            "INSERT INTO tender_runs "
            "(run_id, source_file, captured_at, vehicle_type, in_scope, basic_info_json) "
            "VALUES (?,?,?,?,?,?)",
            ("run-bad-prov", "f.pdf", "2026-01-01T00:00:00+00:00", None, 0, "{}"))
        con.execute(
            "INSERT INTO tender_extraction_values "
            "(run_id, field_uuid, value_json, source, spec_json, provenance_json) "
            "VALUES (?,?,?,?,?,?)",
            ("run-bad-prov", "deadbeef-0000-0000-0000-000000000001", "1.0", None, None, "{not valid json"))
        con.commit()
        con.close()
        loaded = load_tender_run("run-bad-prov", db)
        assert loaded is not None
        assert loaded.values["deadbeef-0000-0000-0000-000000000001"].provenance is None


# ── D1a: _attribute_nulls() direct unit tests (test-coverage fix) ────────────
def test_T_TR_11_attribute_nulls_populates_sink_and_rejected():
    """A key that goes non-null → None is attributed in both sink and rejected,
    with rejected capturing (value, None) since neither validator has a source
    concept (F3)."""
    before = {"required_navigation_type": "BadValue"}
    after = {"required_navigation_type": None}
    sink: dict = {}
    rejected: dict = {}
    _attribute_nulls(before, after, "allowed_values", sink, rejected)
    assert sink == {"required_navigation_type": "allowed_values"}
    assert rejected == {"required_navigation_type": ("BadValue", None)}


def test_T_TR_12_attribute_nulls_excludes_source_and_underscore_prefixed_keys():
    """Keys ending in _source or starting with _ must never be attributed (F5)."""
    before = {
        "required_max_payload_kg_source": "some quote",
        "_internal_flag": "x",
        "required_max_payload_kg": 1000,
    }
    after = {
        "required_max_payload_kg_source": None,
        "_internal_flag": None,
        "required_max_payload_kg": None,
    }
    sink: dict = {}
    rejected: dict = {}
    _attribute_nulls(before, after, "plausibility", sink, rejected)
    assert sink == {"required_max_payload_kg": "plausibility"}
    assert rejected == {"required_max_payload_kg": (1000, None)}


def test_T_TR_13_attribute_nulls_setdefault_does_not_overwrite():
    """An earlier attribution for the same key must never be overwritten (both
    sink and rejected use setdefault semantics)."""
    before = {"required_max_payload_kg": 1000}
    after = {"required_max_payload_kg": None}
    sink = {"required_max_payload_kg": "L2"}
    rejected = {"required_max_payload_kg": (999, "earlier source")}
    _attribute_nulls(before, after, "plausibility", sink, rejected)
    assert sink == {"required_max_payload_kg": "L2"}
    assert rejected == {"required_max_payload_kg": (999, "earlier source")}


# ── D1a: _assemble_field_provenance() direct unit tests (test-coverage fix) ──
def test_T_TR_14_assemble_provenance_4c_override_then_rejected():
    """(a) 4c overrode 4b, then the guard rejected the 4c-produced value:
    raw_value/raw_source must reflect the 4c-rejected pair while
    pre_4c_value/pre_4c_source still show the original 4b data."""
    tk = "required_max_payload_kg"
    produced_by = {tk: "4c"}
    nulled_by = {tk: "L0"}
    rejected = {tk: (950, "4c fabricated quote")}
    pre_4c_snapshot = {tk: (1000, "4b original quote")}
    four_c_state = {tk: "returned_value"}

    result = _assemble_field_provenance(produced_by, nulled_by, rejected, pre_4c_snapshot, four_c_state)

    prov = result[tk]["provenance"]
    assert result[tk]["produced_by"] == "4c"
    assert result[tk]["nulled_by"] == "L0"
    assert prov["raw_value"] == 950
    assert prov["raw_source"] == "4c fabricated quote"
    assert prov["pre_4c_value"] == 1000
    assert prov["pre_4c_source"] == "4b original quote"
    assert prov["pass_4c_state"] == "returned_value"


def test_T_TR_15_assemble_provenance_allowed_values_rejection_populates_raw_value():
    """(b) A Dropdown/Multi-Select-style field rejected via 'allowed_values'
    (no numeric-KO pre_4c_snapshot entry, no source concept): raw_value must
    now be populated — previously (pre-D1a) it was always None for this path."""
    tk = "required_navigation_type"
    produced_by = {tk: "4b"}
    nulled_by = {tk: "allowed_values"}
    rejected = {tk: ("Teleporter", None)}   # no source concept for this validator
    pre_4c_snapshot: dict = {}               # not a numeric KO field — never snapshotted
    four_c_state: dict = {}

    result = _assemble_field_provenance(produced_by, nulled_by, rejected, pre_4c_snapshot, four_c_state)

    prov = result[tk]["provenance"]
    assert prov["raw_value"] == "Teleporter"
    assert prov["raw_source"] is None
    assert prov["pre_4c_value"] is None
    assert prov["pre_4c_source"] is None


def test_T_TR_16_assemble_provenance_replay_produced_by():
    """(c) A replay-sourced field must show produced_by == 'replay'."""
    tk = "required_max_payload_kg"
    produced_by = {tk: "replay"}

    result = _assemble_field_provenance(produced_by, nulled_by={}, rejected={},
                                         pre_4c_snapshot={}, four_c_state={})

    assert result[tk]["produced_by"] == "replay"


# --- T-TR-17 (OI-102): read_run_criteria old/new key alias ---
def test_T_TR_17_read_run_criteria_old_and_new_key_alias():
    """Old-format doc (agv_criteria) and new-format doc (domain_criteria) must
    replay to identical criteria via read_run_criteria()."""
    criteria = {"required_max_payload_kg": 500.0, "required_product_type": "Forklift AGV"}
    old_doc = {"agv_criteria": criteria}
    new_doc = {"domain_criteria": criteria}

    assert read_run_criteria(old_doc) == criteria
    assert read_run_criteria(new_doc) == criteria
    assert read_run_criteria(old_doc) == read_run_criteria(new_doc)
    assert read_run_criteria({}) == {}
