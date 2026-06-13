"""Band dispatch marks each frontier track's ledger entry (not just current_phase)."""
import json
import types

from e2e_harness.cli.commands import dispatch as dispatch_cmd
from e2e_harness.core import run_state, module_plan


def _args(state_path, repo):
    return types.SimpleNamespace(state=str(state_path), repo=str(repo),
                                 runtime="codex", team_profile=None, max_workers=None)


def _mod(mid, deps=()):
    return {"id": mid, "name": f"{mid} svc", "depends_on": list(deps), "acceptance_ids": ["AC-001"]}


def _band_state(repo, *mods):
    (repo / "mp.json").write_text(
        json.dumps({"schema": module_plan.SCHEMA, "modules": list(mods)}), encoding="utf-8")
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")
    st["region"] = "module_band"
    st["current_phase"] = "RED#auth"
    st["tracks"] = {
        "auth": {"module_id": "auth", "current_phase": "RED#auth", "dispatch": "pending",
                 "depends_on": [], "complete": False},
        "reports": {"module_id": "reports", "current_phase": "RED#reports", "dispatch": "pending",
                    "depends_on": [], "complete": False},
    }
    st["phases"] = {"PLANNED": {"evidence": {"module_plan": {"path": "mp.json"}}}}
    sp = repo / "docs" / "agent-runs" / "r1" / "run-state.json"
    sp.parent.mkdir(parents=True)
    sp.write_text(json.dumps(st), encoding="utf-8")
    return sp


def test_band_dispatch_marks_every_frontier_track(tmp_path):
    sp = _band_state(tmp_path, _mod("auth"), _mod("reports"))
    code, result = dispatch_cmd.run(_args(sp, tmp_path))
    assert code == 0
    assert result["agent_team_plan"]["execution_model"] == "module-fanout"
    saved = run_state.load(sp)
    assert saved["tracks"]["auth"]["dispatch"] == "dispatched"
    assert saved["tracks"]["reports"]["dispatch"] == "dispatched"


def test_non_band_dispatch_keeps_legacy_marking(tmp_path):
    # no tracks/region -> the legacy current_phase dispatch marking, unchanged
    (tmp_path / "mp.json").write_text(
        json.dumps({"schema": module_plan.SCHEMA, "modules": [_mod("auth"), _mod("billing", deps=["auth"])]}),
        encoding="utf-8")
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")
    st["current_phase"] = "RED#auth"
    st["phases"] = {"PLANNED": {"evidence": {"module_plan": {"path": "mp.json"}}}}
    sp = tmp_path / "docs" / "agent-runs" / "r1" / "run-state.json"
    sp.parent.mkdir(parents=True)
    sp.write_text(json.dumps(st), encoding="utf-8")
    code, _ = dispatch_cmd.run(_args(sp, tmp_path))
    assert code == 0
    saved = run_state.load(sp)
    assert saved["phases"]["RED#auth"]["dispatch"] == "dispatched"
    assert "tracks" not in saved
