"""Task 5: tamper-evident event log + projection replay (UNWIRED seam).

These exercise the seam in isolation; nothing here touches `run_state.mutate`.
The two core cases (modification, reordering) come straight from the plan; the
deletion and replay cases cover the design's Phase 4 exit criteria
(detect modification/deletion/reordering; replay reconstructs key fields).
"""
import copy
import json

from e2e_harness.core import engine, event_log, run_state, state_store


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


def test_event_log_detects_tail_truncation_via_persisted_anchor(tmp_path):
    """F-3 (flipped from the pinned tail-gap characterization): a persisted
    external head/length anchor (`<path>.head`, written by append_event) closes
    the tail gap the self-anchored forward chain could not see. Dropping the
    TRAILING event leaves a self-consistent prefix, but its length no longer
    matches the anchor, so verify_chain now reports `event-chain-truncated:N`."""
    path = tmp_path / "events.jsonl"
    event_log.append_event(path, {"type": "run.started", "run_id": "r1"})
    event_log.append_event(path, {"type": "gate.passed", "run_id": "r1", "phase": "CLARIFIED"})
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text(lines[0] + "\n", encoding="utf-8")  # drop the LAST event
    ok, reason = event_log.verify_chain(path)
    assert ok is False
    assert reason == "event-chain-truncated:2"


def test_event_log_detects_last_event_rehash_via_anchor(tmp_path):
    """The other tail attack: editing the LAST event AND recomputing its
    event_hash keeps the forward chain self-consistent, so only the persisted
    tip anchor catches it — len matches but the recorded tip no longer does."""
    path = tmp_path / "events.jsonl"
    event_log.append_event(path, {"type": "run.started", "run_id": "r1"})
    second = event_log.append_event(path, {"type": "gate.passed", "run_id": "r1", "phase": "CLARIFIED"})
    lines = path.read_text(encoding="utf-8").splitlines()
    forged = json.loads(lines[1])
    forged["phase"] = "HIJACKED"
    forged.pop("event_hash")
    forged["event_hash"] = event_log._hash_event(forged)  # re-hash so forward chain passes
    path.write_text(lines[0] + "\n" + event_log._canonical(forged) + "\n", encoding="utf-8")
    ok, reason = event_log.verify_chain(path)
    assert ok is False
    assert reason == f"event-chain-tip-mismatch:{second['event_hash']}"


def test_verify_chain_accepts_and_rejects_explicit_external_anchor(tmp_path):
    """An explicit (truly external) anchor — held in a separate durable store, not
    the co-located .head sidecar — is honored too: matching anchor passes, a
    stale expected_len reports truncation."""
    path = tmp_path / "events.jsonl"
    event_log.append_event(path, {"type": "run.started", "run_id": "r1"})
    second = event_log.append_event(path, {"type": "gate.passed", "run_id": "r1", "phase": "CLARIFIED"})
    ok, reason = event_log.verify_chain(path, expected_len=2, expected_tip=second["event_hash"])
    assert ok is True and reason is None
    ok, reason = event_log.verify_chain(path, expected_len=3, expected_tip=second["event_hash"])
    assert ok is False
    assert reason == "event-chain-truncated:3"


def test_detect_drift_catches_truncate_then_append(tmp_path):
    """truncate-then-append survives verify_chain when the attacker also rewrites
    the .head sidecar, so the ultimate witness is projection drift: replay of the
    forged events disagrees with the independently-maintained run-state.json."""
    forged_events = [
        {"type": "run.started", "run_id": "r1"},
        {"type": "phase.submitted", "run_id": "r1", "phase": "IMPLEMENTED"},
    ]
    real_run_state = {"run_id": "r1", "current_phase": "REVIEWED", "phases": {}}
    ok, reason = state_store.detect_drift(forged_events, real_run_state)
    assert ok is False
    assert reason == "drift:current_phase"


def test_detect_drift_flags_dispatch_mismatch(tmp_path):
    events = [
        {"type": "run.started", "run_id": "r1"},
        {"type": "phase.submitted", "run_id": "r1", "phase": "IMPLEMENTED"},
        {"type": "gate.passed", "run_id": "r1", "phase": "IMPLEMENTED"},
    ]
    real = {"run_id": "r1", "current_phase": "IMPLEMENTED",
            "phases": {"IMPLEMENTED": {"dispatch": "failed"}}}
    ok, reason = state_store.detect_drift(events, real)
    assert ok is False
    assert reason == "drift:phases.IMPLEMENTED.dispatch"


def test_detect_drift_clean_when_projection_matches(tmp_path):
    events = [
        {"type": "run.started", "run_id": "r1"},
        {"type": "phase.submitted", "run_id": "r1", "phase": "IMPLEMENTED"},
        {"type": "gate.passed", "run_id": "r1", "phase": "IMPLEMENTED"},
    ]
    # run-state legitimately carries MORE than the narrow projection; drift only
    # checks the fields the projection actually claims.
    real = {"run_id": "r1", "current_phase": "IMPLEMENTED", "feature": "x",
            "phases": {"IMPLEMENTED": {"dispatch": "done", "evidence": {"passing_tests": {}}}}}
    ok, reason = state_store.detect_drift(events, real)
    assert ok is True
    assert reason is None


def test_detect_drift_catches_dropped_gate_event_under_claim(tmp_path):
    """F-3 residual closure (UNDER-CLAIM direction): a truncate-then-append that
    DROPS a trailing gate event leaves the replay SILENT on a per-phase dispatch
    that run-state still carries. The conflict-only check missed this — the
    projection simply omits the field, so nothing it claims disagrees — but the
    log has fallen behind real state, which is exactly the natural truncation."""
    forged_events = [
        {"type": "run.started", "run_id": "r1"},
        {"type": "phase.submitted", "run_id": "r1", "phase": "IMPLEMENTED"},
        # gate.passed for IMPLEMENTED dropped by the truncation
    ]
    real = {"run_id": "r1", "current_phase": "IMPLEMENTED",
            "phases": {"IMPLEMENTED": {"dispatch": "done"}}}
    ok, reason = state_store.detect_drift(forged_events, real)
    assert ok is False
    assert reason == "drift:phases.IMPLEMENTED.dispatch"


def test_detect_drift_catches_dropped_phase_submitted_under_claim(tmp_path):
    """Under-claim on current_phase: the log recorded run.started but the trailing
    phase.submitted was dropped, so the replay is silent on a current_phase that
    run-state asserts. run_id matches (no incidental drift:run_id), isolating the
    log-falls-behind miss the shipped test never exercised."""
    forged_events = [{"type": "run.started", "run_id": "r1"}]
    real = {"run_id": "r1", "current_phase": "IMPLEMENTED", "phases": {}}
    ok, reason = state_store.detect_drift(forged_events, real)
    assert ok is False
    assert reason == "drift:current_phase"


def test_detect_drift_silent_on_empty_log_does_not_false_positive(tmp_path):
    """The under-claim check must NOT fire on an EMPTY projection: a log that has
    recorded nothing yet (e.g. a run whose start bypassed event emission) asserts
    nothing, so there is nothing for it to have fallen behind on — it is a
    not-yet-recorded log, not a truncated one. Only once the projection has
    established the run does an omitted field count as drift."""
    real = {"run_id": "r1", "current_phase": "CREATED", "phases": {}}
    ok, reason = state_store.detect_drift([], real)
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


# --- F-2: side-effect-free event derivation layer (inverse of replay_events) --
# `derive_events(before, after)` turns the OPAQUE before/after run-state dicts a
# writer produces into the semantic event types `replay_events` dispatches on.
# It is the missing layer between `run_state.mutate` (which sees only a post-
# mutation dict, not an event type) and the authoritative event log. These tests
# feed it REAL write-path output (`new_run_state` + `engine.submit_evidence`) and
# prove the round-trip `replay(derive(...))` reconstructs the key fields, without
# touching `run_state.mutate` or the file/lock path.


def test_derive_run_started_and_initial_phase_from_empty(tmp_path):
    after = run_state.new_run_state("r1", "feat", "req")
    events = state_store.derive_events({}, after)
    types = [e["type"] for e in events]
    assert "run.started" in types
    started = next(e for e in events if e["type"] == "run.started")
    assert started["run_id"] == "r1"
    # current_phase went None -> CREATED, so a phase.submitted carries it.
    submitted = next(e for e in events if e["type"] == "phase.submitted")
    assert submitted["phase"] == "CREATED"


def test_derive_gate_passed_from_done_submit(tmp_path):
    before = {"run_id": "r1", "current_phase": "IMPLEMENTED", "phases": {}}
    after = copy.deepcopy(before)
    engine.submit_evidence(after, "IMPLEMENTED", "passing_tests", "handoffs/p.json")
    events = state_store.derive_events(before, after)
    assert [e["type"] for e in events] == ["gate.passed"]
    assert events[0]["phase"] == "IMPLEMENTED"
    assert events[0]["run_id"] == "r1"


def test_derive_gate_failed_carries_reason(tmp_path):
    before = {"run_id": "r1", "current_phase": "IMPLEMENTED", "phases": {}}
    after = copy.deepcopy(before)
    engine.submit_evidence(after, "IMPLEMENTED", "passing_tests",
                           "handoffs/p.json", status="failed", reason="tests are weak")
    events = state_store.derive_events(before, after)
    assert [e["type"] for e in events] == ["gate.failed"]
    assert events[0]["phase"] == "IMPLEMENTED"
    assert events[0]["reason"] == "tests are weak"


def test_derive_phase_submitted_on_current_phase_advance(tmp_path):
    before = {"run_id": "r1", "current_phase": "CLARIFIED", "phases": {}}
    after = {"run_id": "r1", "current_phase": "PLANNED", "phases": {}}
    events = state_store.derive_events(before, after)
    assert [e["type"] for e in events] == ["phase.submitted"]
    assert events[0]["phase"] == "PLANNED"


def test_derive_no_events_when_state_unchanged(tmp_path):
    state = run_state.new_run_state("r1", "feat", "req")
    engine.submit_evidence(state, "IMPLEMENTED", "passing_tests", "handoffs/p.json")
    assert state_store.derive_events(state, copy.deepcopy(state)) == []


def test_derive_then_replay_reconstructs_key_fields(tmp_path):
    """The F-2 invariant: events derived from a real mutation sequence, when
    replayed, reconstruct the key fields (run_id, current_phase, per-phase
    dispatch/blocker) — i.e. derive is the inverse of replay over the diff."""
    log: list[dict] = []

    def step(before, after):
        log.extend(state_store.derive_events(before, after))

    s0: dict = {}
    s1 = run_state.new_run_state("r1", "feat", "req")
    step(s0, s1)

    s2 = copy.deepcopy(s1)
    s2["current_phase"] = "IMPLEMENTED"
    engine.submit_evidence(s2, "IMPLEMENTED", "passing_tests", "handoffs/p.json")
    step(s1, s2)

    s3 = copy.deepcopy(s2)
    s3["current_phase"] = "REVIEWED"
    engine.submit_evidence(s3, "REVIEWED", "review", "handoffs/r.json",
                           status="failed", reason="needs rework")
    step(s2, s3)

    projected = state_store.replay_events(log)
    assert projected["run_id"] == "r1"
    assert projected["current_phase"] == "REVIEWED"
    assert projected["phases"]["IMPLEMENTED"]["dispatch"] == "done"
    assert projected["phases"]["REVIEWED"]["dispatch"] == "failed"
    assert projected["phases"]["REVIEWED"]["blocker"] == "needs rework"


# --- Slice 2: close the `dispatched` drift gap -------------------------------
# `detect_drift` COMPARES the per-phase `dispatch` field, but derive/replay only
# knew done/failed — so a phase sitting at `dispatched` (the `dispatch` verb's
# state) appeared in run-state yet never in the replayed chain => false drift the
# moment forward emission turned on. Closing it requires extending derive AND
# replay symmetrically so they stay strict inverses.


def test_derive_emits_dispatch_dispatched_on_transition(tmp_path):
    before = {"run_id": "r1", "current_phase": "IMPLEMENTED", "phases": {}}
    after = {"run_id": "r1", "current_phase": "IMPLEMENTED",
             "phases": {"IMPLEMENTED": {"dispatch": "dispatched"}}}
    events = state_store.derive_events(before, after)
    assert [e["type"] for e in events] == ["dispatch.dispatched"]
    assert events[0]["phase"] == "IMPLEMENTED"
    assert events[0]["run_id"] == "r1"


def test_replay_consumes_dispatch_dispatched(tmp_path):
    events = [
        {"type": "run.started", "run_id": "r1"},
        {"type": "dispatch.dispatched", "run_id": "r1", "phase": "IMPLEMENTED"},
    ]
    projected = state_store.replay_events(events)
    assert projected["phases"]["IMPLEMENTED"]["dispatch"] == "dispatched"


def test_dispatched_round_trips_derive_then_replay(tmp_path):
    """The strict-inverse invariant for the new value: replay(derive(diff))
    reproduces `dispatched`."""
    before = {"run_id": "r1", "current_phase": "IMPLEMENTED", "phases": {}}
    after = {"run_id": "r1", "current_phase": "IMPLEMENTED",
             "phases": {"IMPLEMENTED": {"dispatch": "dispatched"}}}
    projected = state_store.replay_events(state_store.derive_events(before, after))
    assert projected["phases"]["IMPLEMENTED"]["dispatch"] == "dispatched"


def test_dispatched_chain_yields_no_false_drift(tmp_path):
    """The whole point of Slice 2: a clean chain that recorded `dispatch.dispatched`
    replays to exactly the run-state a `dispatch` produced — no false
    `drift:phases.*.dispatch`. The chain reaches IMPLEMENTED via the normal
    phase.submitted advance first, exactly as a real run does before `dispatch`."""
    events = [
        {"type": "run.started", "run_id": "r1"},
        {"type": "phase.submitted", "run_id": "r1", "phase": "IMPLEMENTED"},
        {"type": "dispatch.dispatched", "run_id": "r1", "phase": "IMPLEMENTED"},
    ]
    real = {"run_id": "r1", "current_phase": "IMPLEMENTED",
            "phases": {"IMPLEMENTED": {"dispatch": "dispatched"}}}
    ok, reason = state_store.detect_drift(events, real)
    assert ok is True
    assert reason is None


def test_dispatched_in_runstate_without_event_still_drifts(tmp_path):
    """Guard the load-bearing-ness of the dispatch.dispatched event: drop it from
    the chain and the dispatched phase run-state still carries reads as under-claim
    drift — proving Slice 2's event is what closes the gap, not a relaxed check."""
    events = [
        {"type": "run.started", "run_id": "r1"},
        {"type": "phase.submitted", "run_id": "r1", "phase": "IMPLEMENTED"},
        # dispatch.dispatched dropped
    ]
    real = {"run_id": "r1", "current_phase": "IMPLEMENTED",
            "phases": {"IMPLEMENTED": {"dispatch": "dispatched"}}}
    ok, reason = state_store.detect_drift(events, real)
    assert ok is False
    assert reason == "drift:phases.IMPLEMENTED.dispatch"


def test_derive_emits_one_dispatch_event_per_phase_sorted(tmp_path):
    """A module-band `_mark_dispatched` sets several phase records at once; derive
    must emit one `dispatch.dispatched` per phase, in sorted (deterministic) order
    so the hash chain is reproducible."""
    before = {"run_id": "r1", "current_phase": "IMPLEMENTED#auth", "phases": {}}
    after = {"run_id": "r1", "current_phase": "IMPLEMENTED#auth", "phases": {
        "IMPLEMENTED#billing": {"dispatch": "dispatched"},
        "IMPLEMENTED#auth": {"dispatch": "dispatched"},
    }}
    events = state_store.derive_events(before, after)
    assert [(e["type"], e["phase"]) for e in events] == [
        ("dispatch.dispatched", "IMPLEMENTED#auth"),
        ("dispatch.dispatched", "IMPLEMENTED#billing"),
    ]
