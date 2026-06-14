"""F2: display (navigation) and authoritative (engine/all_gates_pass) must agree on
the impact gate. Threading `state` into navigation's per-phase gate_passes is what
makes the PLANNED row reflect the impact binding."""
import json

from e2e_harness.core import navigation, lifecycle


def _run_with_verified_required_but_no_refs(tmp_path):
    run_dir = tmp_path / "docs" / "agent-runs" / "r1"
    run_dir.mkdir(parents=True)
    mp = run_dir / "module-plan.json"
    mp.write_text(json.dumps({"schema": "e2e-dev-harness.module-plan.v1",
                              "modules": [{"id": "m1", "name": "M1", "depends_on": [],
                                           "acceptance_ids": ["AC-001"]}]}), encoding="utf-8")
    plan = run_dir / "plan.md"
    plan.write_text("p", encoding="utf-8")
    # CLARIFIED must pass so PLANNED is the first blocker (the real F2 scenario).
    clar = run_dir / "clarification.md"
    clar.write_text("done", encoding="utf-8")
    contract = run_dir / "acceptance-contract.json"
    contract.write_text(json.dumps({
        "schema": "e2e-dev-harness.acceptance-contract.v1",
        "items": [{"id": "AC-001", "criterion": "c", "observable_behavior": "o"}]}),
        encoding="utf-8")
    spine = lifecycle.build_spine(
        ["CLARIFIED", "PLANNED", "RED", "IMPLEMENTED", "REVIEWED", "VERIFIED"])
    state = {"current_phase": "PLANNED", "impact": {"mode": "strict"},
             "impact_assessment": {"required": True, "status": "verified", "seeds": ["s1"]},
             "phases": {
                 "CLARIFIED": {"evidence": {"clarification": {"path": str(clar)},
                                            "acceptance_contract": {"path": str(contract)}}},
                 "PLANNED": {"evidence": {"plan": {"path": str(plan)},
                                          "module_plan": {"path": str(mp)}}}}}
    return spine, state


def test_navigation_planned_row_reflects_impact_gate(tmp_path):
    spine, state = _run_with_verified_required_but_no_refs(tmp_path)
    nav = navigation.navigation_map(spine, state, str(tmp_path))
    planned_row = next(p for p in nav["phases"] if p["name"] == "PLANNED")
    assert "impact_refs" in planned_row["gate"]["missing"]


def test_navigation_next_points_at_planned_when_impact_refs_missing(tmp_path):
    spine, state = _run_with_verified_required_but_no_refs(tmp_path)
    nav = navigation.navigation_map(spine, state, str(tmp_path))
    assert nav["next"]["phase"] == "PLANNED"
