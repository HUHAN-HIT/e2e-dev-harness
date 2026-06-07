from harness_v2.core import lifecycle, navigation, run_state, engine
from harness_v2 import pipeline


def _spine():
    return lifecycle.build_spine(pipeline.active_phase_names("minimal"))


def test_map_shows_full_journey_and_goal():
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(_spine(), st)
    m = navigation.navigation_map(_spine(), st)
    assert [p["name"] for p in m["phases"]] == ["CREATED", "CLARIFIED", "RED", "IMPLEMENTED", "VERIFIED"]
    assert m["goal"] == "VERIFIED"
    assert m["you_are_here"] == "CLARIFIED"


def test_map_status_and_progress():
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(_spine(), st)
    m = navigation.navigation_map(_spine(), st)
    status = {p["name"]: p["status"] for p in m["phases"]}
    assert status["CREATED"] == "done"
    assert status["CLARIFIED"] == "current"
    assert status["RED"] == "pending"
    assert m["progress"] == "1/5"


def test_map_marks_skipped_phases():
    st = run_state.new_run_state("r1", "f", "r")
    m = navigation.navigation_map(_spine(), st)
    full = {p["name"]: p["status"] for p in m["full_catalog"]}
    assert full["PLANNED"] == "skipped"
    assert full["REVIEWED"] == "skipped"
