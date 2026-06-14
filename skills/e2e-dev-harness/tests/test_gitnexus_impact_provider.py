from pathlib import Path

from e2e_harness.adapters.evidence import impact
from e2e_harness.adapters.impact import gitnexus


def _runner(scripted):
    """command_runner stub: maps a substring of the joined command -> result dict.
    Accepts the optional `timeout` kwarg the provider now passes (budget wiring)."""
    def run(command, cwd, timeout=None):
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


def test_resolve_seeds_accepts_typed_file_route_and_fqn_candidates():
    p = gitnexus.GitNexusImpactProvider(command_runner=_runner({}), available=True)
    out = p.resolve_seeds(Path("."), {"seed_candidates": [
        {"kind": "file", "value": "src/handlers/login.py"},
        {"kind": "route", "value": "/api/checkout"},
        {"kind": "fqn", "value": "com.example.checkout.CheckoutService"},
        {"kind": "symbol", "value": "CheckoutService"},
    ]})
    assert out["seeds"] == [
        "src/handlers/login.py",
        "/api/checkout",
        "com.example.checkout.CheckoutService",
        "CheckoutService",
    ]
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


def test_assess_preserves_typed_seed_kind_in_artifact():
    impact_json = '{"risk": "LOW", "file_path": "src/handlers/login.py", "summary": {"direct": 1}}'
    p = gitnexus.GitNexusImpactProvider(
        command_runner=_runner({"gitnexus impact src/handlers/login.py": {
            "exit_code": 0, "stdout": impact_json}}),
        available=True)
    out = p.assess(Path("."), {"seed_candidates": [
        {"kind": "file", "value": "src/handlers/login.py"},
    ]})
    assert out["status"] == "verified"
    assert out["seeds"][0]["kind"] == "file"
    assert out["seeds"][0]["name"] == "src/handlers/login.py"


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


def test_subprocess_calls_pass_configured_timeout_budget():
    # The configured budgets must reach run_command: impact/status under call_timeout_s
    # (the hot path behind `next`), analyze under the longer refresh_timeout_s. Without
    # wiring, every call falls through to run_command's hard-coded default and the
    # budgets are dead config.
    seen: list[tuple[str, float | None]] = []

    def recording(command, cwd, timeout=None):
        joined = " ".join(command)
        seen.append((joined, timeout))
        if "gitnexus impact" in joined:
            return {"command": joined, "exit_code": 0,
                    "stdout": '{"risk": "LOW", "file_path": "a.py", "summary": {"direct": 0}}'}
        return {"command": joined, "exit_code": 0, "stdout": ""}

    p = gitnexus.GitNexusImpactProvider(
        command_runner=recording, available=True,
        call_timeout_s=7.0, refresh_timeout_s=99.0)
    p.inspect_index(Path("."))
    p.refresh_index(Path("."))
    p.assess(Path("."), {"seed_candidates": ["foo"]})

    by_kind: dict[str, float | None] = {}
    for joined, t in seen:
        if "gitnexus status" in joined:
            by_kind["status"] = t
        elif "gitnexus analyze" in joined:
            by_kind["analyze"] = t
        elif "gitnexus impact" in joined:
            by_kind["impact"] = t
    assert by_kind["status"] == 7.0     # inspect_index uses the call budget
    assert by_kind["impact"] == 7.0     # _impact_for_seed uses the call budget
    assert by_kind["analyze"] == 99.0   # refresh_index uses the refresh budget
