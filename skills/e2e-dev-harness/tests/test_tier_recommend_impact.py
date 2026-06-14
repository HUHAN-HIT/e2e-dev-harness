from e2e_harness.adapters.tier import impact_scope, recommend


def _artifact(status, risks):
    return {"schema": "e2e-dev-harness.impact-assessment.v1", "status": status,
            "seeds": [{"name": f"s{i}"} for i, _ in enumerate(risks)],
            "impact": [{"seed": f"s{i}", "risk": r, "summary": {},
                        "affected_processes": [{"name": "p"}]}
                       for i, r in enumerate(risks)]}


def test_derivation_max_risk_and_verified_flag():
    scope = impact_scope.scope_gitnexus_from_artifact(_artifact("verified", ["LOW", "HIGH"]))
    assert scope == {"impact_summary": {"risk": "HIGH"}, "verified": True}


def test_derivation_degraded_not_verified():
    scope = impact_scope.scope_gitnexus_from_artifact(_artifact("degraded", ["MEDIUM"]))
    assert scope["verified"] is False
    assert scope["impact_summary"]["risk"] == "MEDIUM"


def test_derivation_no_seeds_unset_risk():
    scope = impact_scope.scope_gitnexus_from_artifact(_artifact("not_applicable", []))
    assert "risk" not in scope["impact_summary"]


def test_high_impact_floors_recommend_to_critical():
    scope = {"gitnexus": impact_scope.scope_gitnexus_from_artifact(_artifact("verified", ["HIGH"]))}
    result = recommend.recommend_tier("rename a helper function", scope=scope, selected_tier="auto")
    assert result["recommended_tier"] == "critical"


def test_degraded_cross_service_keeps_critical_warning():
    scope = {"dependencies": [{"source_service": "a", "target_service": "b"}],
             "gitnexus": impact_scope.scope_gitnexus_from_artifact(_artifact("degraded", ["MEDIUM"]))}
    result = recommend.recommend_tier("rename a helper function", scope=scope, selected_tier="auto")
    assert result["recommended_tier"] == "critical"
    assert any("not verified" in r for r in result["reasons"])
