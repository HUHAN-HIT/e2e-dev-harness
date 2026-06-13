import json
import sys
from pathlib import Path

from e2e_harness import pipeline
from e2e_harness.core import run_state, engine, dispatch, gates
from e2e_harness.adapters.agent_team import builtin
from e2e_harness.adapters.evidence import command_evidence, validate


def _artifact(base, phase, key):
    """Write a real artifact valid for `key`: command-evidence JSON for the
    test-running phases (failing_tests=nonzero, passing_tests=zero), plain
    file otherwise."""
    if key == "scope_manifest":
        import json as _json
        f = base / f"{phase}-{key}.json"
        f.write_text(_json.dumps({"schema": "e2e-dev-harness.scope-manifest.v1", "status": "COMPLETE", "expected": {"services": [], "tables": [], "phases": []}, "delivered": {"services": [], "tables": [], "phases": []}}), encoding="utf-8")
        return f
    if key == "test_substance":
        import json as _json
        tf = base / f"{phase}-real_test.py"
        tf.write_text("def test_real():" + chr(10) + "    assert 1 + 1 == 2" + chr(10), encoding="utf-8")
        man = {"schema": "e2e-dev-harness.test-substance.v1",
               "acceptance_contract_path": str(base / "CLARIFIED-acceptance_contract.json"),
               "language": "python", "test_files": [str(tf)],
               "red_tests": ["t::test_real"], "green_tests": ["t::test_real"],
               "ac_coverage": {"AC-001": ["t::test_real"]}}
        f = base / f"{phase}-{key}.json"
        f.write_text(_json.dumps(man), encoding="utf-8")
        return f
    if key == "acceptance_contract":
        from e2e_harness.core import acceptance as _acc
        f = base / f"{phase}-{key}.json"
        f.write_text(json.dumps({"schema": _acc.SCHEMA, "items": [
            {"id": "AC-001", "criterion": "c", "observable_behavior": "o"}]}), encoding="utf-8")
        return f
    if key == "module_plan":
        from e2e_harness.core import module_plan as _mp
        f = base / f"{phase}-{key}.json"
        f.write_text(json.dumps({"schema": _mp.SCHEMA, "modules": [
            {"id": "core", "name": "Core", "depends_on": [], "acceptance_ids": ["AC-001"]}]}), encoding="utf-8")
        return f
    want = validate.COMMAND_KEYS.get(key)
    if want is None:
        f = base / f"{phase}-{key}.md"
        f.write_text("real", encoding="utf-8")
        return f
    f = base / f"{phase}-{key}.json"
    code = 0 if want == "zero" else 1
    ev = command_evidence.record_command(
        base, f'"{sys.executable}" -c "import sys; sys.exit({code})"')
    f.write_text(json.dumps(ev), encoding="utf-8")
    return f


def _drive_to(state, repo, target, spine):
    """Advance, fabricating real artifacts, until current_phase == target."""
    base = Path(repo) / "art"
    base.mkdir(parents=True, exist_ok=True)
    res = {"complete": False}
    for _ in range(20):
        res = engine.evaluate(spine, state, repo)
        if state["current_phase"] == target or res["complete"]:
            return res
        phase = res["blocked_phase"]
        ph = next(p for p in spine if p.name == phase)
        for key in ph.produces:
            f = _artifact(base, phase, key)
            engine.submit_evidence(state, phase, key, str(f), repo_root=repo)
    return res


def test_critical_reviewed_dispatch_packet_lists_three_reviews():
    spine = pipeline.build_spine("critical")
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    packet = dispatch.worker_packet(reviewed, "docs/agent-runs/r1/run-state.json")
    assert packet["expected_outputs"] == ["r1_review", "r2_review", "r3_review"]


def test_critical_reviewed_agent_team_plan_splits_three_reviews(tmp_path):
    spine = pipeline.build_spine("critical")
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    plan = builtin.BuiltinAgentTeamProvider().plan_phase({
        "schema": "e2e-dev-harness.agent-team-request.v1",
        "run_state_path": "docs/agent-runs/r1/run-state.json",
        "repo_root": str(tmp_path),
        "runtime": "codex",
        "pipeline": "critical",
        "phase": {
            "name": reviewed.name,
            "worker_role": reviewed.worker_role,
            "worker_skill": reviewed.worker_skill,
            "produces": list(reviewed.produces),
            "exit_gate": list(reviewed.exit_gate),
            "allows_code_write": reviewed.allows_code_write,
        },
        "context_paths": ["docs/agent-runs/r1/run-state.json"],
        "team_profile": "default-critical",
        "constraints": {"max_workers": 3, "fresh_context": True, "allow_code_write": False},
    })

    assert [worker["expected_outputs"] for worker in plan["workers"]] == [
        ["r1_review"],
        ["r2_review"],
        ["r3_review"],
    ]


def test_critical_reviewed_blocks_until_three_real_reviews(tmp_path):
    spine = pipeline.build_spine("critical")
    st = run_state.new_run_state("r1", "f", "r", tier="critical", pipeline="critical")
    _drive_to(st, tmp_path, "REVIEWED", spine)
    assert st["current_phase"] == "REVIEWED"
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    # submit only two real reviews -> still blocked
    for key in ("r1_review", "r2_review"):
        f = tmp_path / f"{key}.md"; f.write_text("ok", encoding="utf-8")
        engine.submit_evidence(st, "REVIEWED", key, str(f), repo_root=tmp_path)
    ok, missing = gates.gate_passes(reviewed, st["phases"]["REVIEWED"], tmp_path)
    assert ok is False and "r3_review" in missing
    # third review -> gate passes
    f = tmp_path / "r3_review.md"; f.write_text("ok", encoding="utf-8")
    engine.submit_evidence(st, "REVIEWED", "r3_review", str(f), repo_root=tmp_path)
    ok, missing = gates.gate_passes(reviewed, st["phases"]["REVIEWED"], tmp_path)
    assert ok is True and missing == []


_ADVERSARIAL_KEYS = [
    "adversarial_code_review",
    "adversarial_design_review",
    "adversarial_test_design_review",
]


def test_adversarial_reviewed_agent_team_plan_splits_three_perspectives(tmp_path):
    """default-adversarial fans REVIEWED into three isolated workers — one per
    perspective — each owning exactly one adversarial evidence key and running the
    dedicated adversarial reviewer skill."""
    spine = pipeline.build_spine("adversarial")
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    plan = builtin.BuiltinAgentTeamProvider().plan_phase({
        "schema": "e2e-dev-harness.agent-team-request.v1",
        "run_state_path": "docs/agent-runs/r1/run-state.json",
        "repo_root": str(tmp_path),
        "runtime": "codex",
        "pipeline": "adversarial",
        "phase": {
            "name": reviewed.name,
            "worker_role": reviewed.worker_role,
            "worker_skill": reviewed.worker_skill,
            "produces": list(reviewed.produces),
            "exit_gate": list(reviewed.exit_gate),
            "allows_code_write": reviewed.allows_code_write,
        },
        "context_paths": ["docs/agent-runs/r1/run-state.json"],
        "team_profile": "default-adversarial",
        "constraints": {"max_workers": 3, "fresh_context": True, "allow_code_write": False},
    })

    assert [worker["id"] for worker in plan["workers"]] == [
        "REVIEWED-code", "REVIEWED-design", "REVIEWED-tests"]
    assert [worker["expected_outputs"] for worker in plan["workers"]] == [
        ["adversarial_code_review"],
        ["adversarial_design_review"],
        ["adversarial_test_design_review"],
    ]
    assert all(worker["skill"] == "e2e-harness-adversarial-review" for worker in plan["workers"])


_ADVERSARIAL_PERSPECTIVE = {
    "adversarial_code_review": "code",
    "adversarial_design_review": "design",
    "adversarial_test_design_review": "test-design",
}


def _adversarial_artifact(base, key):
    """A valid adversarial-review.v1 artifact for `key` — Slice 2 gates these keys
    structurally, so a prose file no longer satisfies the REVIEWED gate."""
    persp = _ADVERSARIAL_PERSPECTIVE[key]
    f = base / f"{key}.json"
    f.write_text(json.dumps({
        "schema": "e2e-dev-harness.adversarial-review.v1",
        "perspective": persp,
        "verdict": "pass-with-findings",
        "claims_attacked": [
            {"id": "C-001", "claim": "fan-out yields independent perspectives",
             "source": "agent-teams/default-adversarial.yaml"}],
        "findings": [
            {"id": "F-001", "severity": "medium", "target": "builtin.py",
             "claim_attacked": "perspective is explicit in the packet",
             "evidence": "packet has expected_outputs but no review_perspective field",
             "counterexample": "a misnamed key makes the worker pick no perspective",
             "required_fix": "keep the key-naming contract tested"}],
        "missing_evidence": [],
        "residual_risk": [],
    }), encoding="utf-8")
    return f


def test_adversarial_reviewed_blocks_until_three_real_reviews(tmp_path):
    spine = pipeline.build_spine("adversarial")
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="adversarial")
    _drive_to(st, tmp_path, "REVIEWED", spine)
    assert st["current_phase"] == "REVIEWED"
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    # submit only two perspectives (valid structured evidence) -> still blocked on the third
    for key in ("adversarial_code_review", "adversarial_design_review"):
        f = _adversarial_artifact(tmp_path, key)
        engine.submit_evidence(st, "REVIEWED", key, str(f), repo_root=tmp_path)
    ok, missing = gates.gate_passes(reviewed, st["phases"]["REVIEWED"], tmp_path)
    assert ok is False and "adversarial_test_design_review" in missing
    # third perspective -> gate passes
    f = _adversarial_artifact(tmp_path, "adversarial_test_design_review")
    engine.submit_evidence(st, "REVIEWED", "adversarial_test_design_review", str(f), repo_root=tmp_path)
    ok, missing = gates.gate_passes(reviewed, st["phases"]["REVIEWED"], tmp_path)
    assert ok is True and missing == []


def test_adversarial_reviewed_prose_no_longer_satisfies_gate(tmp_path):
    """Slice 2 assurance: a non-empty prose file for an adversarial key is rejected
    at the gate (it cannot prove claims were attacked), unlike the prose-gated MVP."""
    spine = pipeline.build_spine("adversarial")
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="adversarial")
    _drive_to(st, tmp_path, "REVIEWED", spine)
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    for key in _ADVERSARIAL_PERSPECTIVE:
        f = tmp_path / f"{key}.md"; f.write_text("looks fine", encoding="utf-8")
        engine.submit_evidence(st, "REVIEWED", key, str(f), repo_root=tmp_path)
    ok, missing = gates.gate_passes(reviewed, st["phases"]["REVIEWED"], tmp_path)
    assert ok is False
    assert set(missing) == set(_ADVERSARIAL_PERSPECTIVE)
