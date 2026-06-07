from harness_v2.core import lifecycle, engine, run_state
from harness_v2 import pipeline


def _spine():
    return lifecycle.build_spine(pipeline.active_phase_names("minimal"))


def test_evaluate_auto_advances_created_then_blocks_on_clarified():
    st = run_state.new_run_state("r1", "f", "r")
    res = engine.evaluate(_spine(), st)
    assert st["current_phase"] == "CLARIFIED"
    assert res["complete"] is False
    assert res["blocked_phase"] == "CLARIFIED"
    assert res["next_action"]["skill"] == "e2e-harness-clarification"


def test_submit_then_evaluate_advances():
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(_spine(), st)
    engine.submit_evidence(st, "CLARIFIED", "clarification", "h1.md")
    engine.evaluate(_spine(), st)
    assert st["current_phase"] == "RED"


def test_full_run_terminates_at_verified_in_bounded_steps():
    spine = _spine()
    st = run_state.new_run_state("r1", "f", "r")
    steps = 0
    res = {"complete": False}
    while steps < 100:
        steps += 1
        res = engine.evaluate(spine, st)
        if res["complete"]:
            break
        ph = res["blocked_phase"]
        phase = next(p for p in spine if p.name == ph)
        for key in phase.produces:
            engine.submit_evidence(st, ph, key, f"{ph}-{key}.md")
    assert st["current_phase"] == "VERIFIED"
    assert res["complete"] is True
    assert steps <= len(spine) + 1


def test_evaluate_idempotent_after_complete():
    spine = _spine()
    st = run_state.new_run_state("r1", "f", "r")
    for _ in range(len(spine)):
        engine.evaluate(spine, st)
        phase = next(p for p in spine if p.name == st["current_phase"])
        for key in phase.produces:
            engine.submit_evidence(st, st["current_phase"], key, "e.md")
    res = engine.evaluate(spine, st)
    assert res["complete"] is True
    assert engine.evaluate(spine, st)["complete"] is True
