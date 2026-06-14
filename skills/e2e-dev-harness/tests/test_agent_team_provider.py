from pathlib import Path

from e2e_harness import pipeline
from e2e_harness.adapters.agent_team import builtin
from e2e_harness.core import dispatch


def _request(phase, tmp_path: Path, **overrides):
    request = {
        "schema": "e2e-dev-harness.agent-team-request.v1",
        "run_state_path": "docs/agent-runs/r1/run-state.json",
        "repo_root": str(tmp_path),
        "runtime": "codex",
        "pipeline": "standard",
        "phase": {
            "name": phase.name,
            "worker_role": phase.worker_role,
            "worker_skill": phase.worker_skill,
            "produces": list(phase.produces),
            "exit_gate": list(phase.exit_gate),
            "allows_code_write": phase.allows_code_write,
        },
        "context_paths": ["docs/agent-runs/r1/run-state.json"],
        "team_profile": "default-standard",
        "constraints": {"max_workers": 1, "fresh_context": True, "allow_code_write": False},
    }
    request.update(overrides)
    return request


def test_builtin_provider_matches_worker_packet_for_single_worker_phase(tmp_path):
    phase = next(p for p in pipeline.build_spine("standard") if p.name == "PLANNED")
    plan = builtin.BuiltinAgentTeamProvider().plan_phase(_request(phase, tmp_path))
    expected = dispatch.worker_packet(phase, "docs/agent-runs/r1/run-state.json")

    assert plan["schema"] == "e2e-dev-harness.agent-team-plan.v1"
    assert plan["provider"] == "builtin"
    assert plan["profile"] == "default-standard"
    assert plan["phase"] == "PLANNED"
    assert plan["execution_model"] == "single-worker"
    assert len(plan["workers"]) == 1
    worker = plan["workers"][0]
    assert worker["role"] == expected["role"]
    assert worker["skill"] == expected["skill"]
    assert worker["context_paths"] == expected["context_paths"]
    assert worker["expected_outputs"] == expected["expected_outputs"]
    assert worker["runtime_subagent_type"] == "implementation-planner"
    assert plan["evidence_contract"]["required_keys"] == expected["expected_outputs"]


def test_builtin_provider_is_pure_and_does_not_touch_run_state(tmp_path):
    phase = next(p for p in pipeline.build_spine("standard") if p.name == "PLANNED")
    run_state = tmp_path / "run-state.json"
    run_state.write_text('{"current_phase": "PLANNED"}', encoding="utf-8")
    before = run_state.read_text(encoding="utf-8")

    plan = builtin.BuiltinAgentTeamProvider().plan_phase(
        _request(phase, tmp_path, run_state_path=str(run_state))
    )

    assert plan["workers"]
    assert run_state.read_text(encoding="utf-8") == before


def test_critical_review_phase_fans_out_to_independent_reviewers(tmp_path):
    phase = next(p for p in pipeline.build_spine("critical") if p.name == "REVIEWED")
    plan = builtin.BuiltinAgentTeamProvider().plan_phase(
        _request(
            phase,
            tmp_path,
            pipeline="critical",
            team_profile="default-critical",
            constraints={"max_workers": 3, "fresh_context": True, "allow_code_write": False},
        )
    )

    assert plan["execution_model"] == "reviewer-fanout"
    assert [worker["id"] for worker in plan["workers"]] == [
        "REVIEWED-r1",
        "REVIEWED-r2",
        "REVIEWED-r3",
    ]
    assert [worker["expected_outputs"] for worker in plan["workers"]] == [
        ["r1_review"],
        ["r2_review"],
        ["r3_review"],
    ]
    assert plan["evidence_contract"]["producer_ids"] == [
        "REVIEWED-r1",
        "REVIEWED-r2",
        "REVIEWED-r3",
    ]
