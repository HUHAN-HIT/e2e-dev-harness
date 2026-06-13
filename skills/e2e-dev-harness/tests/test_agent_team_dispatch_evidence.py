"""F4 (re-anchored): the agent-team dispatch chain enters the audited VERIFIED gate
as a real `agent_team_dispatch` evidence key satisfied via `submit` — the worker
submits the dispatch-invocation.json (which dispatch.py already writes), exactly like
verification/audit_replay. Prose can no longer satisfy it; manual-runtime (a recorded
block) is accepted so an audited manual run is not permanently unsatisfiable."""
import json

from e2e_harness.adapters.evidence import validate


def _plan(tmp_path):
    p = tmp_path / "agent-team-plan.json"
    p.write_text(json.dumps({
        "schema": "e2e-dev-harness.agent-team-plan.v1",
        "workers": [{"id": "VERIFIED-w1", "role": "coverage-reviewer"}],
    }), encoding="utf-8")
    return p


def _invocation(tmp_path, **over):
    payload = {
        "schema": "e2e-dev-harness.dispatch-invocation.v1",
        "phase": "VERIFIED", "runtime": "codex",
        "team_plan_path": str(_plan(tmp_path)),
        "descriptors": [{"worker_id": "VERIFIED-w1"}], "blocked": [],
    }
    payload.update(over)
    return payload


def test_prose_agent_team_dispatch_rejected(tmp_path):
    (tmp_path / "d.md").write_text("dispatched the workers", encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "agent_team_dispatch", {"path": "d.md"})
    assert ok is False
    assert reason in {"not-json", "bad-schema"}


def test_invocation_without_descriptors_or_blocked_rejected(tmp_path):
    (tmp_path / "inv.json").write_text(
        json.dumps(_invocation(tmp_path, descriptors=[], blocked=[])), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "agent_team_dispatch", {"path": "inv.json"})
    assert ok is False
    assert "descriptors" in reason


def test_invocation_missing_team_plan_rejected(tmp_path):
    (tmp_path / "inv.json").write_text(
        json.dumps(_invocation(tmp_path, team_plan_path="ghost-plan.json")), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "agent_team_dispatch", {"path": "inv.json"})
    assert ok is False
    assert "team-plan" in reason


def test_genuine_invocation_passes(tmp_path):
    (tmp_path / "inv.json").write_text(json.dumps(_invocation(tmp_path)), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "agent_team_dispatch", {"path": "inv.json"})
    assert ok is True and reason is None


def test_manual_runtime_blocked_invocation_accepted(tmp_path):
    inv = _invocation(tmp_path, descriptors=[],
                      blocked=[{"reason": "manual_runtime_requires_human_dispatch"}])
    (tmp_path / "inv.json").write_text(json.dumps(inv), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "agent_team_dispatch", {"path": "inv.json"})
    assert ok is True and reason is None
