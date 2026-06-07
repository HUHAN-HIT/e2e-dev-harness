from harness_v2 import pipeline
from harness_v2.core import lifecycle


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


def test_build_spine_overrides_are_isolated_from_catalog():
    pipeline.build_spine("critical")
    assert lifecycle.catalog()["REVIEWED"].exit_gate == ("review",)


def test_unknown_pipeline_raises():
    import pytest
    with pytest.raises(KeyError):
        pipeline.active_phase_names("nope")
