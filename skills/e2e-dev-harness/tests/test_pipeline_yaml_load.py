import pytest

from e2e_harness import pipeline


def test_minimal_loads_from_yaml_and_skips_planned_reviewed():
    names = pipeline.active_phase_names("minimal")
    assert names == ["CREATED", "CLARIFIED", "RED", "IMPLEMENTED", "VERIFIED"]


def test_standard_is_full_spine_single_reviewer():
    spine = pipeline.build_spine("standard")
    assert [p.name for p in spine] == [
        "CREATED", "CLARIFIED", "PLANNED", "RED", "IMPLEMENTED", "REVIEWED", "VERIFIED"]
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    assert reviewed.exit_gate == ("review",)
    assert reviewed.worker_skill == "e2e-harness-review"  # inherited from catalog


def test_critical_reviewed_overrides_to_three_reviews():
    spine = pipeline.build_spine("critical")
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    assert reviewed.produces == ("r1_review", "r2_review", "r3_review")
    assert reviewed.exit_gate == ("r1_review", "r2_review", "r3_review")
    assert reviewed.worker_skill == "e2e-harness-review"  # non-overridden field inherited


def test_audited_overrides_verified_and_reviewed():
    spine = pipeline.build_spine("audited")
    verified = next(p for p in spine if p.name == "VERIFIED")
    assert verified.exit_gate == ("verification", "audit_replay")
    assert verified.next_phase is None


def test_next_phase_wired_linearly():
    spine = pipeline.build_spine("standard")
    for a, b in zip(spine, spine[1:]):
        assert a.next_phase == b.name
    assert spine[-1].next_phase is None


def test_unknown_builtin_name_raises_keyerror():
    with pytest.raises(KeyError):
        pipeline.active_phase_names("nope")


def test_load_spec_from_path(tmp_path):
    f = tmp_path / "custom.yaml"
    f.write_text("name: c\nphases: [CREATED, CLARIFIED, VERIFIED]\n", encoding="utf-8")
    spine = pipeline.spec_to_spine(pipeline.load_spec(str(f)))
    assert [p.name for p in spine] == ["CREATED", "CLARIFIED", "VERIFIED"]


def test_is_path_distinguishes_names_from_paths():
    assert pipeline.is_path("foo.yaml") is True
    assert pipeline.is_path("dir/foo.yml") is True
    assert pipeline.is_path("critical") is False


def test_spine_for_state_prefers_embedded_spec():
    spec = {"name": "x", "phases": ["CREATED", "VERIFIED"]}
    spine = pipeline.spine_for_state({"pipeline": "standard", "pipeline_spec": spec})
    assert [p.name for p in spine] == ["CREATED", "VERIFIED"]


def test_spine_for_state_falls_back_to_named_builtin():
    spine = pipeline.spine_for_state({"pipeline": "minimal"})
    assert [p.name for p in spine] == ["CREATED", "CLARIFIED", "RED", "IMPLEMENTED", "VERIFIED"]
