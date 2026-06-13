"""End-to-end proof of multi-track execution (取向②, fix B2).

A standard run whose PLANNED emits a 2-module plan must expand into a full
RED -> IMPLEMENTED -> REVIEWED lifecycle *per module*, walked in dependency
order, before the single VERIFIED integrates. The spine is re-derived every
step (as the CLI does), so it stays single-track until the module plan lands at
PLANNED and expands from RED onward.
"""
import json
import sys

from e2e_harness import pipeline
from e2e_harness.core import run_state, engine, module_plan, acceptance, multitrack
from e2e_harness.adapters.evidence import command_evidence


def _artifact(repo, art, phase, key):
    bkey = multitrack.base_key(key)
    stem = f"{phase.replace('#', '_')}-{key.replace('#', '_')}"
    if bkey == "acceptance_contract":
        p = art / f"{stem}.json"
        p.write_text(json.dumps({"schema": acceptance.SCHEMA, "items": [
            {"id": "AC-001", "criterion": "c", "observable_behavior": "o"}]}), encoding="utf-8")
        return p
    if bkey == "module_plan":
        p = art / f"{stem}.json"
        p.write_text(json.dumps({"schema": module_plan.SCHEMA, "modules": [
            {"id": "auth", "name": "Auth", "depends_on": [], "acceptance_ids": ["AC-001"]},
            {"id": "billing", "name": "Billing", "depends_on": ["auth"], "acceptance_ids": ["AC-001"]},
        ]}), encoding="utf-8")
        return p
    if bkey == "test_substance":
        tf = art / f"{stem}_test.py"
        tf.write_text("def test_x():\n    assert 1 + 1 == 2\n", encoding="utf-8")
        p = art / f"{stem}.json"
        p.write_text(json.dumps({"schema": "e2e-dev-harness.test-substance.v1",
                                 "acceptance_contract_path": str(art / "CLARIFIED-acceptance_contract.json"),
                                 "language": "python", "test_files": [str(tf)],
                                 "red_tests": ["t::test_x"], "green_tests": ["t::test_x"],
                                 "ac_coverage": {"AC-001": ["t::test_x"]}}), encoding="utf-8")
        return p
    if bkey in ("failing_tests", "passing_tests"):
        code = 1 if bkey == "failing_tests" else 0
        ev = command_evidence.record_command(art, f'"{sys.executable}" -c "import sys; sys.exit({code})"')
        p = art / f"{stem}.json"
        p.write_text(json.dumps(ev), encoding="utf-8")
        return p
    p = art / f"{stem}.md"
    p.write_text("real", encoding="utf-8")
    return p


def test_two_module_run_walks_each_module_lifecycle_then_reaches_verified(tmp_path):
    repo = tmp_path
    art = repo / "art"
    art.mkdir()
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")

    seen: list[str] = []
    reached_verified = False
    for _ in range(40):
        spine = pipeline.spine_for_state(st, repo)   # re-derived each step (as the CLI does)
        st["_run_state_path"] = "rs.json"
        res = engine.evaluate(spine, st, repo)
        if res.get("complete") or res["blocked_phase"] == "VERIFIED":
            reached_verified = True
            break
        ph = res["blocked_phase"]
        seen.append(ph)
        phase = next(p for p in spine if p.name == ph)
        for key in phase.produces:
            f = _artifact(repo, art, ph, key)
            engine.submit_evidence(st, ph, key, str(f.relative_to(repo)), repo_root=repo)

    assert reached_verified
    assert st["current_phase"] == "VERIFIED"
    # every module ran its own full lifecycle, billing strictly after auth (dep order)
    assert seen.index("RED#auth") < seen.index("RED#billing")
    assert {"RED#auth", "IMPLEMENTED#auth", "REVIEWED#auth",
            "RED#billing", "IMPLEMENTED#billing", "REVIEWED#billing"} <= set(seen)


def test_two_module_phase_guard_authorizes_code_write_per_module(tmp_path):
    # the per-module IMPLEMENTED phase must authorize code writes; its RED must not
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")
    st["current_phase"] = "IMPLEMENTED#billing"
    assert pipeline.can_write_code(st) is True
    st["current_phase"] = "RED#billing"
    assert pipeline.can_write_code(st) is False
