import json
import subprocess
import sys
from pathlib import Path

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness_v2.py"


def _run(*args, cwd):
    proc = subprocess.run([sys.executable, str(ENTRY), *args],
                          cwd=cwd, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout or "{}")


def _make_artifact(repo: Path, phase: str, key: str) -> str:
    """Produce a REAL artifact for `key`; return its repo-relative path."""
    from harness_v2.adapters.evidence import command_evidence as ce
    base = repo / "docs" / "agent-runs" / "art"
    base.mkdir(parents=True, exist_ok=True)
    if key in ("failing_tests", "passing_tests"):
        code = 1 if key == "failing_tests" else 0
        ev = ce.record_command(repo, f'"{sys.executable}" -c "import sys; sys.exit({code})"')
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
    assert steps <= 6


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
    assert dres["expected_outputs"] == ["clarification"]
