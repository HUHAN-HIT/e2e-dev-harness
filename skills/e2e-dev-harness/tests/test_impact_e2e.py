"""End-to-end (in-process via the CLI command run() functions) proof of the
strict-mode impact gate: blocked -> re-clarify, amend contract -> verified ->
advance, and the PLANNED impact_refs requirement.

In-process (not subprocess) so the GitNexus provider can be monkeypatched — the
test never shells out to a real GitNexus.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from e2e_harness.cli.commands import start as start_cmd
from e2e_harness.cli.commands import next as next_cmd
from e2e_harness.cli.commands import submit as submit_cmd


class _FakeProvider:
    result = None

    def assess(self, repo, request):
        return _FakeProvider.result


def _blocked():
    return {"schema": "e2e-dev-harness.impact-assessment.v1", "status": "blocked",
            "seeds": [], "impact": [],
            "open_questions": [{"id": "IQ-001", "question": "Which handler owns checkout?",
                                "status": "open"}]}


def _verified():
    return {"schema": "e2e-dev-harness.impact-assessment.v1", "status": "verified",
            "tool": "gitnexus",
            "seeds": [{"kind": "symbol", "name": "checkout_handler",
                       "file_path": "c.py", "reason": "r"}],
            "impact": [{"seed": "checkout_handler", "direction": "upstream", "risk": "LOW",
                        "summary": {}, "affected_processes": [{"name": "run"}],
                        "affected_modules": []}],
            "open_questions": [], "degradation": None, "approval": None}


def _start_args(tmp_path, impact_mode="strict"):
    return SimpleNamespace(
        repo=str(tmp_path), feature="impactfeat", feature_file=None,
        request="modify the checkout API endpoint handler", request_file=None,
        adapter=None, tier="standard", scan=False, pipeline=None,
        preview_tier=False, language_profile=None, impact_mode=impact_mode)


def _next(tmp_path, state_path):
    return next_cmd.run(SimpleNamespace(state=str(state_path), repo=str(tmp_path)))


def _submit(tmp_path, state_path, phase, key, rel):
    return submit_cmd.run(SimpleNamespace(state=str(state_path), repo=str(tmp_path),
                                          phase=phase, key=key, path=rel,
                                          status="done", reason=None, worker_id=None))


def _write(repo: Path, run_dir: Path, name: str, obj) -> str:
    p = run_dir / name
    p.write_text(json.dumps(obj) if not isinstance(obj, str) else obj, encoding="utf-8")
    return str(p.relative_to(repo))


def _contract(seed_candidates, marker="v1"):
    return {"schema": "e2e-dev-harness.acceptance-contract.v1",
            "items": [{"id": "AC-001", "criterion": f"criterion {marker}",
                       "observable_behavior": "obs"}],
            "impact_seed_candidates": seed_candidates}


def test_strict_impact_gate_full_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "e2e_harness.adapters.impact.gitnexus.GitNexusImpactProvider", _FakeProvider)
    repo = tmp_path

    code, res = start_cmd.run(_start_args(tmp_path))
    assert code == 0
    state_path = Path(res["run_state"])
    run_dir = state_path.parent

    # 1) first next -> blocks at CLARIFIED (needs clarification + acceptance_contract)
    _code, nres = _next(tmp_path, state_path)
    assert nres["blocked_phase"] == "CLARIFIED"

    # 2) submit CLARIFIED evidence with seed candidates in the contract
    clar = _write(repo, run_dir, "clarification.md", "# clarified\n")
    contract = _write(repo, run_dir, "acceptance-contract.json",
                      _contract(["checkout_handler"], marker="v1"))
    _submit(tmp_path, state_path, "CLARIFIED", "clarification", clar)
    _submit(tmp_path, state_path, "CLARIFIED", "acceptance_contract", contract)

    # 3) impact BLOCKED -> engine keeps the run at CLARIFIED, surfacing IQ questions
    _FakeProvider.result = _blocked()
    _code, nres = _next(tmp_path, state_path)
    assert nres["blocked_phase"] == "CLARIFIED"
    assert any(q["id"] == "IQ-001" for q in nres.get("open_questions", []))

    # 4) amend the contract (resolves the block) AND impact now VERIFIED -> advance.
    #    The amended contract changes its hash, so the idempotent bridge re-runs.
    contract = _write(repo, run_dir, "acceptance-contract.json",
                      _contract(["checkout_handler"], marker="v2-resolved"))
    _submit(tmp_path, state_path, "CLARIFIED", "acceptance_contract", contract)
    _FakeProvider.result = _verified()
    _code, nres = _next(tmp_path, state_path)
    assert nres["blocked_phase"] == "PLANNED"   # past CLARIFIED, now needs the plan

    # 5) submit plan + module_plan WITHOUT impact_refs -> PLANNED blocked on impact_refs
    plan = _write(repo, run_dir, "plan.md", "# plan\n")
    mp_no_refs = {"schema": "e2e-dev-harness.module-plan.v1",
                  "modules": [{"id": "core", "name": "Core", "depends_on": [],
                               "acceptance_ids": ["AC-001"]}]}
    mp_path = _write(repo, run_dir, "module-plan.json", mp_no_refs)
    _submit(tmp_path, state_path, "PLANNED", "plan", plan)
    _submit(tmp_path, state_path, "PLANNED", "module_plan", mp_path)
    _code, nres = _next(tmp_path, state_path)
    assert nres["blocked_phase"] == "PLANNED"
    assert "impact_refs" in nres["missing_evidence"]

    # 6) re-submit module_plan WITH impact_refs covering the seed -> PLANNED passes
    mp_refs = {"schema": "e2e-dev-harness.module-plan.v1",
               "modules": [{"id": "core", "name": "Core", "depends_on": [],
                            "acceptance_ids": ["AC-001"],
                            "impact_refs": [{"seed": "checkout_handler",
                                             "affected_processes": ["run"],
                                             "test_focus": ["checkout regression"]}]}]}
    mp_path = _write(repo, run_dir, "module-plan.json", mp_refs)
    _submit(tmp_path, state_path, "PLANNED", "module_plan", mp_path)
    _code, nres = _next(tmp_path, state_path)
    assert nres["blocked_phase"] == "RED"   # PLANNED satisfied, advanced past it


def test_impact_degradation_flow(tmp_path, monkeypatch):
    """Impact on by default; an unverifiable assessment offers degradation. The
    coordinator records an approval and the run proceeds as `degraded` (no
    impact_refs required), with the approval hash as the trust anchor."""
    monkeypatch.setattr(
        "e2e_harness.adapters.impact.gitnexus.GitNexusImpactProvider", _FakeProvider)
    _FakeProvider.result = _blocked()
    repo = tmp_path

    code, res = start_cmd.run(_start_args(tmp_path, impact_mode="auto"))
    assert code == 0
    state_path = Path(res["run_state"])
    run_dir = state_path.parent

    _next(tmp_path, state_path)  # -> CLARIFIED (needs evidence)
    clar = _write(repo, run_dir, "clarification.md", "# clarified\n")
    contract = _write(repo, run_dir, "acceptance-contract.json",
                      _contract(["checkout_handler"], marker="v1"))
    _submit(tmp_path, state_path, "CLARIFIED", "clarification", clar)
    _submit(tmp_path, state_path, "CLARIFIED", "acceptance_contract", contract)

    # impact BLOCKED -> reopen CLARIFIED AND offer degradation
    _code, nres = _next(tmp_path, state_path)
    assert nres["blocked_phase"] == "CLARIFIED"
    assert nres["impact"]["status"] == "blocked"
    assert nres["impact"]["degradation_available"] is True

    # coordinator records the degradation approval (the trust anchor)
    approval = run_dir / "gitnexus-degradation.json"
    approval.write_text(json.dumps({
        "schema": "e2e-dev-harness.impact-degradation-approval.v1",
        "approval": "user-approved",
        "reason": "GitNexus not indexed here",
        "fallback_evidence": ["manual code review of checkout_handler"],
    }), encoding="utf-8")
    from e2e_harness.cli.commands import approve_impact_degradation as approve_cmd
    acode, _ares = approve_cmd.run(SimpleNamespace(
        state=str(state_path), approval=str(approval), reason="env has no gitnexus"))
    assert acode == 0

    # next -> bridge re-runs (approval present) -> degraded -> proceeds to PLANNED
    _code, nres = _next(tmp_path, state_path)
    assert nres["blocked_phase"] == "PLANNED"

    # degraded imposes NO impact_refs requirement: a plain module_plan passes PLANNED
    plan = _write(repo, run_dir, "plan.md", "# plan\n")
    mp = {"schema": "e2e-dev-harness.module-plan.v1",
          "modules": [{"id": "core", "name": "Core", "depends_on": [],
                       "acceptance_ids": ["AC-001"]}]}
    mp_path = _write(repo, run_dir, "module-plan.json", mp)
    _submit(tmp_path, state_path, "PLANNED", "plan", plan)
    _submit(tmp_path, state_path, "PLANNED", "module_plan", mp_path)
    _code, nres = _next(tmp_path, state_path)
    assert nres["blocked_phase"] == "RED"   # advanced past PLANNED on degraded evidence
