"""F-4 coverage closure: the operator-facing `gate` verb must ground scope at gate
time too (Hard Boundary #4: "No ungrounded COMPLETE").

Before the fix, `gate --phase VERIFIED` called gate_passes WITHOUT the trusted
run-state, so the scope_manifest validator fell back to tables-only grounding and
a phases/services COMPLETE overclaim PASSED the standalone gate even though `next`
(which threads state through engine.evaluate -> all_gates_pass) rejected it. That
left the strongest claim ("rejected AT THE GATE") true for `next` but not for the
`gate` verb — a real divergence on an operator-facing surface.
"""
import json
from types import SimpleNamespace

from e2e_harness.cli.commands import gate
from e2e_harness.core import module_plan, multitrack, run_state
from e2e_harness.core import scope as scope_core
from e2e_harness import pipeline


def _modular_state_on_disk(tmp_path, modules, completed, *, delivered_phases, status):
    """Write a multi-module run-state + module plan + a VERIFIED scope manifest to
    disk and return the run-state path. `modules` is a list of (id, services)."""
    mods = []
    for i, (mid, services) in enumerate(modules):
        mods.append({"id": mid, "name": mid, "depends_on": [],
                     "acceptance_ids": [f"AC-{i + 1:03d}"],
                     "scope": {"services": list(services), "tables": []}})
    mplan = {"schema": module_plan.SCHEMA, "modules": mods}
    (tmp_path / "module-plan.json").write_text(json.dumps(mplan), encoding="utf-8")

    state = {"schema": run_state.SCHEMA, "run_id": "r1", "feature": "f",
             "request": "r", "tier": "standard", "pipeline": "standard",
             "current_phase": "VERIFIED",
             "phases": {"PLANNED": {"evidence": {"module_plan": {"path": "module-plan.json"}}}}}
    spine = multitrack.expand(pipeline.build_spine("standard"), mplan)
    by = {p.name: p for p in spine}
    for mid in completed:
        for base in ("RED", "IMPLEMENTED", "REVIEWED"):
            name = f"{base}#{mid}"
            state["phases"][name] = {"evidence": {k: {"path": "x"} for k in by[name].exit_gate}}

    man = {"schema": scope_core.SCHEMA, "status": status,
           "expected": {"services": [], "tables": [], "phases": list(delivered_phases)},
           "delivered": {"services": [], "tables": [], "phases": list(delivered_phases)}}
    (tmp_path / "scope.json").write_text(json.dumps(man), encoding="utf-8")
    state["phases"]["VERIFIED"] = {"evidence": {"scope_manifest": {"path": "scope.json"}}}

    sp = tmp_path / "run-state.json"
    sp.write_text(json.dumps(state), encoding="utf-8")
    return sp


def _args(sp, tmp_path, phase="VERIFIED"):
    return SimpleNamespace(state=str(sp), repo=str(tmp_path), phase=phase)


def test_gate_verb_rejects_scope_overclaim_at_gate_time(tmp_path):
    # `reporting` was never a completed module -> ungrounded phase overclaim.
    sp = _modular_state_on_disk(
        tmp_path,
        modules=[("auth", []), ("billing", [])],
        completed=["auth", "billing"],
        delivered_phases=["auth", "billing", "reporting"],
        status="COMPLETE",
    )
    code, payload = gate.run(_args(sp, tmp_path))
    # The discriminating assertion: scope_manifest is grounded against run-state, so
    # the overclaim is rejected by the standalone `gate` verb (tables-only would
    # have let it pass).
    assert "scope_manifest" in payload["missing_evidence"]
    assert code == 1


def test_gate_verb_passes_honest_complete_scope(tmp_path):
    # No overclaim: every delivered phase is a completed module, so threading state
    # must NOT falsely reject the honest scope manifest.
    sp = _modular_state_on_disk(
        tmp_path,
        modules=[("auth", []), ("billing", [])],
        completed=["auth", "billing"],
        delivered_phases=["auth", "billing"],
        status="COMPLETE",
    )
    code, payload = gate.run(_args(sp, tmp_path))
    assert "scope_manifest" not in payload["missing_evidence"]
