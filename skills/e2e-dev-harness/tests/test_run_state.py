def test_package_imports():
    import e2e_harness
    import e2e_harness.core
    assert e2e_harness is not None


from e2e_harness.core import run_state


def test_new_run_state_shape():
    st = run_state.new_run_state("r1", "feat", "req")
    assert st["schema"] == "e2e-dev-harness.run-state.v1"
    assert st["current_phase"] == "CREATED"
    assert st["tier"] == "minimal"
    assert st["pipeline"] == "minimal"
    assert st["phases"] == {}


def test_save_then_load_roundtrip(tmp_path):
    st = run_state.new_run_state("r1", "feat", "req")
    p = tmp_path / "run-state.json"
    run_state.save(p, st)
    loaded = run_state.load(p)
    assert loaded["run_id"] == "r1"
    assert loaded["current_phase"] == "CREATED"


def test_save_refreshes_updated_at(tmp_path):
    st = run_state.new_run_state("r1", "feat", "req", now="20260607T000000Z")
    p = tmp_path / "run-state.json"
    run_state.save(p, st, now="20260607T010101Z")
    assert run_state.load(p)["updated_at"] == "20260607T010101Z"


import json
import pytest
from pathlib import Path


def test_load_rejects_schema_mismatch(tmp_path):
    from e2e_harness.core import run_state
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"schema": "wrong", "run_id": "x"}), encoding="utf-8")
    with pytest.raises(ValueError) as ei:
        run_state.load(p)
    assert "schema" in str(ei.value)


def test_save_is_atomic_no_partial_on_replace(tmp_path):
    from e2e_harness.core import run_state
    st = run_state.new_run_state("r1", "feat", "req")
    p = tmp_path / "run-state.json"
    run_state.save(p, st)
    leftovers = [q.name for q in tmp_path.iterdir() if q.name != "run-state.json"]
    assert leftovers == []
    assert run_state.load(p)["run_id"] == "r1"


def test_domain_block_embedded_when_supplied():
    st = run_state.new_run_state("r", "f", "q",
        domain={"name": "frontend", "test_runner": "vitest", "review_profile": "frontend-default"})
    assert st["domain"]["name"] == "frontend"


def test_domain_absent_by_default_byte_identical():
    st = run_state.new_run_state("r", "f", "q")
    assert "domain" not in st   # parity: backend default adds no key


import threading


def test_mutate_atomic_under_concurrency(tmp_path):
    p = tmp_path / "run-state.json"
    st = run_state.new_run_state("r1", "feat", "req")
    st["phases"] = {"REVIEWED": {"evidence": {}}}
    run_state.save(p, st)

    def add_key(k):
        run_state.mutate(
            p, lambda s: s["phases"]["REVIEWED"]["evidence"].__setitem__(k, {"path": k})
        )

    keys = [f"r{i}_review" for i in range(20)]
    threads = [threading.Thread(target=add_key, args=(k,)) for k in keys]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ev = run_state.load(p)["phases"]["REVIEWED"]["evidence"]
    assert sorted(ev) == sorted(keys)  # zero lost updates


def test_mutate_releases_lock_and_persists(tmp_path):
    p = tmp_path / "run-state.json"
    run_state.save(p, run_state.new_run_state("r1", "feat", "req"))
    run_state.mutate(p, lambda s: s.__setitem__("feature", "feat2"))
    assert not (tmp_path / "run-state.json.lock").exists()
    assert run_state.load(p)["feature"] == "feat2"


# --- F-2 wiring: mutate is the single chokepoint of every mutating verb, so it
# is the event-log wiring point. Additive `events_path` param: default None is
# byte-identical to today (compatibility-projection Non-Goal); when supplied,
# mutate snapshots before->after and appends derive_events(...) to the chained
# log, so events become a tamper-evident projection of the same transition.


def test_mutate_with_events_path_appends_derived_chain(tmp_path):
    from e2e_harness.core import event_log, state_store
    p = tmp_path / "run-state.json"
    events = tmp_path / "events.jsonl"
    run_state.save(p, run_state.new_run_state("r1", "feat", "req"))

    def _advance(s):
        s["current_phase"] = "IMPLEMENTED"
        s.setdefault("phases", {})["IMPLEMENTED"] = {
            "dispatch": "done", "evidence": {"passing_tests": {"path": "x"}}}

    saved = run_state.mutate(p, _advance, events_path=events)

    ok, reason = event_log.verify_chain(events)
    assert ok, reason
    types = [e["type"] for e in event_log.read_events(events)]
    assert "phase.submitted" in types and "gate.passed" in types
    # The event projection reconstructs the same transition the run-state saved.
    projected = state_store.replay_events(event_log.read_events(events))
    assert projected["current_phase"] == saved["current_phase"] == "IMPLEMENTED"
    assert projected["phases"]["IMPLEMENTED"]["dispatch"] == "done"


def test_mutate_without_events_path_writes_no_sidecar(tmp_path):
    """Byte-compat floor: default mutate (no events_path) is unchanged — it leaves
    only run-state.json (lock released, tmp replaced), never an events sidecar."""
    p = tmp_path / "run-state.json"
    run_state.save(p, run_state.new_run_state("r1", "feat", "req"))
    run_state.mutate(p, lambda s: s.__setitem__("current_phase", "CLARIFIED"))
    leftovers = sorted(q.name for q in tmp_path.iterdir() if q.name != "run-state.json")
    assert leftovers == []


def test_submit_evidence_stamps_contract_when_gate_complete():
    """F2: submit_evidence stamps the contract-in-force only once the phase gate is
    complete, idempotently. The exit_gate parameter is OPTIONAL (default None ->
    no stamp), so every positional legacy caller is byte-identical."""
    from e2e_harness.core import engine
    st = run_state.new_run_state("r1", "f", "r")
    eg = ("plan", "module_plan")
    engine.submit_evidence(st, "PLANNED", "plan", "p.md", exit_gate=eg)
    assert "contract" not in st["phases"]["PLANNED"]          # gate not yet complete
    engine.submit_evidence(st, "PLANNED", "module_plan", "m.json", exit_gate=eg)
    assert st["phases"]["PLANNED"]["contract"]["exit_gate"] == ["plan", "module_plan"]
    # idempotent: a later submit with a DIFFERENT exit_gate must not overwrite.
    engine.submit_evidence(st, "PLANNED", "plan", "p2.md", exit_gate=("plan",))
    assert st["phases"]["PLANNED"]["contract"]["exit_gate"] == ["plan", "module_plan"]


def test_submit_evidence_without_exit_gate_writes_no_stamp():
    """F2 back-compat: no exit_gate => no contract key (legacy behavior preserved)."""
    from e2e_harness.core import engine
    st = run_state.new_run_state("r1", "f", "r")
    engine.submit_evidence(st, "PLANNED", "plan", "p.md")
    assert "contract" not in st["phases"]["PLANNED"]
