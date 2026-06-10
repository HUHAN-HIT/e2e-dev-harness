import json
import sys
from pathlib import Path

from e2e_harness.core import lifecycle, gates
from e2e_harness import pipeline


def _phase(name):
    return next(p for p in lifecycle.build_spine(pipeline.active_phase_names("minimal")) if p.name == name)


def test_validate_missing_file_fails(tmp_path):
    from e2e_harness.adapters.evidence import validate
    ok, reason = validate.validate_evidence(tmp_path, "clarification", {"path": "nope.md"})
    assert ok is False
    assert reason == "file-not-found"


def test_validate_empty_file_fails(tmp_path):
    from e2e_harness.adapters.evidence import validate
    (tmp_path / "e.md").write_text("", encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "clarification", {"path": "e.md"})
    assert ok is False
    assert reason == "empty-file"


def test_validate_nonempty_doc_passes(tmp_path):
    from e2e_harness.adapters.evidence import validate
    (tmp_path / "c.md").write_text("real", encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "clarification", {"path": "c.md"})
    assert ok is True and reason is None


def test_validate_passing_tests_requires_zero_exit(tmp_path):
    from e2e_harness.adapters.evidence import command_evidence as ce, validate
    ev = ce.record_command(tmp_path, f'"{sys.executable}" -c "import sys; sys.exit(1)"')
    (tmp_path / "t.json").write_text(json.dumps(ev), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "passing_tests", {"path": "t.json"})
    assert ok is False and reason.startswith("exit-code")


def test_validate_failing_tests_requires_nonzero_exit(tmp_path):
    from e2e_harness.adapters.evidence import command_evidence as ce, validate
    ev = ce.record_command(tmp_path, f'"{sys.executable}" -c "import sys; sys.exit(0)"')
    (tmp_path / "t.json").write_text(json.dumps(ev), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "failing_tests", {"path": "t.json"})
    assert ok is False and reason.startswith("exit-code")


def test_gate_passes_with_repo_root_rejects_fake_path(tmp_path):
    rec = {"evidence": {"clarification": {"path": "ghost.md"}}}
    ok, missing = gates.gate_passes(_phase("CLARIFIED"), rec, repo_root=tmp_path)
    assert ok is False
    assert "clarification" in missing


def test_gate_passes_presence_only_without_repo_root():
    rec = {"evidence": {"clarification": "anything"}}
    ok, missing = gates.gate_passes(_phase("CLARIFIED"), rec)
    assert ok is True and missing == []


# --- #2 evidence anti-forgery: verification is command-evidence + structural authenticity ---

def _forged(**overrides):
    from e2e_harness.adapters.evidence import command_evidence as ce
    base = {
        "schema": ce.COMMAND_EVIDENCE_SCHEMA,
        "command": "mvn clean test",
        "argv": ["mvn", "clean", "test"],
        "exit_code": 0,
        "stdout_tail": "BUILD SUCCESS",
        "stderr_tail": "",
        "stdout_sha256": "0" * 64,
        "stderr_sha256": "0" * 64,
        "environment": {"python": "3.11", "platform": "win32"},
    }
    base.update(overrides)
    return base


def test_validate_verification_requires_zero_exit(tmp_path):
    from e2e_harness.adapters.evidence import command_evidence as ce, validate
    ev = ce.record_command(tmp_path, f'"{sys.executable}" -c "import sys; sys.exit(1)"')
    (tmp_path / "v.json").write_text(json.dumps(ev), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "verification", {"path": "v.json"})
    assert ok is False and reason.startswith("exit-code")


def test_validate_rejects_placeholder_sha256(tmp_path):
    from e2e_harness.adapters.evidence import validate
    forged = _forged(stdout_sha256="verification_stdout", stderr_sha256="def456")
    (tmp_path / "f.json").write_text(json.dumps(forged), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "verification", {"path": "f.json"})
    assert ok is False and reason.startswith("forged-evidence")


def test_validate_rejects_missing_environment(tmp_path):
    from e2e_harness.adapters.evidence import validate
    forged = _forged()
    forged.pop("environment")
    (tmp_path / "f.json").write_text(json.dumps(forged), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "verification", {"path": "f.json"})
    assert ok is False and reason.startswith("forged-evidence")


def test_validate_genuine_record_command_passes(tmp_path):
    from e2e_harness.adapters.evidence import command_evidence as ce, validate
    ev = ce.record_command(tmp_path, f'"{sys.executable}" -c "import sys; sys.exit(0)"')
    (tmp_path / "v.json").write_text(json.dumps(ev), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "verification", {"path": "v.json"})
    assert ok is True and reason is None


# --- #1 verification replay: harness re-runs the command, never trusts the worker's exit_code ---

def test_validate_verification_rejects_tampered_exit_code(tmp_path):
    """A worker records a genuinely FAILING run (real env + real hashes) then
    hand-edits exit_code to 0. #2 cannot see it (structure is authentic); #1's
    replay re-runs the recorded command and catches the lie."""
    from e2e_harness.adapters.evidence import command_evidence as ce, validate
    ev = ce.record_command(tmp_path, f'"{sys.executable}" -c "import sys; sys.exit(1)"')
    assert ev["exit_code"] == 1  # genuinely failing command
    ev["exit_code"] = 0          # tamper: claim success
    (tmp_path / "v.json").write_text(json.dumps(ev), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "verification", {"path": "v.json"})
    assert ok is False and reason.startswith("replay-exit")
