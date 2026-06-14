from pathlib import Path

from e2e_harness.adapters.evidence import impact
from e2e_harness.adapters.impact import gitnexus


def _runner(scripted):
    """command_runner stub: maps a substring of the joined command -> result dict."""
    def run(command, cwd):
        joined = " ".join(command)
        for needle, result in scripted.items():
            if needle in joined:
                return dict(result, command=joined)
        return {"command": joined, "exit_code": 0, "stdout": ""}
    return run


def test_resolve_seeds_filters_non_symbol_candidates():
    p = gitnexus.GitNexusImpactProvider(command_runner=_runner({}), available=True)
    out = p.resolve_seeds(Path("."), {"seed_candidates": ["_phase_request", "services/auth", "a/b.py"]})
    assert out["seeds"] == ["_phase_request"]   # service dir + path rejected
    assert out["blocked"] is False


def test_resolve_seeds_blocks_when_none_derivable():
    p = gitnexus.GitNexusImpactProvider(command_runner=_runner({}), available=True)
    out = p.resolve_seeds(Path("."), {"seed_candidates": ["services/auth"]})
    assert out["seeds"] == []
    assert out["blocked"] is True
    assert any(q["id"].startswith("IQ-") for q in out["open_questions"])


def test_assess_unavailable_blocks():
    p = gitnexus.GitNexusImpactProvider(available=False)
    out = p.assess(Path("."), {"seed_candidates": ["foo"]})
    assert out["status"] == "blocked"
    assert out["open_questions"]


def test_assess_high_risk_normalized():
    impact_json = '{"risk": "HIGH", "file_path": "a.py", "summary": {"direct": 9}, ' \
                  '"affected_processes": [{"name": "checkout", "file_path": "c.py"}], ' \
                  '"affected_modules": ["Billing"]}'
    p = gitnexus.GitNexusImpactProvider(
        command_runner=_runner({"gitnexus impact foo": {"exit_code": 0, "stdout": impact_json}}),
        available=True)
    out = p.assess(Path("."), {"seed_candidates": ["foo"]})
    assert out["status"] == "verified"
    row = out["impact"][0]
    assert row["risk"] == "HIGH"
    assert row["affected_processes"][0]["name"] == "checkout"
    assert row["affected_modules"] == ["Billing"]
    ok, reason = impact.validate_impact_assessment(out)   # provider output must validate
    assert ok is True, reason


def test_assess_ambiguous_seed_blocks_with_options():
    ambiguous = '{"candidates": ["pkg.Foo", "other.Foo"]}'
    p = gitnexus.GitNexusImpactProvider(
        command_runner=_runner({"gitnexus impact Foo": {"exit_code": 0, "stdout": ambiguous}}),
        available=True)
    out = p.assess(Path("."), {"seed_candidates": ["Foo"]})
    assert out["status"] == "blocked"
    assert any("disambiguate" in q["question"] for q in out["open_questions"])


def test_assess_timeout_blocks():
    p = gitnexus.GitNexusImpactProvider(
        command_runner=_runner({"gitnexus impact foo": {"exit_code": 124, "stdout": ""}}),
        available=True)
    out = p.assess(Path("."), {"seed_candidates": ["foo"]})
    assert out["status"] == "blocked"
    assert any("timed out" in q["question"] for q in out["open_questions"])
