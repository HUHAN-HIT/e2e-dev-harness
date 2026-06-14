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
import os
import time


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


def test_mutate_recovers_stale_lock_file(tmp_path, monkeypatch):
    p = tmp_path / "run-state.json"
    run_state.save(p, run_state.new_run_state("r1", "feat", "req"))
    lock = tmp_path / "run-state.json.lock"
    lock.write_text('{"pid": 999999, "hostname": "old", "timestamp": "old"}',
                    encoding="utf-8")
    old = time.time() - 60
    os.utime(lock, (old, old))
    monkeypatch.setattr(run_state, "_LOCK_TIMEOUT_S", 0.2)
    monkeypatch.setattr(run_state, "_LOCK_STALE_S", 0.01, raising=False)

    run_state.mutate(p, lambda s: s.__setitem__("feature", "recovered"))

    assert run_state.load(p)["feature"] == "recovered"
    assert not lock.exists()


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


# --- Slice 1: events_path_for centralizes the sibling-path convention ----------
# Recovery, start, and the four forward commands must agree on ONE location for
# the chained log: <run_dir>/events.jsonl, next to run-state.json.


def test_events_path_for_is_run_dir_sibling(tmp_path):
    sp = tmp_path / "docs" / "agent-runs" / "r1" / "run-state.json"
    assert run_state.events_path_for(sp) == sp.parent / "events.jsonl"


def test_events_path_for_accepts_str(tmp_path):
    """The CLI passes args.state as a str; the helper must accept it."""
    sp = tmp_path / "run-state.json"
    assert run_state.events_path_for(str(sp)) == tmp_path / "events.jsonl"


# --- Slice 1.5: witness write-failure is loud and attributed (R4) -------------
# `save` then derive+append are NOT atomic. A post-save append failure must NOT
# veto the authoritative write; instead it leaves a `events.jsonl.write-failed`
# sentinel naming the cause, warns on stderr, and swallows the exception so the
# command reports the success that actually committed.


def test_write_failed_path_for_is_events_sibling(tmp_path):
    ev = tmp_path / "events.jsonl"
    assert run_state.write_failed_path_for(ev) == tmp_path / "events.jsonl.write-failed"


def test_mutate_witness_failure_does_not_roll_back_save(tmp_path, monkeypatch, capsys):
    from e2e_harness.core import event_log
    p = tmp_path / "run-state.json"
    events = tmp_path / "events.jsonl"
    run_state.save(p, run_state.new_run_state("r1", "feat", "req"))

    def boom(path, payload):
        raise OSError("disk full")
    monkeypatch.setattr(event_log, "append_event", boom)

    # The authority must commit despite the witness failure (no exception out).
    saved = run_state.mutate(
        p, lambda s: s.__setitem__("current_phase", "CLARIFIED"), events_path=events)
    assert saved["current_phase"] == "CLARIFIED"
    assert run_state.load(p)["current_phase"] == "CLARIFIED"   # persisted, not rolled back

    # Attribution: a sentinel names run_id, the failed event type, sequence, reason.
    sentinel = tmp_path / "events.jsonl.write-failed"
    assert sentinel.exists()
    rec = json.loads(sentinel.read_text(encoding="utf-8"))
    assert rec["run_id"] == "r1"
    assert rec["type"] == "phase.submitted"      # current_phase advance -> phase.submitted
    assert rec["expected_sequence"] == 1
    assert "disk full" in rec["reason"]

    # Loud: a warning surfaced on stderr.
    assert "witness" in capsys.readouterr().err.lower()


def test_mutate_witness_success_writes_no_sentinel(tmp_path):
    """The sentinel is ONLY for failure: a healthy append leaves no .write-failed."""
    p = tmp_path / "run-state.json"
    events = tmp_path / "events.jsonl"
    run_state.save(p, run_state.new_run_state("r1", "feat", "req"))
    run_state.mutate(p, lambda s: s.__setitem__("current_phase", "CLARIFIED"), events_path=events)
    assert not (tmp_path / "events.jsonl.write-failed").exists()


def test_run_state_bytes_identical_with_and_without_events(tmp_path):
    """G4 / acceptance #4: emission is purely additive — run-state.json's OWN bytes
    are identical whether or not the witness is active; the only difference is the
    sibling events.jsonl that the active run also writes."""
    def build(dirname, active):
        d = tmp_path / dirname
        d.mkdir()
        p = d / "run-state.json"
        run_state.save(p, run_state.new_run_state("r1", "feat", "req",
                                                  now="20260613T000000Z"))
        ev = run_state.events_path_for(p) if active else None
        run_state.mutate(p, lambda s: s.__setitem__("current_phase", "CLARIFIED"),
                         now="20260613T010101Z", events_path=ev)
        return p.read_bytes()

    with_events = build("with", True)
    without_events = build("without", False)
    assert with_events == without_events
    assert run_state.events_path_for(tmp_path / "with" / "run-state.json").exists()
    assert not run_state.events_path_for(tmp_path / "without" / "run-state.json").exists()


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


# --- D4: stale-lock staleness uses same-host pid liveness, not mtime alone -----
# `_lock_is_stale` must never reclaim a lock whose recorded pid is a live process
# on this host (protecting a holder stalled mid-mutation), while still reclaiming a
# dead holder past the mtime backstop and falling back to mtime cross-host.
import socket as _socket_for_lock_tests


def test_lock_not_stale_when_holder_pid_alive(tmp_path, monkeypatch):
    lock = tmp_path / "run-state.json.lock"
    lock.write_text(json.dumps({"pid": os.getpid(),
                                "hostname": _socket_for_lock_tests.gethostname(),
                                "timestamp": "now"}), encoding="utf-8")
    old = time.time() - 10_000
    os.utime(lock, (old, old))
    monkeypatch.setattr(run_state, "_LOCK_STALE_S", 0.01, raising=False)
    assert run_state._lock_is_stale(lock) is False


def test_lock_stale_when_holder_pid_dead_and_mtime_old(tmp_path, monkeypatch):
    lock = tmp_path / "run-state.json.lock"
    lock.write_text(json.dumps({"pid": 999999,
                                "hostname": _socket_for_lock_tests.gethostname(),
                                "timestamp": "old"}), encoding="utf-8")
    old = time.time() - 10_000
    os.utime(lock, (old, old))
    monkeypatch.setattr(run_state, "_LOCK_STALE_S", 0.01, raising=False)
    assert run_state._lock_is_stale(lock) is True


def test_lock_cross_host_falls_back_to_mtime(tmp_path, monkeypatch):
    lock = tmp_path / "run-state.json.lock"
    lock.write_text(json.dumps({"pid": os.getpid(), "hostname": "some-other-host",
                                "timestamp": "old"}), encoding="utf-8")
    old = time.time() - 10_000
    os.utime(lock, (old, old))
    monkeypatch.setattr(run_state, "_LOCK_STALE_S", 0.01, raising=False)
    assert run_state._lock_is_stale(lock) is True
