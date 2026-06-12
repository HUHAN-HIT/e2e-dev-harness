"""G3: gate evaluation must be side-effect-free on read-only paths.

The verification REPLAY (re-running the recorded command) fires only on the
advance/gate path (skip_replay=False, the default). Read-only paths
(status -> navigation_map, default skip_replay=True) judge by the recorded
exit code and never re-execute.
"""
import json
import sys
from pathlib import Path

from e2e_harness.adapters.evidence import command_evidence
from e2e_harness.core import gates, navigation
from e2e_harness.core.lifecycle import Phase
from e2e_harness import pipeline


def _verification_phase():
    return Phase("VERIFIED", "coverage-reviewer", "e2e-harness-completion",
                 ("verification",), ("verification",), None)


def _genuine_verification(tmp_path):
    """Genuine exit-0 command-evidence whose command writes a sentinel.

    The recorded command is an *allowlisted* test runner (`python -m pytest`)
    so the advance/gate path is permitted to replay it (a bare `python -c ...`
    is rejected by the replay allowlist, by design). Running it executes a tiny
    pytest file that writes the sentinel, so a replay is observable. Recorded
    once, then the sentinel is cleared, so any re-creation proves a replay
    actually fired."""
    sentinel = (tmp_path / "SIDE_EFFECT.txt").as_posix()
    test_file = tmp_path / "test_sentinel_side_effect.py"
    test_file.write_text(
        "def test_writes_sentinel():\n"
        f"    open({sentinel!r}, 'w').write('ran')\n",
        encoding="utf-8",
    )
    exe = sys.executable.replace("\\", "/")
    cmd = f'"{exe}" -m pytest -q "{test_file.as_posix()}"'
    ev = command_evidence.record_command(tmp_path, cmd)
    assert ev["exit_code"] == 0
    (tmp_path / "verification.json").write_text(json.dumps(ev), encoding="utf-8")
    Path(sentinel).unlink(missing_ok=True)
    rec = {"evidence": {"verification": {"path": "verification.json"}}}
    return rec, sentinel


def test_skip_replay_true_does_not_execute(tmp_path):
    rec, sentinel = _genuine_verification(tmp_path)
    ok, missing = gates.gate_passes(_verification_phase(), rec, tmp_path, skip_replay=True)
    assert ok and missing == []          # passes on recorded exit 0
    assert not Path(sentinel).is_file()  # but command NOT re-run


def test_skip_replay_false_executes(tmp_path):
    rec, sentinel = _genuine_verification(tmp_path)
    ok, missing = gates.gate_passes(_verification_phase(), rec, tmp_path, skip_replay=False)
    assert ok and missing == []
    assert Path(sentinel).is_file()      # advance path DID replay


def test_navigation_map_is_side_effect_free(tmp_path):
    """status -> navigation_map (default skip_replay=True) must never replay."""
    rec, sentinel = _genuine_verification(tmp_path)
    state = {
        "schema": "e2e-dev-harness.run-state.v1",
        "pipeline": "minimal",
        "current_phase": "VERIFIED",
        "phases": {"VERIFIED": rec},
    }
    spine = pipeline.spine_for_state(state)
    navigation.navigation_map(spine, state, tmp_path)
    assert not Path(sentinel).is_file()
