from types import SimpleNamespace
import json

from e2e_harness.core import run_state
from e2e_harness.cli.commands import approve_impact_degradation as cmd


def test_records_run_state_approval(tmp_path):
    run_dir = tmp_path / "docs" / "agent-runs" / "r1"
    run_dir.mkdir(parents=True)
    state_path = run_dir / "run-state.json"
    st = run_state.new_run_state("r1", "f", "req", tier="critical", pipeline="critical")
    run_state.save(state_path, st)
    approval = run_dir / "gitnexus-degradation.json"
    approval.write_text(json.dumps({
        "schema": "e2e-dev-harness.impact-degradation-approval.v1",
        "approval": "user-approved",
        "reason": "GitNexus unavailable",
        "fallback_evidence": ["manual review"],
    }), encoding="utf-8")

    args = SimpleNamespace(state=str(state_path), approval=str(approval), reason="env has no gitnexus")
    code, result = cmd.run(args)
    assert code == 0
    saved = run_state.load(state_path)
    block = saved["approvals"]["impact_degradation"]
    assert block["source"] == "user-approved"
    assert block["recorded_by"] == "coordinator"
    assert len(block["sha256"]) == 64


def test_rejects_missing_approval_markers(tmp_path):
    run_dir = tmp_path / "docs" / "agent-runs" / "r1"
    run_dir.mkdir(parents=True)
    state_path = run_dir / "run-state.json"
    run_state.save(state_path, run_state.new_run_state("r1", "f", "req"))
    approval = run_dir / "bad.md"
    approval.write_text("nope", encoding="utf-8")
    args = SimpleNamespace(state=str(state_path), approval=str(approval), reason="x")
    code, result = cmd.run(args)
    assert code == 2 and "error" in result


def test_rejects_markdown_approval_file(tmp_path):
    run_dir = tmp_path / "docs" / "agent-runs" / "r1"
    run_dir.mkdir(parents=True)
    state_path = run_dir / "run-state.json"
    run_state.save(state_path, run_state.new_run_state("r1", "f", "req"))
    approval = run_dir / "gitnexus-degradation.md"
    approval.write_text("Approval: user-approved\nReason: GitNexus unavailable\n"
                        "Fallback Evidence: manual review\n", encoding="utf-8")
    args = SimpleNamespace(state=str(state_path), approval=str(approval), reason="x")
    code, result = cmd.run(args)
    assert code == 2
    assert "json" in result["error"].lower()


def test_rejects_missing_approval_file(tmp_path):
    run_dir = tmp_path / "docs" / "agent-runs" / "r1"
    run_dir.mkdir(parents=True)
    state_path = run_dir / "run-state.json"
    run_state.save(state_path, run_state.new_run_state("r1", "f", "req"))
    args = SimpleNamespace(state=str(state_path), approval=str(run_dir / "nope.md"), reason="x")
    code, result = cmd.run(args)
    assert code == 2 and "error" in result


def test_reason_comes_from_hashed_json_not_cli_override(tmp_path):
    """Degradation reason must come from the sha256-anchored approval JSON, not a
    CLI override, else the audit reason drifts from what's hashed (finding P2)."""
    run_dir = tmp_path / "docs" / "agent-runs" / "r1"
    run_dir.mkdir(parents=True)
    state_path = run_dir / "run-state.json"
    run_state.save(state_path, run_state.new_run_state(
        "r1", "f", "req", tier="critical", pipeline="critical"))
    approval = run_dir / "gitnexus-degradation.json"
    approval.write_text(json.dumps({
        "schema": "e2e-dev-harness.impact-degradation-approval.v1",
        "approval": "user-approved",
        "reason": "GitNexus unavailable",
        "fallback_evidence": ["manual review"],
    }), encoding="utf-8")
    # Even if a CLI reason is still passed (legacy caller), it must be IGNORED.
    args = SimpleNamespace(state=str(state_path), approval=str(approval),
                           reason="OVERRIDE that must be ignored")
    code, result = cmd.run(args)
    assert code == 0
    block = run_state.load(state_path)["approvals"]["impact_degradation"]
    assert block["reason"] == "GitNexus unavailable"
    assert len(block["sha256"]) == 64
