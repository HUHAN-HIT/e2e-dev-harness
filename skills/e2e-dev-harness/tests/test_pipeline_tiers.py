from e2e_harness import pipeline
from e2e_harness.core import lifecycle


def test_minimal_skips_planned_and_reviewed():
    names = pipeline.active_phase_names("minimal")
    assert "PLANNED" not in names and "REVIEWED" not in names


def test_standard_is_full_spine_single_reviewer():
    names = pipeline.active_phase_names("standard")
    assert names == ["CREATED", "CLARIFIED", "PLANNED", "RED", "IMPLEMENTED", "REVIEWED", "VERIFIED"]
    spine = pipeline.build_spine("standard")
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    assert reviewed.exit_gate == ("review",)


def test_critical_reviewed_requires_three_reviews():
    spine = pipeline.build_spine("critical")
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    assert reviewed.exit_gate == ("r1_review", "r2_review", "r3_review")
    assert reviewed.produces == ("r1_review", "r2_review", "r3_review")


def test_audited_adds_audit_replay_to_verified():
    spine = pipeline.build_spine("audited")
    verified = next(p for p in spine if p.name == "VERIFIED")
    assert "audit_replay" in verified.exit_gate
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    assert reviewed.exit_gate == ("r1_review", "r2_review", "r3_review")


def test_audited_verified_requires_agent_team_dispatch():
    """F4: audited VERIFIED enforces the agent-team dispatch chain as a gate key
    (produces+exit_gate for I2 closure); other tiers do not (tier isolation)."""
    verified = next(p for p in pipeline.build_spine("audited") if p.name == "VERIFIED")
    assert "agent_team_dispatch" in verified.exit_gate
    assert "agent_team_dispatch" in verified.produces
    for tier in ("standard", "critical"):
        sv = next(p for p in pipeline.build_spine(tier) if p.name == "VERIFIED")
        assert "agent_team_dispatch" not in sv.exit_gate


def test_build_spine_overrides_are_isolated_from_catalog():
    pipeline.build_spine("critical")
    assert lifecycle.catalog()["REVIEWED"].exit_gate == ("review",)


def test_unknown_pipeline_raises():
    import pytest
    with pytest.raises(KeyError):
        pipeline.active_phase_names("nope")


def test_rapid_is_pipeline_not_tier():
    names = pipeline.active_phase_names("rapid")

    assert names == ["CREATED", "CLARIFIED", "IMPLEMENTED", "VERIFIED"]
    assert "RED" not in names
    assert "PLANNED" not in names
    assert "REVIEWED" not in names
