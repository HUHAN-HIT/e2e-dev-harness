"""Module-fanout dispatch (B3): the parallel half of progressive parallel dev.

When the run is at a module-scoped phase and the ready frontier holds >=2
independent modules, `dispatch` emits one worker per module concurrently. When a
module is still gated behind a dependency, the frontier is a single module and
dispatch stays single-worker — depends_on is honoured.
"""
import json
import types
from pathlib import Path

from e2e_harness.cli.commands import dispatch as dispatch_cmd
from e2e_harness.core import run_state, module_plan


def _args(state_path, repo):
    return types.SimpleNamespace(state=str(state_path), repo=str(repo),
                                 runtime="codex", team_profile=None, max_workers=None)


def _setup(repo, *modules):
    (repo / "mp.json").write_text(
        json.dumps({"schema": module_plan.SCHEMA, "modules": list(modules)}), encoding="utf-8")
    state = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")
    state["current_phase"] = "RED#auth"
    state["phases"] = {"PLANNED": {"evidence": {"module_plan": {"path": "mp.json"}}}}
    sp = repo / "docs" / "agent-runs" / "r1" / "run-state.json"
    sp.parent.mkdir(parents=True)
    sp.write_text(json.dumps(state), encoding="utf-8")
    return sp


def _mod(mid, deps=()):
    return {"id": mid, "name": f"{mid} svc", "depends_on": list(deps), "acceptance_ids": ["AC-001"]}


def test_dispatch_fans_out_independent_modules_in_parallel(tmp_path):
    sp = _setup(tmp_path, _mod("auth"), _mod("billing"))
    code, result = dispatch_cmd.run(_args(sp, tmp_path))
    assert code == 0
    assert result["agent_team_plan"]["execution_model"] == "module-fanout"
    ids = [d["worker_id"] for d in result["worker_descriptors"]]
    assert "RED#auth" in ids and "RED#billing" in ids
    outs = {d["worker_id"]: d["expected_outputs"] for d in result["worker_descriptors"]}
    assert outs["RED#auth"] == ["failing_tests#auth"]
    assert outs["RED#billing"] == ["failing_tests#billing"]


def test_dispatch_dependent_module_stays_single_worker(tmp_path):
    # billing depends on auth -> at RED#auth only auth is ready (serial, no fanout)
    sp = _setup(tmp_path, _mod("auth"), _mod("billing", deps=["auth"]))
    code, result = dispatch_cmd.run(_args(sp, tmp_path))
    assert code == 0
    assert result["agent_team_plan"]["execution_model"] == "single-worker"
    assert result["expected_outputs"] == ["failing_tests#auth"]
