"""Gap 4 (c) + P1 — no-auto-spawn dispatch is explicitly blocked (not silently
marked DISPATCHED), and the dispatch default runtime is codex.

(c): a runtime whose capabilities().can_auto_spawn is False must NOT let the
coordinator self-deal (mark DISPATCHED + 'run it yourself'); dispatch returns an
explicit blocked result (non-zero exit + dispatch_blocked) and leaves the phase
in its implicit PENDING state — without resurrecting a WAITING_DISPATCH enum
member (that overlapping state was deliberately removed in the 2026-06-07 redesign).

P1: the dispatch command's default runtime is codex (seam/argparse default), not
the stale 'claude-code' getattr fallback.
"""
import json
import subprocess
import sys
import types
from pathlib import Path

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness.py"


def _run(*args, cwd):
    proc = subprocess.run([sys.executable, str(ENTRY), *args],
                          cwd=cwd, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout or "{}")


def _start_and_advance(tmp_path):
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    state_path = res["run_state"]
    _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
    return state_path


def test_manual_runtime_blocks_dispatch_without_marking_dispatched(tmp_path):
    state_path = _start_and_advance(tmp_path)
    code, dres = _run("dispatch", "--state", state_path, "--repo", str(tmp_path),
                      "--runtime", "manual", cwd=tmp_path)
    assert code != 0
    assert dres["dispatch_blocked"]["reason"] == "manual_runtime_requires_human_dispatch"
    # descriptor still emitted (tells the human/coordinator what to run)
    assert dres["worker_descriptor"]["runtime"] == "manual"
    # phase NOT marked dispatched (stays implicit PENDING)
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    cur = state["current_phase"]
    assert state["phases"].get(cur, {}).get("dispatch") != "dispatched"


def test_codex_runtime_still_marks_dispatched(tmp_path):
    state_path = _start_and_advance(tmp_path)
    code, dres = _run("dispatch", "--state", state_path, "--repo", str(tmp_path),
                      "--runtime", "codex", cwd=tmp_path)
    assert code == 0
    assert "dispatch_blocked" not in dres
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    cur = state["current_phase"]
    assert state["phases"][cur]["dispatch"] == "dispatched"


def test_dispatch_default_runtime_is_codex_not_claude_code(tmp_path, monkeypatch):
    # P1: a programmatic call with no `runtime` attr must default to codex.
    state_path = _start_and_advance(tmp_path)
    monkeypatch.chdir(tmp_path)
    from e2e_harness.cli.commands import dispatch as dispatch_cmd
    code, res = dispatch_cmd.run(types.SimpleNamespace(state=state_path))
    assert res["worker_descriptor"]["runtime"] == "codex"
