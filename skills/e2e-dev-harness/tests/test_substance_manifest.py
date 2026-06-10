"""IMPLEMENTED-phase test-substance manifest validator (link ③).

The manifest is self-contained but not self-certifying: red/green-same-batch and
AC-coverage are declared, while empty-shell detection RE-ANALYSES the real test
files (a worker cannot self-report its way past an empty test), and AC coverage
is cross-checked against the genuine acceptance contract produced at CLARIFIED.
"""
import json

from e2e_harness.adapters.evidence import substance
from e2e_harness.core import acceptance


def _contract_file(repo, *ids):
    obj = {"schema": acceptance.SCHEMA,
           "items": [{"id": i, "criterion": "c", "observable_behavior": "o"} for i in ids]}
    p = repo / "acceptance-contract.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return "acceptance-contract.json"


def _test_file(repo, name, body):
    p = repo / name
    p.write_text(body, encoding="utf-8")
    return name


def _manifest(repo, *, test_files, red, green, coverage, contract="acceptance-contract.json",
              language="python"):
    return {
        "schema": substance.SCHEMA,
        "acceptance_contract_path": contract,
        "language": language,
        "test_files": test_files,
        "red_tests": red,
        "green_tests": green,
        "ac_coverage": coverage,
    }


def test_wellformed_manifest_passes(tmp_path):
    _contract_file(tmp_path, "AC-001")
    tf = _test_file(tmp_path, "test_x.py", "def test_a():\n    assert foo() == 1\n")
    man = _manifest(tmp_path, test_files=[tf], red=["test_x::test_a"],
                    green=["test_x::test_a"], coverage={"AC-001": ["test_x::test_a"]})
    ok, reason = substance.validate_substance_manifest(man, tmp_path)
    assert ok is True and reason is None


def test_bad_schema_rejected(tmp_path):
    man = _manifest(tmp_path, test_files=["x"], red=["a"], green=["a"], coverage={"AC-001": ["a"]})
    man["schema"] = "nope"
    ok, reason = substance.validate_substance_manifest(man, tmp_path)
    assert ok is False and reason == "bad-schema"


def test_red_green_mismatch_rejected(tmp_path):
    _contract_file(tmp_path, "AC-001")
    tf = _test_file(tmp_path, "test_x.py", "def test_a():\n    assert x == 1\n")
    man = _manifest(tmp_path, test_files=[tf], red=["test_x::test_a"],
                    green=["test_x::test_b"], coverage={"AC-001": ["test_x::test_a"]})
    ok, reason = substance.validate_substance_manifest(man, tmp_path)
    assert ok is False and reason == "red-green-mismatch"


def test_empty_shell_test_is_rejected(tmp_path):
    _contract_file(tmp_path, "AC-001")
    tf = _test_file(tmp_path, "test_x.py", "def test_a():\n    service.freeze()  # empty shell: no assertion\n")
    man = _manifest(tmp_path, test_files=[tf], red=["test_x::test_a"],
                    green=["test_x::test_a"], coverage={"AC-001": ["test_x::test_a"]})
    ok, reason = substance.validate_substance_manifest(man, tmp_path)
    assert ok is False and reason.startswith("empty-test:")


def test_uncovered_acceptance_id_is_rejected(tmp_path):
    _contract_file(tmp_path, "AC-001", "AC-002")
    tf = _test_file(tmp_path, "test_x.py", "def test_a():\n    assert x == 1\n")
    man = _manifest(tmp_path, test_files=[tf], red=["test_x::test_a"],
                    green=["test_x::test_a"], coverage={"AC-001": ["test_x::test_a"]})
    ok, reason = substance.validate_substance_manifest(man, tmp_path)
    assert ok is False and reason == "uncovered:AC-002"


def test_missing_test_file_is_rejected(tmp_path):
    _contract_file(tmp_path, "AC-001")
    man = _manifest(tmp_path, test_files=["nope.py"], red=["a"], green=["a"],
                    coverage={"AC-001": ["a"]})
    ok, reason = substance.validate_substance_manifest(man, tmp_path)
    assert ok is False and reason.startswith("test-file-not-found:")


def test_validate_evidence_routes_substance_key(tmp_path):
    from e2e_harness.adapters.evidence import validate
    _contract_file(tmp_path, "AC-001")
    _test_file(tmp_path, "test_x.py", "def test_a():\n    assert x == 1\n")
    man = _manifest(tmp_path, test_files=["test_x.py"], red=["test_x::test_a"],
                    green=["test_x::test_a"], coverage={"AC-001": ["test_x::test_a"]})
    p = tmp_path / "substance.json"
    p.write_text(json.dumps(man), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "test_substance", "substance.json")
    assert ok is True and reason is None
