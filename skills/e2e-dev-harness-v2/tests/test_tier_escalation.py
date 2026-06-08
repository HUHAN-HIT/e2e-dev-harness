"""U3 — scanner -> tier escalation wiring.

Golden-fixture thresholds: a scanner scope (scanner-scope.v1) raises the tier
floor. >=2 services => at least `standard`; >=1 cross-service dependency edge
=> `critical`. The scope never downgrades a higher text-derived tier.
"""
from harness_v2.adapters.tier import classify


# --- golden scanner-scope fixtures (scanner-scope.v1 shape) ---

def _scope(services, dependencies=None):
    return {
        "schema": "e2e-dev-harness.scanner-scope.v1",
        "ready": True,
        "scanner": "java-spring",
        "services": list(services),
        "dependencies": list(dependencies or []),
        "warnings": [],
    }


SCOPE_SINGLE = _scope(["svc-a"])
SCOPE_TWO = _scope(["svc-a", "svc-b"])
SCOPE_CROSS = _scope(["svc-a", "svc-b"], [{"from": "svc-a", "to": "svc-b"}])

_PLAIN = "rename a helper function"  # text-only tier == minimal


def test_two_services_escalate_minimal_to_standard():
    tier, reasons = classify.classify_tier(_PLAIN, scope=SCOPE_TWO)
    assert tier == "standard"
    assert any("service" in r.lower() for r in reasons)


def test_cross_service_dependency_escalates_to_critical():
    tier, reasons = classify.classify_tier(_PLAIN, scope=SCOPE_CROSS)
    assert tier == "critical"
    assert any("dependenc" in r.lower() for r in reasons)


def test_single_service_does_not_escalate():
    tier, _ = classify.classify_tier(_PLAIN, scope=SCOPE_SINGLE)
    assert tier == "minimal"


def test_no_scope_is_text_only_minimal():
    tier, _ = classify.classify_tier(_PLAIN, scope=None)
    assert tier == "minimal"


def test_scope_never_downgrades_higher_text_tier():
    # audited (text) outranks the standard floor from a 2-service scope
    tier, _ = classify.classify_tier(
        "compliance audit of the incident response", scope=SCOPE_TWO
    )
    assert tier == "audited"


def test_text_critical_beats_standard_floor():
    # payment text => critical; a 2-service scope (standard floor) must not lower it
    tier, _ = classify.classify_tier(
        "add refund settlement to the ledger", scope=SCOPE_TWO
    )
    assert tier == "critical"


def test_standard_text_escalates_to_critical_on_cross_service():
    # REST endpoint => standard (text); cross-service deps raise it to critical
    tier, _ = classify.classify_tier(
        "add a REST endpoint for the client", scope=SCOPE_CROSS
    )
    assert tier == "critical"
