"""F5: the audited VERIFIED `audit_replay` key must be a machine-checkable manifest
whose every claim is backed by GENUINE command-evidence — prose can no longer satisfy
the gate. Validation is anti-forgery (records must bear record_command's structure)
but intentionally NOT anti-tamper (no exit_code replay; that is documented residual)."""
import json
import sys

from e2e_harness.adapters.evidence import validate, command_evidence as ce


def _manifest(claims):
    return {"schema": "e2e-dev-harness.audit-replay.v1", "claims": claims}


def test_prose_audit_replay_is_rejected(tmp_path):
    prose = tmp_path / "ar.md"
    prose.write_text("Full local suite: 376 passed.\nInstaller sync: ok.\n", encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "audit_replay", {"path": "ar.md"})
    assert ok is False
    assert reason in {"not-json", "bad-schema"}


def test_audit_replay_requires_backing_command_evidence(tmp_path):
    man = tmp_path / "ar.json"
    man.write_text(json.dumps(_manifest(
        [{"name": "full suite", "evidence": "missing.json", "expect_exit": 0}])), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "audit_replay", {"path": "ar.json"})
    assert ok is False
    assert "evidence-not-found" in reason


def test_audit_replay_rejects_forged_backing_evidence(tmp_path):
    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps({
        "schema": "e2e-dev-harness.command-evidence.v1", "exit_code": 0,
        "stdout_sha256": "full_suite_stdout", "stderr_sha256": "x",
        "environment": {"python": "3", "platform": "x"}}), encoding="utf-8")
    man = tmp_path / "ar.json"
    man.write_text(json.dumps(_manifest(
        [{"name": "full suite", "evidence": "forged.json", "expect_exit": 0}])), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "audit_replay", {"path": "ar.json"})
    assert ok is False
    assert "forged-evidence" in reason


def test_audit_replay_rejects_wrong_exit_code(tmp_path):
    rec = ce.record_command(tmp_path, f'"{sys.executable}" -c "import sys; sys.exit(3)"')
    backing = tmp_path / "suite.json"
    backing.write_text(json.dumps(rec), encoding="utf-8")
    man = tmp_path / "ar.json"
    man.write_text(json.dumps(_manifest(
        [{"name": "full suite", "evidence": "suite.json", "expect_exit": 0}])), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "audit_replay", {"path": "ar.json"})
    assert ok is False
    assert "exit" in reason


def test_audit_replay_passes_with_genuine_command_evidence(tmp_path):
    rec = ce.record_command(tmp_path, f'"{sys.executable}" -c "import sys; sys.exit(0)"')
    backing = tmp_path / "suite.json"
    backing.write_text(json.dumps(rec), encoding="utf-8")
    man = tmp_path / "ar.json"
    man.write_text(json.dumps(_manifest(
        [{"name": "full suite", "evidence": "suite.json", "expect_exit": 0}])), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "audit_replay", {"path": "ar.json"})
    assert ok is True and reason is None
