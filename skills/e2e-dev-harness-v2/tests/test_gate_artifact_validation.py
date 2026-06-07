import json
import sys
from pathlib import Path

from harness_v2.core import lifecycle, gates
from harness_v2 import pipeline


def _phase(name):
    return next(p for p in lifecycle.build_spine(pipeline.active_phase_names("minimal")) if p.name == name)


def test_validate_missing_file_fails(tmp_path):
    from harness_v2.adapters.evidence import validate
    ok, reason = validate.validate_evidence(tmp_path, "clarification", {"path": "nope.md"})
    assert ok is False
    assert reason == "file-not-found"


def test_validate_empty_file_fails(tmp_path):
    from harness_v2.adapters.evidence import validate
    (tmp_path / "e.md").write_text("", encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "clarification", {"path": "e.md"})
    assert ok is False
    assert reason == "empty-file"


def test_validate_nonempty_doc_passes(tmp_path):
    from harness_v2.adapters.evidence import validate
    (tmp_path / "c.md").write_text("real", encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "clarification", {"path": "c.md"})
    assert ok is True and reason is None


def test_validate_passing_tests_requires_zero_exit(tmp_path):
    from harness_v2.adapters.evidence import command_evidence as ce, validate
    ev = ce.record_command(tmp_path, f'"{sys.executable}" -c "import sys; sys.exit(1)"')
    (tmp_path / "t.json").write_text(json.dumps(ev), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "passing_tests", {"path": "t.json"})
    assert ok is False and reason.startswith("exit-code")


def test_validate_failing_tests_requires_nonzero_exit(tmp_path):
    from harness_v2.adapters.evidence import command_evidence as ce, validate
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
