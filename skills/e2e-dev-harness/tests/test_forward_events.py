"""Slice 1: forward-path event emission, switched at run creation.

Emission is a per-run property fixed at `start`: unset E2E_HARNESS_DISABLE_EVENTS
lays down `events.jsonl` (+ `.head`) seeded from `run.started`; the four forward
commands (dispatch/next/submit/migrate) then extend the chain IFF that sibling
already exists. An old run (no sibling) or an opted-out run stays event-free, so a
forward command never produces a partial mid-run chain (which would read as drift).

The end-to-end invariant: at every point of a real run, `verify_chain` passes and
`detect_drift(chain, run-state)` is clean — the witness is a faithful projection.
"""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from e2e_harness.core import run_state, event_log, state_store

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness.py"


def _start(tmp_path, **over):
    from e2e_harness.cli.commands import start
    # tier="auto" mirrors the CLI's --tier default (recommend_tier's contract).
    kw = dict(repo=str(tmp_path), feature="demo", request="do x", tier="auto")
    kw.update(over)
    code, res = start.run(SimpleNamespace(**kw))
    assert code == 0, res
    return Path(res["run_state"])


def _assert_chain_matches_state(state_path):
    """The Slice 1 invariant at any point: chain verifies AND replays to exactly
    the run-state projectable fields."""
    events_path = run_state.events_path_for(state_path)
    ok, why = event_log.verify_chain(events_path)
    assert ok, why
    ok, why = state_store.detect_drift(event_log.read_events(events_path),
                                       run_state.load(state_path))
    assert ok, why


# --- the forward-path emission switch: events_path_if_active ------------------


def test_events_path_if_active_returns_path_when_log_exists(tmp_path):
    sp = tmp_path / "run-state.json"
    ev = run_state.events_path_for(sp)
    ev.write_text("", encoding="utf-8")
    assert run_state.events_path_if_active(sp) == ev


def test_events_path_if_active_returns_none_when_log_absent(tmp_path):
    sp = tmp_path / "run-state.json"
    assert run_state.events_path_if_active(sp) is None


# --- start seeds the chain (default) / opts out (env) ------------------------


def test_start_seeds_events_log_with_run_started(tmp_path):
    sp = _start(tmp_path)
    events_path = run_state.events_path_for(sp)
    assert events_path.exists()
    assert (tmp_path_anchor := Path(str(events_path) + ".head")).exists(), tmp_path_anchor
    types = [e["type"] for e in event_log.read_events(events_path)]
    assert types[0] == "run.started"
    # seeded with the full initial transition so the projection already carries
    # current_phase=CREATED — no false current_phase drift before the first `next`.
    assert "phase.submitted" in types
    _assert_chain_matches_state(sp)


def test_start_disable_events_creates_no_log(tmp_path, monkeypatch):
    monkeypatch.setenv("E2E_HARNESS_DISABLE_EVENTS", "1")
    sp = _start(tmp_path)
    assert not run_state.events_path_for(sp).exists()
    # run-state itself is unaffected — the run is simply permanently event-free.
    assert run_state.load(sp)["current_phase"] == "CREATED"


# --- forward commands extend an existing chain; skip an absent one ------------


def test_next_extends_chain_and_stays_clean(tmp_path):
    sp = _start(tmp_path)
    from e2e_harness.cli.commands import next as next_cmd
    next_cmd.run(SimpleNamespace(state=str(sp), repo=str(tmp_path)))
    types = [e["type"] for e in event_log.read_events(run_state.events_path_for(sp))]
    # the advance CREATED -> CLARIFIED appended a phase.submitted for CLARIFIED
    assert types.count("phase.submitted") >= 2
    _assert_chain_matches_state(sp)


def test_dispatch_appends_dispatch_dispatched(tmp_path):
    sp = _start(tmp_path)
    from e2e_harness.cli.commands import next as next_cmd, dispatch as dispatch_cmd
    next_cmd.run(SimpleNamespace(state=str(sp), repo=str(tmp_path)))     # -> CLARIFIED
    code, _ = dispatch_cmd.run(SimpleNamespace(state=str(sp), repo=str(tmp_path)))
    assert code == 0
    types = [e["type"] for e in event_log.read_events(run_state.events_path_for(sp))]
    assert "dispatch.dispatched" in types
    _assert_chain_matches_state(sp)


def test_old_run_without_log_skips_emission(tmp_path):
    """Old-run upgrade: a run created before Phase 1 has no events.jsonl; a forward
    command must skip emission rather than start a partial mid-run chain."""
    sp = tmp_path / "run-state.json"
    st = run_state.new_run_state("r-old", "feat", "req")
    st["current_phase"] = "CREATED"
    run_state.save(sp, st)
    assert not run_state.events_path_for(sp).exists()
    from e2e_harness.cli.commands import next as next_cmd
    next_cmd.run(SimpleNamespace(state=str(sp), repo=str(tmp_path)))
    assert not run_state.events_path_for(sp).exists()   # still no sidecar


# --- the end-to-end invariant across a full CLI drive ------------------------


def _run(*args, cwd):
    proc = subprocess.run([sys.executable, str(ENTRY), *args],
                          cwd=cwd, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout or "{}")


def test_full_drive_keeps_chain_clean(tmp_path):
    """A real start->next->submit drive to VERIFIED must leave a chain that both
    verifies and replays to the run-state projectable fields with zero drift."""
    from test_cli_e2e import _make_artifact
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
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
    _assert_chain_matches_state(state_path)
    # the chain genuinely recorded the run, not just an empty seed.
    types = [e["type"] for e in event_log.read_events(run_state.events_path_for(state_path))]
    assert types[0] == "run.started"
    assert "gate.passed" in types
