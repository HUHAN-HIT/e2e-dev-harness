import json
import subprocess
import sys
from pathlib import Path

from harness_v2.adapters.hooks import phase_guard_v2 as pg
from harness_v2.adapters.evidence import command_evidence as ce

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness_v2.py"


def _run(*args, cwd):
    proc = subprocess.run([sys.executable, str(ENTRY), *args],
                          cwd=cwd, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout or "{}")


def _make_artifact(repo: Path, phase: str, key: str) -> str:
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


def _code_write_hook(repo: Path) -> str:
    return json.dumps({"tool_name": "Write",
                       "tool_input": {"file_path": str(repo / "src" / "feature.py"),
                                      "content": "print('x')"}})


def test_phase_guard_blocks_early_then_allows_at_implemented(tmp_path):
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    assert code == 0
    state_path = res["run_state"]

    # 1) Fresh run sits before IMPLEMENTED: a code write is denied.
    d = pg.decide(_code_write_hook(tmp_path), tmp_path, state_path)
    assert d["decision"] == "deny", d

    # 2) Drive the run via real gates until current_phase == IMPLEMENTED.
    from harness_v2.core import run_state
    reached_impl = False
    for _ in range(50):
        if pipeline_can_write(state_path):
            reached_impl = True
            break
        code, nres = _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
        if nres.get("complete"):
            break
        phase = nres["blocked_phase"]
        for key in nres["next_action"]["expected_outputs"]:
            rel = _make_artifact(tmp_path, phase, key)
            _run("submit", "--state", state_path, "--phase", phase,
                 "--key", key, "--path", rel, "--repo", str(tmp_path), cwd=tmp_path)
    assert reached_impl, "run never reached a code-write phase"

    # 3) Same code write is now allowed.
    d = pg.decide(_code_write_hook(tmp_path), tmp_path, state_path)
    assert d["decision"] == "allow", d


def pipeline_can_write(state_path):
    from harness_v2 import pipeline
    from harness_v2.core import run_state
    return pipeline.can_write_code(run_state.load(state_path))
