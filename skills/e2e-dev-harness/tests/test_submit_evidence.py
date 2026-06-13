"""OWN1: evidence namespace ownership guard in engine.submit_evidence.

Defense-in-depth (NOT an authorization boundary): when a namespaced worker_id is
available, a worker cannot submit evidence under a different module's namespace,
and a phase/key namespace disagreement is rejected outright. An adversarial worker
can still pass any worker_id; this only stops accidental cross-module mislabeling.
"""
import json
from types import SimpleNamespace

import pytest

from e2e_harness.cli.commands import submit
from e2e_harness.core import engine, run_state


def test_submit_evidence_rejects_cross_module_worker_claim():
    state = {}
    with pytest.raises(ValueError, match="worker-module-mismatch"):
        engine.submit_evidence(
            state, "IMPLEMENTED#billing", "passing_tests#billing",
            "handoffs/IMPLEMENTED-passing_tests.json",
            worker_id="IMPLEMENTED#auth",
        )


def test_submit_evidence_rejects_phase_key_module_mismatch():
    state = {}
    with pytest.raises(ValueError, match="phase-key-module-mismatch"):
        engine.submit_evidence(
            state, "IMPLEMENTED#billing", "passing_tests#auth", "handoffs/x.json",
        )


def test_submit_evidence_allows_matching_worker_namespace():
    state = {}
    engine.submit_evidence(
        state, "IMPLEMENTED#auth", "passing_tests#auth", "h.json",
        worker_id="IMPLEMENTED#auth",
    )
    assert "passing_tests#auth" in state["phases"]["IMPLEMENTED#auth"]["evidence"]


def test_submit_evidence_without_worker_id_is_backcompat():
    state = {}
    engine.submit_evidence(state, "IMPLEMENTED#auth", "passing_tests#auth", "h.json")
    assert "passing_tests#auth" in state["phases"]["IMPLEMENTED#auth"]["evidence"]


def test_submit_evidence_singleton_phase_unaffected():
    state = {}
    engine.submit_evidence(state, "VERIFIED", "scope_manifest", "s.json")
    assert "scope_manifest" in state["phases"]["VERIFIED"]["evidence"]


def test_submit_cli_forwards_worker_id(tmp_path):
    """The CLI must thread --worker-id into submit_evidence: a mismatched id raises
    (proving forwarding; without forwarding worker_id would default None and pass)."""
    sp = tmp_path / "run-state.json"
    run_state.save(sp, run_state.new_run_state("r1", "f", "req",
                                               tier="standard", pipeline="standard"))
    args = SimpleNamespace(state=str(sp), repo=str(tmp_path),
                           phase="IMPLEMENTED#billing", key="passing_tests#billing",
                           path="x.json", status="done", reason=None,
                           worker_id="IMPLEMENTED#auth")
    with pytest.raises(ValueError, match="worker-module-mismatch"):
        submit.run(args)


# --- F-5: trusted worker-identity binding (OWN1 -> authorization boundary) -----
# authorized_producers are the worker ids the HARNESS dispatched for this band
# (read from dispatch-invocation.v1 / agent-team-plan.json producer_ids), NOT the
# worker-self-reported worker_id. When a module fan-out was dispatched, a submit
# for a module namespace that was NEVER dispatched (a forged/phantom module) is
# rejected. Singleton / non-fanout / no-record flows are unaffected (the design's
# acknowledged residual: a manual / identity-less runtime degrades to anti-mislabel).


def test_submit_evidence_rejects_namespace_not_dispatched():
    state = {}
    with pytest.raises(ValueError, match="evidence-namespace-not-dispatched"):
        engine.submit_evidence(
            state, "IMPLEMENTED#payments", "passing_tests#payments", "h.json",
            authorized_producers=["IMPLEMENTED#auth", "IMPLEMENTED#billing"],
        )


def test_submit_evidence_accepts_dispatched_namespace():
    state = {}
    engine.submit_evidence(
        state, "IMPLEMENTED#auth", "passing_tests#auth", "h.json",
        authorized_producers=["IMPLEMENTED#auth", "IMPLEMENTED#billing"],
    )
    assert "passing_tests#auth" in state["phases"]["IMPLEMENTED#auth"]["evidence"]


def test_submit_evidence_singleton_unaffected_by_producers():
    """A singleton (non-namespaced) submit is never gated by the fan-out producer
    set — only module-namespaced submits against a fan-out are."""
    state = {}
    engine.submit_evidence(
        state, "VERIFIED", "scope_manifest", "s.json",
        authorized_producers=["IMPLEMENTED#auth", "IMPLEMENTED#billing"],
    )
    assert "scope_manifest" in state["phases"]["VERIFIED"]["evidence"]


def test_submit_evidence_no_producers_degrades_to_own1():
    state = {}
    engine.submit_evidence(state, "IMPLEMENTED#auth", "passing_tests#auth", "h.json")
    assert "passing_tests#auth" in state["phases"]["IMPLEMENTED#auth"]["evidence"]


def test_submit_cli_enforces_dispatched_producers(tmp_path):
    """End-to-end: submit resolves the trusted producer_ids from the on-disk
    agent-team-plan.json and rejects a never-dispatched module namespace."""
    sp = tmp_path / "run-state.json"
    run_state.save(sp, run_state.new_run_state("r1", "f", "req",
                                               tier="standard", pipeline="standard"))
    (tmp_path / "agent-team-plan.json").write_text(json.dumps({
        "schema": "e2e-dev-harness.agent-team-plan.v1",
        "phase": "IMPLEMENTED#auth",
        "workers": [{"id": "IMPLEMENTED#auth"}, {"id": "IMPLEMENTED#billing"}],
        "evidence_contract": {"producer_ids": ["IMPLEMENTED#auth", "IMPLEMENTED#billing"]},
    }), encoding="utf-8")
    args = SimpleNamespace(state=str(sp), repo=str(tmp_path),
                           phase="IMPLEMENTED#payments", key="passing_tests#payments",
                           path="x.json", status="done", reason=None, worker_id=None)
    with pytest.raises(ValueError, match="evidence-namespace-not-dispatched"):
        submit.run(args)
    # the run-state must be untouched: the lock released, no partial write.
    assert "IMPLEMENTED#payments" not in run_state.load(sp).get("phases", {})
