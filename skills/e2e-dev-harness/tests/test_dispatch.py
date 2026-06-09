from e2e_harness.core import lifecycle, dispatch
from e2e_harness import pipeline


def test_status_values():
    assert dispatch.DispatchStatus.PENDING.value == "pending"
    assert dispatch.DispatchStatus.DONE.value == "done"
    assert {s.value for s in dispatch.DispatchStatus} == {
        "pending", "dispatched", "running", "done", "failed"}


def test_worker_packet_is_pointer_only():
    spine = lifecycle.build_spine(pipeline.active_phase_names("minimal"))
    clar = next(p for p in spine if p.name == "CLARIFIED")
    packet = dispatch.worker_packet(clar, run_state_path="docs/agent-runs/r1/run-state.json")
    assert packet["role"] == "requirements-clarifier"
    assert packet["skill"] == "e2e-harness-clarification"
    assert packet["expected_outputs"] == ["clarification"]
    assert "docs/agent-runs/r1/run-state.json" in packet["context_paths"]
    assert "instructions" not in packet
