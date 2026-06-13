"""OWN1: evidence namespace ownership guard in engine.submit_evidence.

Defense-in-depth (NOT an authorization boundary): when a namespaced worker_id is
available, a worker cannot submit evidence under a different module's namespace,
and a phase/key namespace disagreement is rejected outright. An adversarial worker
can still pass any worker_id; this only stops accidental cross-module mislabeling.
"""
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
