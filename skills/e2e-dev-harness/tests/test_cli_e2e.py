import json
import subprocess
import sys
from pathlib import Path

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness.py"


def _run(*args, cwd):
    proc = subprocess.run([sys.executable, str(ENTRY), *args],
                          cwd=cwd, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout or "{}")


def _make_artifact(repo: Path, phase: str, key: str) -> str:
    """Produce a REAL artifact for `key`; return its repo-relative path."""
    from e2e_harness.adapters.evidence import command_evidence as ce, validate
    base = repo / "docs" / "agent-runs" / "art"
    base.mkdir(parents=True, exist_ok=True)
    # Any COMMAND_KEYS key (failing_tests/passing_tests/verification) needs genuine
    # command-evidence with the right exit code; everything else is a plain artifact.
    if key == "scope_manifest":
        import json as _json
        f = base / f"{phase}-{key}.json"
        f.write_text(_json.dumps({"schema": "e2e-dev-harness.scope-manifest.v1", "status": "COMPLETE", "expected": {"services": [], "tables": [], "phases": []}, "delivered": {"services": [], "tables": [], "phases": []}}), encoding="utf-8")
        return str(f.relative_to(repo))
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
        return str(f.relative_to(repo))
    if key == "acceptance_contract":
        import json as _json
        from e2e_harness.core import acceptance as _acc
        f = base / f"{phase}-{key}.json"
        f.write_text(_json.dumps({"schema": _acc.SCHEMA, "items": [
            {"id": "AC-001", "criterion": "demo criterion",
             "observable_behavior": "demo observable behaviour"}]}), encoding="utf-8")
        return str(f.relative_to(repo))
    want = validate.COMMAND_KEYS.get(key)
    if want is not None:
        code = 0 if want == "zero" else 1
        command = f'"{sys.executable}" -c "import sys; sys.exit({code})"'
        if key == "verification":
            tf = base / f"{phase}-{key}-replay_test.py"
            tf.write_text("def test_real():\n    assert 1 + 1 == 2\n", encoding="utf-8")
            command = f'"{sys.executable}" -m pytest "{tf}" -q'
        ev = ce.record_command(repo, command)
        f = base / f"{phase}-{key}.json"
        f.write_text(json.dumps(ev), encoding="utf-8")
    else:
        f = base / f"{phase}-{key}.md"
        f.write_text(f"# {phase} {key}\nreal evidence content\n", encoding="utf-8")
    return str(f.relative_to(repo))


def test_start_then_drive_to_verified_with_real_artifacts_terminates(tmp_path):
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    assert code == 0
    state_path = res["run_state"]
    steps = 0
    nres = {"complete": False}
    while steps < 50:
        steps += 1
        code, nres = _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
        if nres["complete"]:
            break
        phase = nres["blocked_phase"]
        for key in nres["next_action"]["expected_outputs"]:
            rel = _make_artifact(tmp_path, phase, key)
            _run("submit", "--state", state_path, "--phase", phase,
                 "--key", key, "--path", rel, "--repo", str(tmp_path), cwd=tmp_path)
    assert nres["complete"] is True
    assert nres["navigation_map"]["you_are_here"] == "VERIFIED"
    assert nres.get("delivery") == "COMPLETE"  # link ②: full-scope delivery labelled
    # No --tier => auto, which floors to `standard` (G4): the drive walks the
    # standard spine (adds PLANNED + REVIEWED) and terminates in 7 steps. The
    # bound stays tight to guard against a runaway loop / pipeline regression.
    assert steps <= 8


def test_fake_path_evidence_never_reaches_verified(tmp_path):
    """R1: a present-but-nonexistent evidence path must NOT drive the run to VERIFIED."""
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    state_path = res["run_state"]
    steps = 0
    nres = {"complete": False}
    while steps < 8:
        steps += 1
        code, nres = _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
        if nres["complete"]:
            break
        phase = nres["blocked_phase"]
        for key in nres["next_action"]["expected_outputs"]:
            _run("submit", "--state", state_path, "--phase", phase,
                 "--key", key, "--path", f"{phase}-{key}.md",  # FAKE: never created
                 "--repo", str(tmp_path), cwd=tmp_path)
    assert nres["complete"] is False
    assert nres["navigation_map"]["you_are_here"] != "VERIFIED"


def test_dispatch_returns_pointer_packet(tmp_path):
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    state_path = res["run_state"]
    _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
    code, dres = _run("dispatch", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
    assert dres["skill"] == "e2e-harness-clarification"
    assert dres["expected_outputs"] == ["clarification", "acceptance_contract"]


def test_dispatch_emits_worker_descriptor(tmp_path):
    """Dispatch emits a launchable worker request that inherits the runtime default model."""
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    state_path = res["run_state"]
    _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
    code, dres = _run("dispatch", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
    desc = dres["worker_descriptor"]
    assert desc["schema"] == "e2e-dev-harness.worker-descriptor.v1"
    assert desc["runtime"] == "codex"
    assert desc["tool"] == "multi_agent_v1.spawn_agent"
    assert desc["arguments"]["agent_type"] == "worker"
    assert desc["arguments"]["fork_context"] is False
    assert "model" not in desc["arguments"]
    assert "message" in desc["arguments"]
    assert desc["expected_outputs"] == dres["expected_outputs"]


def test_dispatch_runtime_manual_yields_manual_descriptor(tmp_path):
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    state_path = res["run_state"]
    _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
    code, dres = _run("dispatch", "--state", state_path, "--repo", str(tmp_path),
                      "--runtime", "manual", cwd=tmp_path)
    desc = dres["worker_descriptor"]
    assert desc["runtime"] == "manual"
    assert desc["tool"] is None


def test_dispatch_runtime_opencode_yields_task_descriptor(tmp_path):
    """`--runtime opencode` emits an opencode task descriptor (no model pin)."""
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    state_path = res["run_state"]
    _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
    code, dres = _run("dispatch", "--state", state_path, "--repo", str(tmp_path),
                      "--runtime", "opencode", cwd=tmp_path)
    desc = dres["worker_descriptor"]
    assert desc["runtime"] == "opencode"
    assert desc["tool"] == "task"
    assert desc["arguments"]["subagent_type"] == "general-purpose"
    assert "model" not in desc["arguments"]
    assert "prompt" in desc["arguments"]
    assert desc["expected_outputs"] == dres["expected_outputs"]


def test_gate_verb_rejects_fake_artifact_accepts_real(tmp_path):
    """R1 at the `gate` verb directly: a fake artifact fails the gate (exit 1),
    a real one passes (exit 0)."""
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    state_path = res["run_state"]
    _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)  # -> CLARIFIED

    # fake evidence path that is never created
    _run("submit", "--state", state_path, "--phase", "CLARIFIED",
         "--key", "clarification", "--path", "CLARIFIED-clarification.md",
         "--repo", str(tmp_path), cwd=tmp_path)
    code, gres = _run("gate", "--state", state_path, "--phase", "CLARIFIED",
                      "--repo", str(tmp_path), cwd=tmp_path)
    assert code == 1
    assert gres["passed"] is False
    assert "clarification" in gres["missing_evidence"]

    # real artifacts for BOTH required keys at the same phase -> gate passes
    for k in ("clarification", "acceptance_contract"):
        rel = _make_artifact(tmp_path, "CLARIFIED", k)
        _run("submit", "--state", state_path, "--phase", "CLARIFIED",
             "--key", k, "--path", rel, "--repo", str(tmp_path), cwd=tmp_path)
    code, gres = _run("gate", "--state", state_path, "--phase", "CLARIFIED",
                      "--repo", str(tmp_path), cwd=tmp_path)
    assert code == 0
    assert gres["passed"] is True
    assert gres["missing_evidence"] == []
