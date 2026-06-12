from e2e_harness.adapters.tier import classify


def test_plain_request_without_auto_stays_minimal():
    # Core text classification (no auto floor) still yields minimal so the
    # scanner-escalation wiring (test_tier_escalation) keeps a minimal baseline.
    tier, reasons = classify.classify_tier("rename a helper function")
    assert tier == "minimal"
    assert reasons


def test_plain_request_floors_to_standard_under_auto():
    # G4: in auto mode a no-risk request is floored to standard (review is the
    # default; `--tier minimal` remains an explicit opt-down).
    tier, reasons = classify.classify_tier("rename a helper function", auto=True)
    assert tier == "standard"
    assert any("floor" in r.lower() for r in reasons)


def test_payment_keyword_escalates_to_critical():
    tier, _ = classify.classify_tier("add refund settlement to the ledger")
    assert tier == "critical"


def test_security_login_password_is_critical():
    tier, _ = classify.classify_tier("add user login with password")
    assert tier == "critical"


def test_security_oauth_token_is_critical():
    tier, _ = classify.classify_tier("issue an oauth token for the user session")
    assert tier == "critical"


def test_security_keyword_is_critical_even_under_auto():
    # The auto floor only lifts minimal; it never lowers a security-critical tier.
    tier, _ = classify.classify_tier("enforce permission checks on the endpoint", auto=True)
    assert tier == "critical"


def test_payment_wire_transfer_is_critical():
    tier, _ = classify.classify_tier("support wire transfer and withdrawal")
    assert tier == "critical"


def test_payment_billing_invoice_is_critical():
    tier, _ = classify.classify_tier("generate a billing invoice for the charge")
    assert tier == "critical"


def test_audit_keyword_escalates_to_audited():
    tier, _ = classify.classify_tier("compliance audit of the incident response")
    assert tier == "audited"


def test_single_service_api_surface_is_standard():
    tier, _ = classify.classify_tier("add a REST endpoint for the client")
    assert tier == "standard"
