from types import SimpleNamespace

from e2e_harness.core import run_state, gates
from e2e_harness.cli.commands import migrate
from e2e_harness import pipeline


def test_migrate_stamps_plan_only_planned_against_intersection(tmp_path):
    """F2 (Hybrid): `migrate` back-fills a contract stamp for a legacy phase that no
    longer satisfies a tightened live gate, using the intersection of the live gate
    with the evidence actually present (plan-only PLANNED -> ['plan'])."""
    st = run_state.new_run_state("r1", "f", "r", tier="audited", pipeline="audited")
    st["current_phase"] = "PLANNED"
    st["phases"]["PLANNED"] = {"evidence": {"plan": {"path": "plan.md"}}, "dispatch": "done"}
    p = tmp_path / "run-state.json"
    run_state.save(p, st)

    code, res = migrate.run(SimpleNamespace(state=str(p), repo="."))

    assert code == 0
    assert any(s["phase"] == "PLANNED" and s["exit_gate"] == ["plan"] for s in res["stamped"])
    reloaded = run_state.load(p)
    assert reloaded["phases"]["PLANNED"]["contract"]["exit_gate"] == ["plan"]
    # and the stamp makes the live gate pass without re-running the planner
    planned = next(ph for ph in pipeline.spine_for_state(reloaded, tmp_path) if ph.name == "PLANNED")
    ok, missing = gates.gate_passes(planned, reloaded["phases"]["PLANNED"])
    assert ok is True and missing == []


def test_migrate_skips_phase_with_no_present_evidence(tmp_path):
    """F2: a phase whose evidence has zero overlap with the live gate is NOT stamped
    with [] (which would silently revert to live gate); it is reported skipped."""
    st = run_state.new_run_state("r1", "f", "r", tier="audited", pipeline="audited")
    st["current_phase"] = "PLANNED"
    st["phases"]["PLANNED"] = {"evidence": {"unrelated": {"path": "x"}}, "dispatch": "done"}
    p = tmp_path / "run-state.json"
    run_state.save(p, st)

    code, res = migrate.run(SimpleNamespace(state=str(p), repo="."))

    assert code == 0
    assert "PLANNED" in res["skipped_empty"]
    assert "contract" not in run_state.load(p)["phases"]["PLANNED"]


def test_migrate_leaves_fully_satisfied_phase_unstamped(tmp_path):
    """F2: a phase that already satisfies the live gate needs no stamp."""
    st = run_state.new_run_state("r1", "f", "r", tier="audited", pipeline="audited")
    st["current_phase"] = "RED"
    st["phases"]["CLARIFIED"] = {"evidence": {
        "clarification": {"path": "c.md"}, "acceptance_contract": {"path": "a.json"}}}
    p = tmp_path / "run-state.json"
    run_state.save(p, st)

    code, res = migrate.run(SimpleNamespace(state=str(p), repo="."))

    assert code == 0
    assert "contract" not in run_state.load(p)["phases"]["CLARIFIED"]
