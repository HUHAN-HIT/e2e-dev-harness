import json

from e2e_harness.core import impact_gate


def _module_plan(tmp_path, impact_refs=None):
    mp = {"schema": "e2e-dev-harness.module-plan.v1",
          "modules": [{"id": "m1", "name": "M1", "depends_on": [], "acceptance_ids": ["AC-001"]}]}
    if impact_refs is not None:
        mp["modules"][0]["impact_refs"] = impact_refs
    p = tmp_path / "module-plan.json"
    p.write_text(json.dumps(mp), encoding="utf-8")
    return p


def _planned_rec(mp_path):
    return {"evidence": {"module_plan": {"path": str(mp_path)}}}


def test_no_binding_no_block(tmp_path):
    assert impact_gate.planned_missing({}, str(tmp_path), {}) == []


def test_not_required_no_block(tmp_path):
    st = {"impact_assessment": {"required": False, "status": "not_applicable"}}
    assert impact_gate.planned_missing(st, str(tmp_path), {}) == []


def test_blocked_not_reported_here(tmp_path):
    st = {"impact_assessment": {"required": True, "status": "blocked"}}
    assert impact_gate.planned_missing(st, str(tmp_path), {}) == []   # owned by CLARIFIED edge


def test_verified_requires_refs(tmp_path):
    mp = _module_plan(tmp_path, impact_refs=None)
    st = {"impact_assessment": {"required": True, "status": "verified", "seeds": ["_phase_request"]}}
    assert impact_gate.planned_missing(st, str(tmp_path), _planned_rec(mp)) == ["impact_refs"]


def test_verified_with_matching_refs_passes(tmp_path):
    mp = _module_plan(tmp_path, impact_refs=[{"seed": "_phase_request",
                                              "affected_processes": ["run"], "test_focus": ["x"]}])
    st = {"impact_assessment": {"required": True, "status": "verified", "seeds": ["_phase_request"]}}
    assert impact_gate.planned_missing(st, str(tmp_path), _planned_rec(mp)) == []


def test_degraded_without_matching_approval_blocks(tmp_path):
    art = tmp_path / "impact-assessment.json"
    art.write_text(json.dumps({"schema": "e2e-dev-harness.impact-assessment.v1",
                               "status": "degraded", "seeds": [], "impact": [],
                               "approval": {"sha256": "abc"}}), encoding="utf-8")
    st = {"_run_state_path": str(tmp_path / "run-state.json"),
          "approvals": {"impact_degradation": {"sha256": "MISMATCH"}},
          "impact_assessment": {"required": True, "status": "degraded",
                                "path": "impact-assessment.json"}}
    assert impact_gate.planned_missing(st, str(tmp_path), {}) == ["impact_degradation_approval"]


def test_degraded_with_matching_approval_passes(tmp_path):
    art = tmp_path / "impact-assessment.json"
    art.write_text(json.dumps({"schema": "e2e-dev-harness.impact-assessment.v1",
                               "status": "degraded", "seeds": [], "impact": [],
                               "approval": {"sha256": "abc"}}), encoding="utf-8")
    st = {"_run_state_path": str(tmp_path / "run-state.json"),
          "approvals": {"impact_degradation": {"sha256": "abc"}},
          "impact_assessment": {"required": True, "status": "degraded",
                                "path": "impact-assessment.json"}}
    assert impact_gate.planned_missing(st, str(tmp_path), {}) == []


def test_missing_binding_but_required_is_backstop(tmp_path):
    # No binding, but the trigger says required -> backstop reports impact_assessment.
    contract = tmp_path / "acceptance-contract.json"
    contract.write_text(json.dumps({"schema": "e2e-dev-harness.acceptance-contract.v1",
                                    "items": [{"id": "AC-001", "criterion": "c",
                                               "observable_behavior": "o"}],
                                    "impact_seed_candidates": ["_phase_request"]}), encoding="utf-8")
    st = {"request": "change planner", "tier": "critical", "impact": {"mode": "strict"},
          "phases": {"CLARIFIED": {"evidence": {"acceptance_contract": {"path": str(contract)}}}}}
    assert impact_gate.planned_missing(st, str(tmp_path), {}) == ["impact_assessment"]


def test_missing_binding_mode_off_no_block(tmp_path):
    st = {"request": "change planner", "tier": "critical", "impact": {"mode": "off"}}
    assert impact_gate.planned_missing(st, str(tmp_path), {}) == []


# --- Task 3d.2: wired into gates.gate_passes for PLANNED ---

from e2e_harness.core import gates, lifecycle


def _plain(tmp_path, name):
    p = tmp_path / name
    p.write_text("x", encoding="utf-8")
    return p


def _planned_phase():
    return next(p for p in lifecycle.build_spine(["CLARIFIED", "PLANNED"]) if p.name == "PLANNED")


def test_gate_passes_reports_impact_refs_for_planned(tmp_path):
    mp = _module_plan(tmp_path, impact_refs=None)
    rec = _planned_rec(mp)
    rec["evidence"]["plan"] = {"path": str(_plain(tmp_path, "plan.md"))}
    st = {"impact_assessment": {"required": True, "status": "verified", "seeds": ["_phase_request"]}}
    ok, missing = gates.gate_passes(_planned_phase(), rec, str(tmp_path), state=st)
    assert ok is False and "impact_refs" in missing


def test_gate_passes_no_state_skips_impact(tmp_path):
    mp = _module_plan(tmp_path, impact_refs=None)
    rec = _planned_rec(mp)
    rec["evidence"]["plan"] = {"path": str(_plain(tmp_path, "plan.md"))}
    ok, missing = gates.gate_passes(_planned_phase(), rec, str(tmp_path))   # no state
    assert "impact_refs" not in missing
