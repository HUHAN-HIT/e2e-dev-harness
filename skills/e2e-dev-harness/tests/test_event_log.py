"""Task 5: tamper-evident event log + projection replay (UNWIRED seam).

These exercise the seam in isolation; nothing here touches `run_state.mutate`.
The two core cases (modification, reordering) come straight from the plan; the
deletion and replay cases cover the design's Phase 4 exit criteria
(detect modification/deletion/reordering; replay reconstructs key fields).
"""
from e2e_harness.core import event_log, state_store


def test_event_log_detects_modified_event(tmp_path):
    path = tmp_path / "events.jsonl"
    first = event_log.append_event(path, {"type": "run.started", "run_id": "r1"})
    second = event_log.append_event(path, {"type": "gate.passed", "run_id": "r1", "phase": "CLARIFIED"})
    assert first["event_hash"]
    assert second["prev_event_hash"] == first["event_hash"]
    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = lines[1].replace("gate.passed", "gate.failed")
    path.write_text(lines[0] + "\n" + tampered + "\n", encoding="utf-8")
    ok, reason = event_log.verify_chain(path)
    assert not ok
    assert reason == "event-hash-mismatch:2"


def test_event_log_detects_reordered_event(tmp_path):
    path = tmp_path / "events.jsonl"
    event_log.append_event(path, {"type": "run.started", "run_id": "r1"})
    event_log.append_event(path, {"type": "phase.submitted", "run_id": "r1", "phase": "CLARIFIED"})
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text(lines[1] + "\n" + lines[0] + "\n", encoding="utf-8")
    ok, reason = event_log.verify_chain(path)
    assert not ok
    assert reason.startswith("event-chain-broken")


def test_event_log_detects_middle_deletion(tmp_path):
    path = tmp_path / "events.jsonl"
    event_log.append_event(path, {"type": "run.started", "run_id": "r1"})
    event_log.append_event(path, {"type": "phase.submitted", "run_id": "r1", "phase": "CLARIFIED"})
    event_log.append_event(path, {"type": "gate.passed", "run_id": "r1", "phase": "CLARIFIED"})
    lines = path.read_text(encoding="utf-8").splitlines()
    # Drop the MIDDLE event -> the survivor's prev_event_hash no longer chains.
    path.write_text(lines[0] + "\n" + lines[2] + "\n", encoding="utf-8")
    ok, reason = event_log.verify_chain(path)
    assert not ok
    assert reason.startswith("event-chain-broken")


def test_event_log_tail_truncation_is_a_known_undetected_gap(tmp_path):
    """KNOWN LIMITATION (pinned, not endorsed): a pure in-file forward hash chain
    has no head/length anchor, so dropping the TRAILING event(s) leaves a
    self-consistent prefix that verify_chain accepts. The same is true for
    re-hashing the LAST event. Full tail tamper-evidence needs the deferred
    projection-drift cross-check (design Phase 4). This test characterizes the
    boundary so a future fix flips it deliberately rather than by accident."""
    path = tmp_path / "events.jsonl"
    event_log.append_event(path, {"type": "run.started", "run_id": "r1"})
    event_log.append_event(path, {"type": "gate.passed", "run_id": "r1", "phase": "CLARIFIED"})
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text(lines[0] + "\n", encoding="utf-8")  # drop the LAST event
    ok, reason = event_log.verify_chain(path)
    assert ok is True
    assert reason is None


def test_event_log_accepts_intact_chain(tmp_path):
    path = tmp_path / "events.jsonl"
    event_log.append_event(path, {"type": "run.started", "run_id": "r1"})
    event_log.append_event(path, {"type": "phase.submitted", "run_id": "r1", "phase": "CLARIFIED"})
    ok, reason = event_log.verify_chain(path)
    assert ok
    assert reason is None


def test_state_store_replays_key_fields(tmp_path):
    path = tmp_path / "events.jsonl"
    event_log.append_event(path, {"type": "run.started", "run_id": "r1"})
    event_log.append_event(path, {"type": "phase.submitted", "run_id": "r1", "phase": "IMPLEMENTED"})
    event_log.append_event(path, {"type": "gate.passed", "run_id": "r1", "phase": "IMPLEMENTED"})
    projected = state_store.replay_events(event_log.read_events(path))
    assert projected["run_id"] == "r1"
    assert projected["current_phase"] == "IMPLEMENTED"
    assert projected["phases"]["IMPLEMENTED"]["dispatch"] == "done"


def test_state_store_replays_gate_failed(tmp_path):
    path = tmp_path / "events.jsonl"
    event_log.append_event(path, {"type": "run.started", "run_id": "r1"})
    event_log.append_event(path, {"type": "phase.submitted", "run_id": "r1", "phase": "IMPLEMENTED"})
    event_log.append_event(path, {"type": "gate.failed", "run_id": "r1", "phase": "IMPLEMENTED", "reason": "tests red"})
    projected = state_store.replay_events(event_log.read_events(path))
    assert projected["phases"]["IMPLEMENTED"]["dispatch"] == "failed"
    assert projected["phases"]["IMPLEMENTED"]["blocker"] == "tests red"
