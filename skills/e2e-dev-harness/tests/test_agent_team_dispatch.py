import json
from pathlib import Path

from e2e_harness import pipeline
from e2e_harness.cli.commands import dispatch as dispatch_cmd
from e2e_harness.core import engine, run_state


class Args:
    def __init__(self, state, runtime="codex", team_profile=None, max_workers=None):
        self.state = state
        self.runtime = runtime
        self.team_profile = team_profile
        self.max_workers = max_workers


def _write_state(tmp_path, *, tier="standard", phase="PLANNED"):
    state = run_state.new_run_state("r1", "feature", "request", tier=tier, pipeline=tier)
    state["current_phase"] = phase
    path = tmp_path / "docs" / "agent-runs" / "r1" / "run-state.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def test_dispatch_preserves_legacy_single_worker_shape(tmp_path):
    path = _write_state(tmp_path, tier="standard", phase="PLANNED")

    code, result = dispatch_cmd.run(Args(path))

    assert code == 0
    assert result["schema"] == "e2e-dev-harness.worker-packet.v1"
    assert result["role"] == "implementation-planner"
    assert result["skill"] == "e2e-harness-planning"
    assert result["expected_outputs"] == ["plan", "module_plan"]
    assert result["worker_descriptor"]["runtime"] == "codex"
    assert result["agent_team_plan"]["execution_model"] == "single-worker"


def test_critical_review_dispatch_emits_three_descriptors_and_artifacts(tmp_path):
    path = _write_state(tmp_path, tier="critical", phase="REVIEWED")

    code, result = dispatch_cmd.run(Args(path, runtime="opencode"))

    assert code == 0
    assert result["agent_team_plan"]["execution_model"] == "reviewer-fanout"
    assert [item["worker_id"] for item in result["worker_descriptors"]] == [
        "REVIEWED-r1",
        "REVIEWED-r2",
        "REVIEWED-r3",
    ]
    assert [item["descriptor"]["expected_outputs"] for item in result["worker_descriptors"]] == [
        ["r1_review"],
        ["r2_review"],
        ["r3_review"],
    ]
    run_dir = path.parent
    assert (run_dir / "agent-team-plan.json").is_file()
    assert list((run_dir / "dispatch-invocations").glob("REVIEWED-*.json"))


def test_custom_pipeline_dispatch_falls_back_to_tier_profile(tmp_path):
    path = _write_state(tmp_path, tier="critical", phase="REVIEWED")
    state = json.loads(path.read_text(encoding="utf-8"))
    state["pipeline"] = str(tmp_path / "custom.yaml")
    state["pipeline_spec"] = {
        "name": "custom",
        "phases": [
            "CREATED",
            "CLARIFIED",
            "PLANNED",
            "RED",
            "IMPLEMENTED",
            "REVIEWED",
            "VERIFIED",
        ],
    }
    path.write_text(json.dumps(state), encoding="utf-8")

    code, result = dispatch_cmd.run(Args(path, runtime="codex"))

    assert code == 0
    assert result["agent_team_plan"]["profile"] == "default-critical"
    assert len(result["worker_descriptors"]) == 3


def test_adversarial_pipeline_dispatch_auto_selects_adversarial_profile(tmp_path):
    """start --pipeline adversarial must auto-pair default-adversarial so the
    coordinator receives three isolated perspective reviewers without an explicit
    --team-profile, mirroring how critical/audited auto-select their fan-out."""
    state = run_state.new_run_state(
        "r1", "feature", "request", tier="standard", pipeline="adversarial")
    state["current_phase"] = "REVIEWED"
    path = tmp_path / "docs" / "agent-runs" / "r1" / "run-state.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(state), encoding="utf-8")

    code, result = dispatch_cmd.run(Args(path, runtime="codex"))

    assert code == 0
    assert result["agent_team_plan"]["profile"] == "default-adversarial"
    assert result["agent_team_plan"]["execution_model"] == "reviewer-fanout"
    assert [item["worker_id"] for item in result["worker_descriptors"]] == [
        "REVIEWED-code", "REVIEWED-design", "REVIEWED-tests"]
    assert [item["descriptor"]["expected_outputs"] for item in result["worker_descriptors"]] == [
        ["adversarial_code_review"],
        ["adversarial_design_review"],
        ["adversarial_test_design_review"],
    ]


def test_manual_runtime_blocks_without_marking_dispatched(tmp_path):
    path = _write_state(tmp_path, tier="critical", phase="REVIEWED")

    code, result = dispatch_cmd.run(Args(path, runtime="manual", max_workers=3))

    assert code == 3
    assert result["dispatch_blocked"]["reason"] == "manual_runtime_requires_human_dispatch"
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["phases"].get("REVIEWED", {}).get("dispatch") is None
    assert result["agent_team_plan"]["execution_model"] == "reviewer-fanout"
    assert len(result["worker_descriptors"]) == 3
