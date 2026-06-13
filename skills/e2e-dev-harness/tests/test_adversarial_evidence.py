"""Slice 2: structured evidence for the opt-in adversarial pipeline.

A prose file proves a report exists; the adversarial-review.v1 schema proves the
reviewer enumerated claims, attacked them, bound findings to evidence, and did not
escalate to `block` without a high/critical finding. These tests pin the validator
rules and the gate-time enforcement of the three perspective keys.
"""
import json

from e2e_harness.adapters.evidence import adversarial, validate


def _review(**over):
    obj = {
        "schema": "e2e-dev-harness.adversarial-review.v1",
        "perspective": "code",
        "verdict": "pass-with-findings",
        "claims_attacked": [
            {"id": "C-001",
             "claim": "the review fan-out guarantees independent perspectives",
             "source": "agent-teams/default-adversarial.yaml"},
        ],
        "findings": [
            {"id": "F-001", "severity": "medium",
             "target": "adapters/agent_team/builtin.py",
             "claim_attacked": "worker perspective is explicit in the packet",
             "evidence": "worker packet carries expected_outputs but no review_perspective field",
             "counterexample": "a misnamed expected output makes the worker choose no perspective",
             "required_fix": "keep the key-naming contract tested"},
        ],
        "missing_evidence": [],
        "residual_risk": ["markdown companion report may be richer than the JSON summary"],
    }
    obj.update(over)
    return obj


# --- validator unit rules -----------------------------------------------------

def test_valid_code_review_passes():
    ok, reason = adversarial.validate_adversarial_review(_review(), "code")
    assert ok is True and reason is None


def test_valid_design_and_test_design_pass():
    ok, _ = adversarial.validate_adversarial_review(_review(perspective="design"), "design")
    assert ok is True
    ok, _ = adversarial.validate_adversarial_review(_review(perspective="test-design"), "test-design")
    assert ok is True


def test_non_mapping_rejected():
    ok, reason = adversarial.validate_adversarial_review(["not", "a", "mapping"], "code")
    assert ok is False and reason == "not-mapping"


def test_bad_schema_rejected():
    ok, reason = adversarial.validate_adversarial_review(_review(schema="other.v1"), "code")
    assert ok is False and reason == "bad-schema"


def test_unknown_perspective_rejected():
    ok, reason = adversarial.validate_adversarial_review(_review(perspective="vibes"), "vibes")
    assert ok is False and reason == "bad-perspective"


def test_perspective_must_match_expected_key():
    ok, reason = adversarial.validate_adversarial_review(_review(perspective="design"), "code")
    assert ok is False and reason.startswith("perspective-mismatch")


def test_bad_verdict_rejected():
    ok, reason = adversarial.validate_adversarial_review(_review(verdict="lgtm"), "code")
    assert ok is False and reason == "bad-verdict"


def test_empty_claims_attacked_rejected():
    ok, reason = adversarial.validate_adversarial_review(_review(claims_attacked=[]), "code")
    assert ok is False and reason == "claims-attacked-empty"


def test_malformed_claim_rejected():
    ok, reason = adversarial.validate_adversarial_review(
        _review(claims_attacked=[{"id": "C-001"}]), "code")
    assert ok is False and reason == "claim-malformed"


def test_finding_missing_required_field_rejected():
    bad = _review()
    del bad["findings"][0]["counterexample"]
    ok, reason = adversarial.validate_adversarial_review(bad, "code")
    assert ok is False and reason == "finding-missing-field:counterexample"


def test_finding_bad_severity_rejected():
    bad = _review()
    bad["findings"][0]["severity"] = "spicy"
    ok, reason = adversarial.validate_adversarial_review(bad, "code")
    assert ok is False and reason.startswith("bad-severity")


def test_block_without_high_or_critical_rejected():
    ok, reason = adversarial.validate_adversarial_review(_review(verdict="block"), "code")
    assert ok is False and reason == "block-without-high-severity"


def test_block_with_high_finding_passes():
    obj = _review(verdict="block")
    obj["findings"][0]["severity"] = "high"
    ok, reason = adversarial.validate_adversarial_review(obj, "code")
    assert ok is True and reason is None


# --- gate-time enforcement via STRUCTURED_KEYS --------------------------------

def test_gate_rejects_prose_for_adversarial_key(tmp_path):
    (tmp_path / "r.md").write_text("looks fine to me", encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "adversarial_code_review", {"path": "r.md"})
    assert ok is False and reason == "not-json"


def test_gate_accepts_valid_json_for_each_perspective(tmp_path):
    for key, persp in (
        ("adversarial_code_review", "code"),
        ("adversarial_design_review", "design"),
        ("adversarial_test_design_review", "test-design"),
    ):
        f = tmp_path / f"{key}.json"
        f.write_text(json.dumps(_review(perspective=persp)), encoding="utf-8")
        ok, reason = validate.validate_evidence(tmp_path, key, {"path": f.name})
        assert ok is True and reason is None, (key, reason)


def test_gate_rejects_perspective_mismatch_via_key(tmp_path):
    # a 'design' artifact submitted under the code key must be rejected
    f = tmp_path / "x.json"
    f.write_text(json.dumps(_review(perspective="design")), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "adversarial_code_review", {"path": "x.json"})
    assert ok is False and reason.startswith("perspective-mismatch")


def test_gate_validates_module_namespaced_adversarial_key(tmp_path):
    # multitrack base_key strips the #module suffix, so the structured rule still applies
    f = tmp_path / "m.json"
    f.write_text(json.dumps(_review(perspective="code")), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "adversarial_code_review#auth", {"path": "m.json"})
    assert ok is True and reason is None
