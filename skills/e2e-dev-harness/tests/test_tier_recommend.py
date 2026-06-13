from e2e_harness.adapters.tier import recommend


def test_plain_auto_recommends_standard_with_options():
    result = recommend.recommend_tier("rename a helper function", scope=None, selected_tier="auto")

    assert result["recommended_tier"] == "standard"
    assert result["selected_tier"] == "standard"
    assert result["selection_source"] == "auto"
    assert [option["tier"] for option in result["options"]] == [
        "minimal",
        "standard",
        "critical",
        "audited",
    ]
    standard = next(option for option in result["options"] if option["tier"] == "standard")
    assert standard["recommended"] is True
    assert any("auto baseline floor" in reason for reason in standard["reasons"])


def test_explicit_lower_tier_records_downgrade_metadata():
    result = recommend.recommend_tier(
        "add refund settlement to the ledger",
        scope=None,
        selected_tier="standard",
    )

    assert result["recommended_tier"] == "critical"
    assert result["selected_tier"] == "standard"
    assert result["selection_source"] == "explicit"
    assert result["downgrade"]["requested_below_recommended"] is True
    assert result["downgrade"]["requires_provenance"] is True
    assert result["downgrade"]["blocked"] is False


def test_explicit_below_audited_is_blocked():
    result = recommend.recommend_tier(
        "compliance audit of the incident response",
        scope=None,
        selected_tier="critical",
    )

    assert result["recommended_tier"] == "audited"
    assert result["selected_tier"] == "audited"
    assert result["downgrade"]["requested_below_recommended"] is True
    assert result["downgrade"]["blocked"] is True


def test_gitnexus_medium_risk_floors_to_standard():
    scope = {
        "gitnexus": {
            "verified": True,
            "impact_summary": {"risk": "MEDIUM"},
        },
    }

    result = recommend.recommend_tier("rename a helper function", scope=scope, selected_tier="auto")

    assert result["recommended_tier"] == "standard"
    assert result["selected_tier"] == "standard"
    assert "GitNexus impact risk: MEDIUM" in result["reasons"]


def test_gitnexus_high_risk_floors_to_critical():
    scope = {
        "gitnexus": {
            "verified": True,
            "impact_summary": {"risk": "HIGH"},
        },
    }

    result = recommend.recommend_tier("rename a helper function", scope=scope, selected_tier="auto")

    assert result["recommended_tier"] == "critical"
    assert result["selected_tier"] == "critical"
    assert "GitNexus impact risk: HIGH" in result["reasons"]


def test_gitnexus_medium_risk_with_unverified_dependencies_keeps_both_reasons():
    scope = {
        "dependencies": [
            {
                "source_service": "services/a",
                "target_service": "services/b",
            }
        ],
        "gitnexus": {
            "verified": False,
            "impact_summary": {"risk": "MEDIUM"},
        },
    }

    result = recommend.recommend_tier("rename a helper function", scope=scope, selected_tier="auto")

    assert result["recommended_tier"] == "critical"
    assert "GitNexus impact risk: MEDIUM" in result["reasons"]
    assert (
        "cross-service dependencies found but GitNexus impact evidence is not verified"
        in result["reasons"]
    )
