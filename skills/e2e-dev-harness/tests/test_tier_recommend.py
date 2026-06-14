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


def test_explicit_below_audited_preserves_selection_with_provenance_required():
    result = recommend.recommend_tier(
        "compliance audit of the incident response",
        scope=None,
        selected_tier="critical",
    )

    assert result["recommended_tier"] == "audited"
    assert result["selected_tier"] == "critical"
    assert result["downgrade"]["requested_below_recommended"] is True
    assert result["downgrade"]["requires_provenance"] is True
    assert result["downgrade"]["blocked"] is False


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


# --- Slice 3: adversarial-review suggestion (advisory, opt-in via --pipeline) ---

def _adv(result):
    return result["adversarial_review"]


def test_control_plane_request_suggests_adversarial_review():
    result = recommend.recommend_tier(
        "refactor the coordinator lifecycle phase guard", scope=None, selected_tier="auto")
    adv = _adv(result)
    assert adv["suggested"] is True
    assert adv["pipeline"] == "adversarial"
    assert adv["select_with"] == "start --pipeline adversarial"
    assert any("adversarial-review trigger" in r and "control-plane" in r for r in adv["reasons"])


def test_evidence_gate_dispatch_request_suggests_adversarial_review():
    result = recommend.recommend_tier(
        "harden the evidence gate and dispatch protocol", scope=None, selected_tier="auto")
    adv = _adv(result)
    assert adv["suggested"] is True
    assert any("evidence/gate/dispatch" in r for r in adv["reasons"])


def test_concurrency_request_suggests_adversarial_review():
    result = recommend.recommend_tier(
        "add module fan-out concurrency to the band", scope=None, selected_tier="auto")
    adv = _adv(result)
    assert adv["suggested"] is True
    assert any("concurrency" in r for r in adv["reasons"])


def test_security_request_suggests_adversarial_review():
    result = recommend.recommend_tier(
        "rework the auth token session handling", scope=None, selected_tier="auto")
    adv = _adv(result)
    assert adv["suggested"] is True
    assert any("security-sensitive" in r for r in adv["reasons"])


def test_high_gitnexus_impact_suggests_adversarial_review():
    scope = {"gitnexus": {"verified": True, "impact_summary": {"risk": "CRITICAL"}}}
    result = recommend.recommend_tier("rename a helper function", scope=scope, selected_tier="auto")
    adv = _adv(result)
    assert adv["suggested"] is True
    assert any("high GitNexus impact" in r and "CRITICAL" in r for r in adv["reasons"])


def test_plain_request_does_not_suggest_adversarial_review():
    result = recommend.recommend_tier("rename a helper function", scope=None, selected_tier="auto")
    adv = _adv(result)
    assert adv["suggested"] is False
    assert adv["reasons"] == []


def test_adversarial_suggestion_is_advisory_not_a_tier_change():
    """Slice 3 keeps the suggestion explicit/user-confirmed: it never auto-selects a
    pipeline — selected_tier stays a real tier and the user opts in via --pipeline."""
    result = recommend.recommend_tier(
        "refactor the coordinator lifecycle and gate", scope=None, selected_tier="auto")
    assert result["adversarial_review"]["suggested"] is True
    assert result["selected_tier"] in ("minimal", "standard", "critical", "audited")
    assert [o["tier"] for o in result["options"]] == ["minimal", "standard", "critical", "audited"]
    assert "adversarial" not in [o["tier"] for o in result["options"]]


def test_rapid_is_not_a_tier_recommendation_option():
    """Regression pin: rapid is an opt-in pipeline, not an auto tier option."""
    result = recommend.recommend_tier(
        "make a small copy change", scope=None, selected_tier="auto")

    assert [option["tier"] for option in result["options"]] == [
        "minimal",
        "standard",
        "critical",
        "audited",
    ]
    assert "rapid" not in [option["tier"] for option in result["options"]]
    assert result["selected_tier"] in ("minimal", "standard", "critical", "audited")
