from e2e_harness.core import lifecycle, navigation, run_state, engine
from e2e_harness import pipeline


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


def test_map_carries_per_phase_gate_summary():
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(_spine(), st)  # blocked at CLARIFIED, no evidence
    m = navigation.navigation_map(_spine(), st)
    clar = next(p for p in m["phases"] if p["name"] == "CLARIFIED")
    assert clar["gate"]["required"] == 2  # clarification + acceptance_contract (link ①)
    assert clar["gate"]["missing"] == ["clarification", "acceptance_contract"]
    assert clar["gate"]["ok"] is False


def test_map_reports_remaining_gates_to_goal():
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(_spine(), st)
    m = navigation.navigation_map(_spine(), st)
    # CLARIFIED(2) + RED(1) + IMPLEMENTED(1) + VERIFIED(1) = 5 unmet gate keys ahead
    assert m["remaining_gates"] == 5


def test_map_frames_next_action_inside_map():
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(_spine(), st)
    m = navigation.navigation_map(_spine(), st)
    assert m["next"]["phase"] == "CLARIFIED"
    assert "e2e-harness-clarification" in m["next"]["action"]


def test_map_next_is_null_when_complete(tmp_path):
    import json, sys
    from e2e_harness.adapters.evidence import command_evidence as ce, validate
    st = run_state.new_run_state("r1", "f", "r")
    spine = _spine()
    base = tmp_path / "art"; base.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        res = engine.evaluate(spine, st, tmp_path)
        if res["complete"]:
            break
        ph = next(p for p in spine if p.name == res["blocked_phase"])
        for key in ph.produces:
            if key == "acceptance_contract":
                from e2e_harness.core import acceptance as _acc
                f = base / f"{ph.name}-{key}.json"
                f.write_text(json.dumps({"schema": _acc.SCHEMA, "items": [
                    {"id": "AC-001", "criterion": "demo",
                     "observable_behavior": "demo behaviour"}]}), encoding="utf-8")
                engine.submit_evidence(st, ph.name, key, str(f), repo_root=tmp_path)
                continue
            want = validate.COMMAND_KEYS.get(key)  # incl. verification (zero exit)
            if want is not None:
                code = 0 if want == "zero" else 1
                f = base / f"{ph.name}-{key}.json"
                f.write_text(json.dumps(ce.record_command(tmp_path, f'"{sys.executable}" -c "import sys; sys.exit({code})"')), encoding="utf-8")
            else:
                f = base / f"{ph.name}-{key}.md"; f.write_text("real", encoding="utf-8")
            engine.submit_evidence(st, ph.name, key, str(f), repo_root=tmp_path)
    m = navigation.navigation_map(spine, st, tmp_path)
    assert m["next"] is None
