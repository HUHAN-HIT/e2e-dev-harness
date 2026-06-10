from e2e_harness.core import lifecycle
from e2e_harness import pipeline


def test_minimal_spine_order_and_links():
    spine = lifecycle.build_spine(pipeline.active_phase_names("minimal"))
    names = [p.name for p in spine]
    assert names == ["CREATED", "CLARIFIED", "RED", "IMPLEMENTED", "VERIFIED"]
    assert spine[0].next_phase == "CLARIFIED"
    assert spine[-1].next_phase is None


def test_created_phase_has_empty_gate():
    spine = lifecycle.build_spine(pipeline.active_phase_names("minimal"))
    assert spine[0].name == "CREATED"
    assert spine[0].exit_gate == ()


def test_clarified_phase_binds_worker_skill():
    spine = lifecycle.build_spine(pipeline.active_phase_names("minimal"))
    clar = next(p for p in spine if p.name == "CLARIFIED")
    assert clar.worker_skill == "e2e-harness-clarification"
    assert clar.exit_gate == ("clarification", "acceptance_contract")
    assert clar.produces == ("clarification", "acceptance_contract")
