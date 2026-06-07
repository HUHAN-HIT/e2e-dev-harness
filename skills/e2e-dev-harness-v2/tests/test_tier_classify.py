from harness_v2.adapters.tier import classify


def test_plain_request_is_minimal():
    tier, reasons = classify.classify_tier("rename a helper function")
    assert tier == "minimal"
    assert reasons


def test_payment_keyword_escalates_to_critical():
    tier, _ = classify.classify_tier("add refund settlement to the ledger")
    assert tier == "critical"


def test_audit_keyword_escalates_to_audited():
    tier, _ = classify.classify_tier("compliance audit of the incident response")
    assert tier == "audited"


def test_single_service_api_surface_is_standard():
    tier, _ = classify.classify_tier("add a REST endpoint for the client")
    assert tier == "standard"
