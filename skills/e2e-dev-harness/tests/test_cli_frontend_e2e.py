"""End-to-end: a frontend fixture repo is auto-detected and driven to VERIFIED
via the same CLI verbs as backend, proving the DomainAdapter seam carries a
non-backend domain through start -> next -> submit with no core changes."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness.py"
FIX = Path(__file__).resolve().parent / "fixtures" / "frontend_app"


def _run(*a, cwd):
    p = subprocess.run([sys.executable, str(ENTRY), *a], cwd=cwd, capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout or "{}")


def _artifact(repo: Path, phase: str, key: str) -> str:
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
    if key == "module_plan":
        import json as _json
        from e2e_harness.core import module_plan as _mp
        f = base / f"{phase}-{key}.json"
        f.write_text(_json.dumps({"schema": _mp.SCHEMA, "modules": [
            {"id": "core", "name": "Core", "depends_on": [], "acceptance_ids": ["AC-001"]}]}), encoding="utf-8")
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
        f.write_text("real\n", encoding="utf-8")
    return str(f.relative_to(repo))


def test_frontend_repo_drives_to_verified(tmp_path):
    for item in FIX.iterdir():
        dst = tmp_path / item.name
        shutil.copytree(item, dst) if item.is_dir() else shutil.copy(item, dst)

    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    assert code == 0 and res["domain"] == "frontend"

    state = res["run_state"]
    # the non-backend domain block is embedded in run-state (Task 4 embed)
    embedded = json.loads(Path(state).read_text(encoding="utf-8"))
    assert embedded["domain"]["name"] == "frontend"
    assert embedded["domain"]["test_runner"] == "vitest"

    steps = 0
    nres = {"complete": False}
    while steps < 50:
        steps += 1
        _, nres = _run("next", "--state", state, "--repo", str(tmp_path), cwd=tmp_path)
        if nres["complete"]:
            break
        phase = nres["blocked_phase"]
        for key in nres["next_action"]["expected_outputs"]:
            _run("submit", "--state", state, "--phase", phase, "--key", key,
                 "--path", _artifact(tmp_path, phase, key), "--repo", str(tmp_path), cwd=tmp_path)
    assert nres["complete"] is True
    assert nres["navigation_map"]["you_are_here"] == "VERIFIED"
    # No --tier => auto, floored to `standard` (G4): the standard spine adds
    # PLANNED + REVIEWED, so termination is 7 steps. Bound stays tight.
    assert steps <= 8
