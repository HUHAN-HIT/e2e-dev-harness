from e2e_harness.core import lifecycle, gates
from e2e_harness import pipeline


def _phase(name):
    return next(p for p in lifecycle.build_spine(pipeline.active_phase_names("minimal")) if p.name == name)


def test_gate_blocks_when_evidence_missing():
    ok, missing = gates.gate_passes(_phase("CLARIFIED"), {"evidence": {}})
    assert ok is False
    assert missing == ["clarification"]


def test_gate_passes_when_evidence_present():
    rec = {"evidence": {"clarification": "h.md"}}
    ok, missing = gates.gate_passes(_phase("CLARIFIED"), rec)
    assert ok is True
    assert missing == []


def test_empty_gate_always_passes():
    ok, missing = gates.gate_passes(_phase("CREATED"), {})
    assert ok is True
    assert missing == []
