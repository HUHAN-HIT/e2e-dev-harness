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
