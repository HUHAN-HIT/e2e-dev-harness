from e2e_harness.adapters.domain import base
from e2e_harness import pipeline
from e2e_harness.core import pipeline_validate


def test_merge_applies_overrides_and_stays_valid():
    spec = pipeline.load_spec("standard")  # phases: CREATED..VERIFIED (bare strings)
    overrides = {"RED": {"produces": ["failing_tests"], "exit_gate": ["failing_tests"],
                         "worker_skill": "e2e-harness-tdd-red"}}
    merged = base.merge_overrides(spec, overrides)
    red = next(e for e in merged["phases"] if (e if isinstance(e, str) else e["phase"]) == "RED")
    assert isinstance(red, dict) and red["worker_skill"] == "e2e-harness-tdd-red"
    ok, errors = pipeline_validate.validate_spec(merged)
    assert ok, errors


def test_merge_empty_overrides_is_identity():
    spec = pipeline.load_spec("standard")
    assert base.merge_overrides(spec, {}) == spec
