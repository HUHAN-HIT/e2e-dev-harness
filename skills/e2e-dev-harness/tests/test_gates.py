from e2e_harness.core import lifecycle, gates
from e2e_harness import pipeline


def _phase(name):
    return next(p for p in lifecycle.build_spine(pipeline.active_phase_names("minimal")) if p.name == name)


def test_gate_blocks_when_evidence_missing():
    ok, missing = gates.gate_passes(_phase("CLARIFIED"), {"evidence": {}})
    assert ok is False
    # CLARIFIED now also requires a structured acceptance contract (link ①).
    assert missing == ["clarification", "acceptance_contract"]


def test_gate_passes_when_evidence_present():
    rec = {"evidence": {"clarification": "h.md", "acceptance_contract": "a.json"}}
    ok, missing = gates.gate_passes(_phase("CLARIFIED"), rec)
    assert ok is True
    assert missing == []


def test_empty_gate_always_passes():
    ok, missing = gates.gate_passes(_phase("CREATED"), {})
    assert ok is True
    assert missing == []


def test_passed_phase_judged_against_stamped_contract_not_tightened_gate():
    """F2 (Hybrid): a phase carrying a contract stamp is judged against the gate in
    force when it passed, not a later-tightened live gate. Same evidence, no stamp
    -> blocked by the new requirement."""
    planned = lifecycle.catalog()["PLANNED"]  # live exit_gate = (plan, module_plan)
    plan_only = {"evidence": {"plan": "p.md"}}
    ok, missing = gates.gate_passes(planned, plan_only)
    assert ok is False and missing == ["module_plan"]      # unstamped -> live gate
    stamped = {"evidence": {"plan": "p.md"}, "contract": {"exit_gate": ["plan"]}}
    ok2, missing2 = gates.gate_passes(planned, stamped)
    assert ok2 is True and missing2 == []                  # judged against the stamp


def test_planned_default_gate_still_requires_module_plan_for_new_runs():
    """F2 must NOT revert the tightening: an unstamped (new) PLANNED still requires
    module_plan. Guards against an implementer loosening lifecycle.py."""
    planned = lifecycle.catalog()["PLANNED"]
    ok, missing = gates.gate_passes(planned, {"evidence": {"plan": "p.md"}})
    assert ok is False and "module_plan" in missing


def test_empty_contract_stamp_falls_back_to_live_gate():
    """F2: an empty stamp ([]) is conservative — it reverts to the live gate rather
    than legitimizing a phase with no matching evidence."""
    planned = lifecycle.catalog()["PLANNED"]
    rec = {"evidence": {"plan": "p.md"}, "contract": {"exit_gate": []}}
    ok, missing = gates.gate_passes(planned, rec)
    assert ok is False and missing == ["module_plan"]
