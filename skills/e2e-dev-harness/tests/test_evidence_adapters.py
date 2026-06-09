import json
import sys
from pathlib import Path


def test_sha256_file_matches_hashlib(tmp_path):
    from e2e_harness.adapters.evidence import hashing
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    import hashlib
    assert hashing.sha256_file(f) == hashlib.sha256(b"hello").hexdigest()


def test_record_command_captures_exit_code_and_hashes(tmp_path):
    from e2e_harness.adapters.evidence import command_evidence as ce
    ev = ce.record_command(tmp_path, f'"{sys.executable}" -c "import sys; sys.exit(3)"')
    assert ev["schema"] == ce.COMMAND_EVIDENCE_SCHEMA
    assert ev["exit_code"] == 3
    assert len(ev["stdout_sha256"]) == 64
    assert ce.is_command_evidence(ev) is True


def test_is_command_evidence_rejects_plain_dict():
    from e2e_harness.adapters.evidence import command_evidence as ce
    assert ce.is_command_evidence({"foo": "bar"}) is False
