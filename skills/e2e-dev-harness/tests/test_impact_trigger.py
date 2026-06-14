from e2e_harness.core import impact_trigger


def _state(request="add a function", tier="standard"):
    return {"request": request, "tier": tier, "phases": {}}


def test_tier_critical_requires_impact():
    reasons = impact_trigger.required_reasons(_state(tier="critical"), repo_root=None)
    assert "tier-critical" in reasons


def test_explicit_impact_request_requires_impact():
    reasons = impact_trigger.required_reasons(
        _state(request="what is the blast radius of changing checkout?"), repo_root=None)
    assert "explicit-impact" in reasons


def test_documentation_only_not_required():
    st = _state(request="update the README documentation and fix a typo", tier="minimal")
    assert impact_trigger.required_reasons(st, repo_root=None) == []
    assert impact_trigger.is_documentation_only(st, repo_root=None) is True


def test_seed_candidates_in_contract_require_impact(tmp_path):
    contract = tmp_path / "acceptance-contract.json"
    contract.write_text('{"schema": "e2e-dev-harness.acceptance-contract.v1", '
                        '"items": [{"id": "AC-001", "criterion": "c", "observable_behavior": "o"}], '
                        '"impact_seed_candidates": ["_phase_request"]}', encoding="utf-8")
    st = {"request": "change planner", "tier": "standard",
          "phases": {"CLARIFIED": {"evidence": {"acceptance_contract": {"path": str(contract)}}}}}
    reasons = impact_trigger.required_reasons(st, repo_root=str(tmp_path))
    assert "existing-symbol" in reasons


def test_code_surface_request_requires_impact():
    reasons = impact_trigger.required_reasons(
        _state(request="modify the checkout API endpoint handler", tier="standard"), repo_root=None)
    assert "code-change" in reasons


def test_plain_non_code_request_not_required():
    # no code surface keyword, not doc-only, standard tier -> nothing fires
    assert impact_trigger.required_reasons(_state(request="please proceed", tier="standard"),
                                           repo_root=None) == []
