from harness_v2 import pipeline
from harness_v2.core import lifecycle


def test_phase_defaults_to_no_code_write():
    p = lifecycle.Phase("X", "", "", (), (), None)
    assert p.allows_code_write is False


def test_catalog_phases_all_default_false():
    for name, phase in lifecycle.catalog().items():
        assert phase.allows_code_write is False, name


def _state(current, phases):
    return {"current_phase": current, "pipeline_spec": {"name": "t", "phases": phases}}


def test_mapping_phase_with_flag_allows():
    state = _state("IMPLEMENTED", [
        "CREATED", "CLARIFIED", "RED",
        {"phase": "IMPLEMENTED", "allows_code_write": True},
        "VERIFIED",
    ])
    assert pipeline.can_write_code(state) is True


def test_bare_string_phase_denies():
    state = _state("RED", ["CREATED", "CLARIFIED", "RED", "IMPLEMENTED", "VERIFIED"])
    assert pipeline.can_write_code(state) is False


def test_bare_string_implemented_denies_without_flag():
    # bare-string inherits catalog default (False) — only an explicit flag opens it.
    state = _state("IMPLEMENTED", ["CREATED", "CLARIFIED", "RED", "IMPLEMENTED", "VERIFIED"])
    assert pipeline.can_write_code(state) is False


def test_missing_current_phase_denies():
    state = {"pipeline_spec": {"name": "t", "phases": ["CREATED", "VERIFIED"]}}
    assert pipeline.can_write_code(state) is False


def test_current_phase_not_in_spine_denies():
    state = _state("GHOST", ["CREATED", "VERIFIED"])
    assert pipeline.can_write_code(state) is False
