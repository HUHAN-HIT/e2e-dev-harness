"""dispatch.run transports the impact-assessment path into the worker packet's
context_paths, gated by phase + artifact status. Transport only — never interpreted.
"""
import json
from types import SimpleNamespace

from e2e_harness.core import run_state
from e2e_harness.cli.commands import dispatch as dispatch_cmd


def _mk(tmp_path, current_phase, status):
    run_dir = tmp_path / "docs" / "agent-runs" / "r1"
    run_dir.mkdir(parents=True)
    art = run_dir / "impact-assessment.json"
    art.write_text(json.dumps({"schema": "e2e-dev-harness.impact-assessment.v1",
                               "status": status, "seeds": [], "impact": [],
                               "open_questions": []}), encoding="utf-8")
    st = run_state.new_run_state("r1", "feat", "change the planner", tier="standard",
                                 pipeline="standard")
    st["current_phase"] = current_phase
    st["impact"] = {"mode": "auto"}
    st["impact_assessment"] = {"status": status,
                               "path": str(art.relative_to(tmp_path))}   # repo-relative
    state_path = run_dir / "run-state.json"
    run_state.save(state_path, st)
    return state_path


def _args(state_path, tmp_path):
    return SimpleNamespace(state=str(state_path), repo=str(tmp_path), runtime="codex",
                           team_profile=None, max_workers=None, json=False)


def _has_impact(packet):
    return any("impact-assessment.json" in c for c in packet["context_paths"])


def test_planned_verified_includes_impact_path(tmp_path):
    code, packet = dispatch_cmd.run(_args(_mk(tmp_path, "PLANNED", "verified"), tmp_path))
    assert code == 0
    assert _has_impact(packet)


def test_clarified_blocked_includes_impact_path(tmp_path):
    code, packet = dispatch_cmd.run(_args(_mk(tmp_path, "CLARIFIED", "blocked"), tmp_path))
    assert code == 0
    assert _has_impact(packet)


def test_clarified_verified_excludes_impact_path(tmp_path):
    # CLARIFIED only surfaces a *blocked* impact (for re-clarification), not verified.
    code, packet = dispatch_cmd.run(_args(_mk(tmp_path, "CLARIFIED", "verified"), tmp_path))
    assert code == 0
    assert not _has_impact(packet)


def test_no_binding_unchanged(tmp_path):
    run_dir = tmp_path / "docs" / "agent-runs" / "r1"
    run_dir.mkdir(parents=True)
    st = run_state.new_run_state("r1", "feat", "q", tier="standard", pipeline="standard")
    st["current_phase"] = "PLANNED"
    state_path = run_dir / "run-state.json"
    run_state.save(state_path, st)
    code, packet = dispatch_cmd.run(_args(state_path, tmp_path))
    assert code == 0
    assert not _has_impact(packet)
