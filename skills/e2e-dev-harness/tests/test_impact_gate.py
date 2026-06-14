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


def test_verified_binding_without_seeds_reports_integrity_defect(tmp_path):
    mp = _module_plan(tmp_path, impact_refs=[])
    st = {"impact_assessment": {"required": True, "status": "verified", "seeds": []}}
    assert impact_gate.planned_missing(st, str(tmp_path), _planned_rec(mp)) == [
        "impact_assessment_seeds_missing"
    ]


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


def test_degraded_artifact_sha_mismatch_blocks_integrity(tmp_path):
    art = tmp_path / "impact-assessment.json"
    art.write_text(json.dumps({"schema": "e2e-dev-harness.impact-assessment.v1",
                               "status": "degraded", "seeds": [], "impact": [],
                               "approval": {"sha256": "abc"}}), encoding="utf-8")
    import hashlib
    original_sha = hashlib.sha256(art.read_bytes()).hexdigest()
    art.write_text(json.dumps({"schema": "e2e-dev-harness.impact-assessment.v1",
                               "status": "degraded", "seeds": [], "impact": [],
                               "approval": {"sha256": "abc"},
                               "tampered": True}), encoding="utf-8")
    st = {"_run_state_path": str(tmp_path / "run-state.json"),
          "approvals": {"impact_degradation": {"sha256": "abc"}},
          "impact_assessment": {"required": True, "status": "degraded",
                                "path": "impact-assessment.json",
                                "sha256": original_sha}}
    assert impact_gate.planned_missing(st, str(tmp_path), {}) == [
        "impact_assessment_integrity"
    ]


def test_missing_binding_returns_empty_not_unsatisfiable(tmp_path):
    # No binding: on the authoritative path the engine always writes the binding before
    # the PLANNED gate; a custom spine without CLARIFIED cannot assess impact at all.
    # Either way the gate must NOT demand an `impact_assessment` that nothing can
    # produce -> []  (removing the old unsatisfiable backstop that wedged such runs).
    contract = tmp_path / "acceptance-contract.json"
    contract.write_text(json.dumps({"schema": "e2e-dev-harness.acceptance-contract.v1",
                                    "items": [{"id": "AC-001", "criterion": "c",
                                               "observable_behavior": "o"}],
                                    "impact_seed_candidates": ["_phase_request"]}), encoding="utf-8")
    st = {"request": "change planner", "tier": "critical", "impact": {"mode": "strict"},
          "phases": {"CLARIFIED": {"evidence": {"acceptance_contract": {"path": str(contract)}}}}}
    assert impact_gate.planned_missing(st, str(tmp_path), {}) == []


def test_missing_binding_mode_off_no_block(tmp_path):
    st = {"request": "change planner", "tier": "critical", "impact": {"mode": "off"}}
    assert impact_gate.planned_missing(st, str(tmp_path), {}) == []


# --- Task 3d.2: wired into gates.gate_passes for PLANNED ---

from e2e_harness.core import gates, lifecycle, engine


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


# --- P1-A regression: a custom spine with PLANNED but no CLARIFIED must not wedge ---

def test_planned_without_clarified_does_not_wedge(tmp_path):
    """A custom pipeline can have PLANNED without CLARIFIED. The engine impact bridge
    only runs when CLARIFIED is in the spine, so no `impact_assessment` binding is ever
    written for such a run. The PLANNED gate must NOT then demand an impact_assessment
    that nothing can produce — the run must advance past PLANNED, not stall forever."""
    spine = lifecycle.build_spine(["PLANNED", "RED"])
    (tmp_path / "plan.md").write_text("# plan\n", encoding="utf-8")
    mp = _module_plan(tmp_path)                         # valid module-plan.json
    st = {
        "current_phase": "PLANNED",
        "impact": {"mode": "auto"},                     # default-on, NOT off
        "request": "modify the checkout handler function",  # code surface => impact "required"
        "phases": {"PLANNED": {"evidence": {
            "plan": {"path": "plan.md"},
            "module_plan": {"path": str(mp.relative_to(tmp_path))},
        }}},
    }
    res = engine.evaluate(spine, st, repo_root=str(tmp_path))
    assert res["blocked_phase"] == "RED"                # advanced past PLANNED
    assert "impact_assessment" not in res["missing_evidence"]
