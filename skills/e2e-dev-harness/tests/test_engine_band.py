"""Region-aware engine: dispatcher + per-track band advance."""
from e2e_harness import pipeline
from e2e_harness.core import engine, run_state


def test_region_of_defaults_to_prologue():
    st = run_state.new_run_state("r1", "f", "r")
    assert engine._region_of(st) == "prologue"


def test_region_of_reads_explicit_region():
    st = run_state.new_run_state("r1", "f", "r")
    st["region"] = "module_band"
    assert engine._region_of(st) == "module_band"


def test_prologue_evaluate_is_unchanged_for_single_track():
    spine = pipeline.build_spine("minimal")
    st = run_state.new_run_state("r1", "f", "r")
    res = engine.evaluate(spine, st)
    assert st["current_phase"] == "CLARIFIED"
    assert res["blocked_phase"] == "CLARIFIED"
    assert res["complete"] is False


import json

from e2e_harness.core import module_plan, multitrack
from e2e_harness.adapters.evidence import command_evidence


def _mod(mid, deps=()):
    return {"id": mid, "name": f"{mid} svc", "depends_on": list(deps), "acceptance_ids": ["AC-001"]}


def _write_plan(repo, *mods):
    p = repo / "mp.json"
    p.write_text(json.dumps({"schema": module_plan.SCHEMA, "modules": list(mods)}), encoding="utf-8")
    return p


def _planned_state(repo, *mods):
    """State sitting at PLANNED with a valid >=2-module plan, ready to fork.

    PLANNED's gate validates real artifacts (repo_root is passed), so `plan` and
    `module_plan` must be real non-empty files for the fork to fire.
    """
    _write_plan(repo, *mods)
    (repo / "plan.md").write_text("# plan\nreal", encoding="utf-8")
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")
    st["current_phase"] = "PLANNED"
    st["phases"] = {
        "CLARIFIED": {"evidence": {"clarification": {"path": "c"}, "acceptance_contract": {"path": "a"}}},
        "PLANNED": {"evidence": {"plan": {"path": "plan.md"}, "module_plan": {"path": "mp.json"}}},
    }
    return st


def _failing(repo, mid):
    """Real failing-tests command evidence file for RED#<mid>."""
    art = repo / "art"; art.mkdir(exist_ok=True)
    ev = command_evidence.record_command(art, 'python -c "import sys; sys.exit(1)"')
    p = art / f"failing_{mid}.json"
    p.write_text(json.dumps(ev), encoding="utf-8")
    return str(p.relative_to(repo))


def test_passing_planned_forks_into_band(tmp_path):
    st = _planned_state(tmp_path, _mod("auth"), _mod("reports"))
    res = engine.evaluate(pipeline.spine_for_state(st, tmp_path), st, tmp_path)
    assert st["region"] == "module_band"
    assert set(st["tracks"]) == {"auth", "reports"}
    assert res["region"] == "module_band"


def test_band_frontier_holds_all_independent_tracks(tmp_path):
    st = _planned_state(tmp_path, _mod("auth"), _mod("reports"))
    res = engine.evaluate(pipeline.spine_for_state(st, tmp_path), st, tmp_path)
    blocked = sorted(e["blocked_phase"] for e in res["tracks_frontier"])
    assert blocked == ["RED#auth", "RED#reports"]
    # leading-cursor projection picks the topo-first track
    assert res["blocked_phase"] == "RED#auth"


def test_band_dependent_track_absent_from_frontier(tmp_path):
    st = _planned_state(tmp_path, _mod("auth"), _mod("billing", deps=["auth"]))
    res = engine.evaluate(pipeline.spine_for_state(st, tmp_path), st, tmp_path)
    blocked = [e["blocked_phase"] for e in res["tracks_frontier"]]
    assert blocked == ["RED#auth"]  # billing gated by depends_on


def test_band_tracks_advance_independently(tmp_path):
    st = _planned_state(tmp_path, _mod("auth"), _mod("reports"))
    spine = pipeline.spine_for_state(st, tmp_path)
    engine.evaluate(spine, st, tmp_path)              # fork -> frontier RED#auth, RED#reports
    # only auth submits its failing tests this beat
    engine.submit_evidence(st, "RED#auth", "failing_tests#auth", _failing(tmp_path, "auth"), repo_root=tmp_path)
    res = engine.evaluate(spine, st, tmp_path)
    frontier = {e["track"]: e["blocked_phase"] for e in res["tracks_frontier"]}
    assert frontier["auth"] == "IMPLEMENTED#auth"     # auth advanced
    assert frontier["reports"] == "RED#reports"       # reports unchanged -> not blocked by auth


def test_band_joins_to_verified_when_all_tracks_complete(tmp_path):
    st = _planned_state(tmp_path, _mod("auth"), _mod("reports"))
    spine = pipeline.spine_for_state(st, tmp_path)
    engine.evaluate(spine, st, tmp_path)
    # mark every module phase satisfied directly (presence-only gate via repo_root=None)
    by = {p.name: p for p in spine}
    for name in ("RED#auth", "IMPLEMENTED#auth", "REVIEWED#auth",
                 "RED#reports", "IMPLEMENTED#reports", "REVIEWED#reports"):
        st.setdefault("phases", {})[name] = {"evidence": {k: {"path": "x"} for k in by[name].exit_gate}}
    res = engine.evaluate(spine, st, None)   # repo_root=None -> presence-only gate
    assert st["region"] == "epilogue"
    assert st["current_phase"] == "VERIFIED"
    assert res["blocked_phase"] == "VERIFIED"


from e2e_harness.core import dispatch as dispatch_core


def _completed_band_state(tmp_path, *mods):
    """A band state whose tracks are all complete and sitting at the VERIFIED
    join, with module evidence present (presence-only gate)."""
    st = _planned_state(tmp_path, *mods)
    spine = pipeline.spine_for_state(st, tmp_path)
    engine.evaluate(spine, st, tmp_path)  # fork
    by = {p.name: p for p in spine}
    for mid in (m["id"] for m in mods):
        for base in ("RED", "IMPLEMENTED", "REVIEWED"):
            name = f"{base}#{mid}"
            st["phases"][name] = {"evidence": {k: {"path": "x"} for k in by[name].exit_gate},
                                  "dispatch": dispatch_core.DispatchStatus.DONE.value}
    return st, spine


def test_band_verification_failure_reopens_implementation_tracks(tmp_path):
    st, spine = _completed_band_state(tmp_path, _mod("auth"), _mod("reports"))
    # join to epilogue with a FAILED verification (presence-only gate, but the
    # phase dispatch is marked failed to trigger verification rework)
    st["phases"]["VERIFIED"] = {
        "evidence": {"verification": {"path": "v"}, "scope_manifest": {"path": "s"}},
        "dispatch": dispatch_core.DispatchStatus.FAILED.value,
        "blocker": "verification command exited 1",
    }
    st["region"] = "epilogue"
    st["current_phase"] = "VERIFIED"
    res = engine.evaluate(spine, st, None)
    assert res["rework_required"] is True
    assert st["region"] == "module_band"
    # not attributable (VERIFIED keys are un-namespaced) -> reopen all tracks
    assert st["tracks"]["auth"]["complete"] is False
    assert st["tracks"]["reports"]["complete"] is False
    assert st["phases"]["IMPLEMENTED#auth"]["evidence"] == {}
    assert st["phases"]["IMPLEMENTED#auth"]["dispatch"] == dispatch_core.DispatchStatus.FAILED.value
    assert set(st["phases"]["IMPLEMENTED#auth"]["superseded_evidence"]) == \
        {"passing_tests#auth", "test_substance#auth"}


def test_single_track_verification_rework_is_unchanged(tmp_path):
    # guards the back-compat path: no tracks -> legacy _route_verification_rework
    from e2e_harness.adapters.evidence import command_evidence as ce
    spine = pipeline.build_spine("minimal")
    st = run_state.new_run_state("r1", "f", "r")
    st["current_phase"] = "VERIFIED"
    st["phases"]["IMPLEMENTED"] = {
        "dispatch": dispatch_core.DispatchStatus.DONE.value,
        "evidence": {"passing_tests": {"path": "old.json"}, "test_substance": {"path": "old.json"}},
    }
    ev = ce.record_command(tmp_path, 'python -c "import sys; sys.exit(1)"')
    v = tmp_path / "v.json"; v.write_text(json.dumps(ev), encoding="utf-8")
    s = tmp_path / "s.json"
    s.write_text(json.dumps({"schema": "e2e-dev-harness.scope-manifest.v1", "status": "COMPLETE",
                             "expected": {"services": [], "tables": [], "phases": []},
                             "delivered": {"services": [], "tables": [], "phases": []}}), encoding="utf-8")
    engine.submit_evidence(st, "VERIFIED", "verification", str(v), repo_root=tmp_path)
    engine.submit_evidence(st, "VERIFIED", "scope_manifest", str(s), repo_root=tmp_path)
    res = engine.evaluate(spine, st, tmp_path)
    assert res["rework_required"] is True
    assert res["blocked_phase"] == "IMPLEMENTED"   # single-chain target, unchanged
