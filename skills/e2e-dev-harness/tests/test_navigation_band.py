"""Navigation map gains region + per-track lanes; top-level shape preserved."""
import json

from e2e_harness import pipeline
from e2e_harness.core import navigation, run_state, engine, module_plan


def _mod(mid, deps=()):
    return {"id": mid, "name": f"{mid} svc", "depends_on": list(deps), "acceptance_ids": ["AC-001"]}


def _band_state(tmp_path, *mods):
    (tmp_path / "mp.json").write_text(
        json.dumps({"schema": module_plan.SCHEMA, "modules": list(mods)}), encoding="utf-8")
    (tmp_path / "plan.md").write_text("# plan\nreal", encoding="utf-8")
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")
    st["current_phase"] = "PLANNED"
    st["phases"] = {
        "CLARIFIED": {"evidence": {"clarification": {"path": "c"}, "acceptance_contract": {"path": "a"}}},
        "PLANNED": {"evidence": {"plan": {"path": "plan.md"}, "module_plan": {"path": "mp.json"}}},
    }
    spine = pipeline.spine_for_state(st, tmp_path)
    engine.evaluate(spine, st, tmp_path)  # fork into band
    return st, spine


def test_navigation_includes_region_and_track_lanes(tmp_path):
    st, spine = _band_state(tmp_path, _mod("auth"), _mod("billing", deps=["auth"]))
    m = navigation.navigation_map(spine, st, tmp_path)
    assert m["region"] == "module_band"
    lanes = {lane["module_id"]: lane for lane in m["tracks"]}
    assert set(lanes) == {"auth", "billing"}
    assert lanes["auth"]["progress"].endswith("/3")
    assert lanes["billing"]["blocked_by_deps"] == ["auth"]
    assert [p["name"] for p in lanes["auth"]["phases"]] == \
        ["RED#auth", "IMPLEMENTED#auth", "REVIEWED#auth"]


def test_navigation_top_level_shape_preserved_for_single_track(tmp_path):
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(pipeline.build_spine("minimal"), st)
    m = navigation.navigation_map(pipeline.build_spine("minimal"), st)
    assert m["region"] == "prologue"
    assert m["tracks"] == []          # additive, empty outside a band
    assert m["schema"] == "e2e-dev-harness.navigation-map.v1"
    assert "you_are_here" in m and "phases" in m and "progress" in m and "next" in m
