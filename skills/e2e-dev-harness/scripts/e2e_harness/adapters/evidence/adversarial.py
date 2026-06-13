"""Validate an adversarial-review evidence artifact (high-assurance REVIEWED).

A prose file proves a report exists; it cannot prove the reviewer enumerated
claims, attacked them, found counterexamples, and bound each finding to evidence.
The `adversarial-review.v1` schema makes that structurally checkable, so the three
opt-in adversarial perspective keys reject empty prose, malformed JSON, a
perspective that does not match its key, and a `block` verdict unsupported by any
high/critical finding.

Registered in `validate.STRUCTURED_KEYS` once per key, each binding the perspective
that key pins (the worker packet's `expected_outputs` name encodes the angle):
    adversarial_code_review        -> code
    adversarial_design_review      -> design
    adversarial_test_design_review -> test-design
"""
from __future__ import annotations

SCHEMA = "e2e-dev-harness.adversarial-review.v1"
PERSPECTIVES = ("code", "design", "test-design")
VERDICTS = ("pass", "pass-with-findings", "block")
SEVERITIES = ("critical", "high", "medium", "low")
_HIGH_SEVERITIES = {"critical", "high"}
FINDING_FIELDS = (
    "id", "severity", "target", "claim_attacked", "evidence", "counterexample", "required_fix",
)

# The opt-in adversarial evidence key -> the single perspective it pins.
KEY_PERSPECTIVE = {
    "adversarial_code_review": "code",
    "adversarial_design_review": "design",
    "adversarial_test_design_review": "test-design",
}


def _nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_adversarial_review(obj, expected_perspective: str) -> tuple[bool, str | None]:
    """Return (ok, reason). `reason` is None on success, else a stable machine code
    naming exactly what failed (mirrors the other STRUCTURED_KEYS validators)."""
    if not isinstance(obj, dict):
        return False, "not-mapping"
    if obj.get("schema") != SCHEMA:
        return False, "bad-schema"

    perspective = obj.get("perspective")
    if perspective not in PERSPECTIVES:
        return False, "bad-perspective"
    if perspective != expected_perspective:
        return False, f"perspective-mismatch:{perspective}!={expected_perspective}"

    if obj.get("verdict") not in VERDICTS:
        return False, "bad-verdict"

    claims = obj.get("claims_attacked")
    if not isinstance(claims, list) or not claims:
        return False, "claims-attacked-empty"
    for claim in claims:
        if not isinstance(claim, dict) or not _nonempty_str(claim.get("claim")):
            return False, "claim-malformed"

    findings = obj.get("findings")
    if not isinstance(findings, list):
        return False, "findings-not-list"
    for finding in findings:
        if not isinstance(finding, dict):
            return False, "finding-not-mapping"
        for field in FINDING_FIELDS:
            if not _nonempty_str(finding.get(field)):
                return False, f"finding-missing-field:{field}"
        if finding["severity"] not in SEVERITIES:
            return False, f"bad-severity:{finding['severity']}"

    if obj["verdict"] == "block" and not any(
        f.get("severity") in _HIGH_SEVERITIES for f in findings
    ):
        return False, "block-without-high-severity"

    return True, None
