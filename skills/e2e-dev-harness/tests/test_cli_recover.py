"""F-1: approval-gated `recover` (design Phase 3).

`recover --plan` is read-only and emits an auditable recovery plan;
`recover --apply --approval <path>` performs ONE narrow, approved control-plane
repair — registering a genuine, human-supplied worker artifact to unstick a run —
records input/output hashes, refuses to fabricate (a missing artifact stays
missing), and is the ONLY path that flips coordinator_may_write_worker_outputs to
True. It never bypasses validators: the registered evidence still faces the gate.
"""
import hashlib
import json
from types import SimpleNamespace

from e2e_harness.cli.commands import recover
from e2e_harness.core import event_log, run_state


def _blocked_state(tmp_path):
    p = tmp_path / "run-state.json"
    state = run_state.new_run_state("r1", "feat", "req")
    state["current_phase"] = "IMPLEMENTED"
    state["phases"] = {"IMPLEMENTED": {"evidence": {}}}
    run_state.save(p, state)
    return p


def _approval(tmp_path, **over):
    obj = {
        "schema": "e2e-dev-harness.recovery-approval.v1",
        "approved": True,
        "coordinator_may_write_worker_outputs": True,
        "phase": "IMPLEMENTED",
        "key": "passing_tests",
        "evidence_path": "handoffs/passing.json",
        "approver": "user",
        "reason": "genuine worker output recovered after a crash",
    }
    obj.update(over)
    ap = tmp_path / "approval.json"
    ap.write_text(json.dumps(obj), encoding="utf-8")
    return ap


def test_recover_plan_is_read_only_and_emits_plan(tmp_path):
    p = _blocked_state(tmp_path)
    before = p.read_bytes()
    args = SimpleNamespace(state=str(p), repo=str(tmp_path), plan=True, apply=False, approval=None)
    code, payload = recover.run(args)
    assert code == 0
    assert payload["schema"] == "e2e-dev-harness.recovery-plan.v1"
    assert payload["requires_approval"] is True
    assert payload["coordinator_may_write_worker_outputs"] is False
    assert payload["blocked_phase"] == "IMPLEMENTED"
    assert "passing_tests" in payload["proposed_repair"]["evidence_keys"]
    assert payload["input_hashes"]["run_state"] == hashlib.sha256(before).hexdigest()
    # READ-ONLY: --plan must not mutate the run-state or emit events.
    assert p.read_bytes() == before
    assert not (tmp_path / "events.jsonl").exists()


def test_recover_apply_refuses_without_approval(tmp_path):
    p = _blocked_state(tmp_path)
    before = p.read_bytes()
    args = SimpleNamespace(state=str(p), repo=str(tmp_path), plan=False, apply=True, approval=None)
    code, payload = recover.run(args)
    assert code == 2
    assert "approval" in payload["error"].lower()
    assert p.read_bytes() == before  # no mutation without approval


def test_recover_apply_refuses_unapproved_approval_file(tmp_path):
    """An approval that does not actually grant the worker-output write must be
    refused — recover is the gate, not a rubber stamp."""
    p = _blocked_state(tmp_path)
    before = p.read_bytes()
    ap = _approval(tmp_path, coordinator_may_write_worker_outputs=False)
    args = SimpleNamespace(state=str(p), repo=str(tmp_path), plan=False, apply=True, approval=str(ap))
    code, payload = recover.run(args)
    assert code == 2
    assert "approv" in payload["error"].lower()
    assert p.read_bytes() == before


def test_recover_apply_refuses_to_fabricate_missing_evidence(tmp_path):
    """Recovery must not turn a MISSING artifact into a passing state: if the
    approved evidence file does not exist, refuse and leave state untouched."""
    p = _blocked_state(tmp_path)
    before = p.read_bytes()
    ap = _approval(tmp_path, evidence_path="handoffs/does-not-exist.json")
    args = SimpleNamespace(state=str(p), repo=str(tmp_path), plan=False, apply=True, approval=str(ap))
    code, payload = recover.run(args)
    assert code == 2
    assert "evidence" in payload["error"].lower()
    assert p.read_bytes() == before  # nothing fabricated


def test_recover_apply_with_approval_registers_evidence_and_records_hashes(tmp_path):
    p = _blocked_state(tmp_path)
    (tmp_path / "handoffs").mkdir()
    (tmp_path / "handoffs" / "passing.json").write_text('{"ran": true}', encoding="utf-8")
    before = p.read_bytes()
    before_hash = hashlib.sha256(before).hexdigest()
    ap = _approval(tmp_path)
    args = SimpleNamespace(state=str(p), repo=str(tmp_path), plan=False, apply=True, approval=str(ap))
    code, payload = recover.run(args)
    assert code == 0
    assert payload["schema"] == "e2e-dev-harness.recovery-applied.v1"
    # recover is the ONLY gate that flips this True, and only under approval.
    assert payload["coordinator_may_write_worker_outputs"] is True
    assert payload["input_hashes"]["run_state"] == before_hash
    assert payload["output_hashes"]["run_state"] != before_hash  # state changed
    # the genuine artifact is now registered as evidence (still gated downstream).
    st = run_state.load(p)
    assert "passing_tests" in st["phases"]["IMPLEMENTED"]["evidence"]
    # audit trail: recovery events appended to the tamper-evident log, chain intact.
    events = event_log.read_events(tmp_path / "events.jsonl")
    types = [e["type"] for e in events]
    assert "recovery.applied" in types
    ok, reason = event_log.verify_chain(tmp_path / "events.jsonl")
    assert ok, reason


def test_doctor_after_recover_on_old_run_is_not_false_control_plane_drift(tmp_path):
    """Slice 3 interaction: an OLD run (no prior chain) recovered via apply gets a
    bootstrapped witness. The next doctor --state must NOT read it as
    control_plane_drift — the recovery audit events must anchor on a COMPLETE chain
    (run.started + current phase), else a recovery-only chain under-claims
    current_phase and false-blocks a legitimately-recovered run."""
    from types import SimpleNamespace
    from e2e_harness.cli.commands import doctor
    p = _blocked_state(tmp_path)
    (tmp_path / "handoffs").mkdir()
    (tmp_path / "handoffs" / "passing.json").write_text('{"ran": true}', encoding="utf-8")
    ap = _approval(tmp_path)
    code, _ = recover.run(SimpleNamespace(
        state=str(p), repo=str(tmp_path), plan=False, apply=True, approval=str(ap)))
    assert code == 0
    # the witness now exists; the chain must verify AND not drift vs run-state.
    ok, why = event_log.verify_chain(tmp_path / "events.jsonl")
    assert ok, why
    from e2e_harness.core import state_store
    ok, why = state_store.detect_drift(
        event_log.read_events(tmp_path / "events.jsonl"), run_state.load(p))
    assert ok, why
    dcode, dpayload = doctor.run(SimpleNamespace(
        project_root=str(tmp_path), runtime="claude", strict=False,
        state=str(p), repo=str(tmp_path)))
    # the run is still domain-blocked (test_substance missing) — that's fine — but it
    # must NOT be a control-plane fault from the recovery-bootstrapped chain.
    if dpayload["first_fault"]:
        assert dpayload["first_fault"]["kind"] not in (
            "control_plane_drift", "event_log_write_failed"), dpayload["first_fault"]
