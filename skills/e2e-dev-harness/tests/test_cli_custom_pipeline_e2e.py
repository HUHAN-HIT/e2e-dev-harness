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
    from e2e_harness.adapters.evidence import command_evidence as ce
    base = repo / "docs" / "agent-runs" / "art"
    base.mkdir(parents=True, exist_ok=True)
    if key in ("failing_tests", "passing_tests"):
        code = 1 if key == "failing_tests" else 0
        ev = ce.record_command(repo, f'"{sys.executable}" -c "import sys; sys.exit({code})"')
        f = base / f"{phase}-{key}.json"
        f.write_text(json.dumps(ev), encoding="utf-8")
    else:
        f = base / f"{phase}-{key}.md"
        f.write_text(f"# {phase} {key}\nreal\n", encoding="utf-8")
    return str(f.relative_to(repo))


def test_custom_pipeline_drives_to_verified(tmp_path):
    custom = tmp_path / "custom.yaml"
    custom.write_text("name: c\nphases: [CREATED, CLARIFIED, VERIFIED]\n", encoding="utf-8")
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", "--pipeline", str(custom), cwd=tmp_path)
    assert code == 0
    state_path = res["run_state"]
    # run-state is hermetic: it embedded the resolved spec
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    assert state["pipeline_spec"]["phases"] == ["CREATED", "CLARIFIED", "VERIFIED"]

    steps = 0
    nres = {"complete": False}
    while steps < 10:
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


def test_unsatisfiable_custom_pipeline_rejected_at_start_no_run_state(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "name: b\nphases:\n  - CREATED\n  - phase: CLARIFIED\n    exit_gate: [clarification, ghost]\n  - VERIFIED\n",
        encoding="utf-8")
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", "--pipeline", str(bad), cwd=tmp_path)
    assert code != 0
    assert res.get("error") == "invalid pipeline"
    assert any("ghost" in e for e in res["errors"])
    # no run-state was written
    assert not list((tmp_path / "docs" / "agent-runs").glob("*/run-state.json"))


def test_builtin_start_records_name_not_spec(tmp_path):
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", "--tier", "standard", cwd=tmp_path)
    assert code == 0
    state = json.loads(Path(res["run_state"]).read_text(encoding="utf-8"))
    assert state["pipeline"] == "standard"
    assert "pipeline_spec" not in state  # built-ins stay lean
