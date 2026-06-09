from dataclasses import replace

from e2e_harness.core import lifecycle, gates
from e2e_harness import pipeline


def test_minimal_pipeline_is_gate_closed():
    spine = lifecycle.build_spine(pipeline.active_phase_names("minimal"))
    ok, unmet = gates.gate_closure_ok(spine)
    assert ok is True, f"unsatisfiable evidence: {unmet}"


def test_closure_detects_unproduced_evidence():
    spine = lifecycle.build_spine(pipeline.active_phase_names("minimal"))
    broken = list(spine)
    broken[1] = replace(broken[1], exit_gate=("clarification", "ghost"))
    ok, unmet = gates.gate_closure_ok(broken)
    assert ok is False
    assert "ghost" in unmet


def test_all_builtin_tiers_gate_closed():
    from e2e_harness import pipeline
    for tier in ("minimal", "standard", "critical", "audited"):
        spine = pipeline.build_spine(tier)
        ok, unmet = gates.gate_closure_ok(spine)
        assert ok is True, f"tier {tier} not gate-closed: {unmet}"
