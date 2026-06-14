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
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return name


def _manifest(repo, *, test_files, red, green, coverage, contract="acceptance-contract.json",
              language="python", analyzer_warnings=None):
    obj = {
        "schema": substance.SCHEMA,
        "acceptance_contract_path": contract,
        "language": language,
        "test_files": test_files,
        "red_tests": red,
        "green_tests": green,
        "ac_coverage": coverage,
    }
    if analyzer_warnings is not None:
        obj["analyzer_warnings"] = analyzer_warnings
    return obj


def _language_profile(repo, profiles):
    run_dir = repo / "docs" / "agent-runs" / "r1"
    run_dir.mkdir(parents=True, exist_ok=True)
    profile = {
        "schema": "e2e-harness.language-profile.v1",
        "profiles": profiles,
        "primary_language": profiles[0]["language"],
        "warnings": [],
    }
    p = run_dir / "language-profile.json"
    p.write_text(json.dumps(profile), encoding="utf-8")
    return {
        "language": {
            "schema": "e2e-harness.language-binding.v1",
            "profile_path": str(p.relative_to(repo)),
            "primary_language": profiles[0]["language"],
            "profiles": [pr["language"] for pr in profiles],
            "source": "detected",
        }
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


def test_javascript_manifest_accepts_real_assertions(tmp_path):
    _contract_file(tmp_path, "AC-001")
    tf = _test_file(tmp_path, "app.test.js",
                    "test('renders empty state', () => { expect(view()).toBe('empty') })")
    man = _manifest(tmp_path, test_files=[tf], red=["renders empty state"],
                    green=["renders empty state"], coverage={"AC-001": ["renders empty state"]},
                    language="javascript", analyzer_warnings=[])

    ok, reason = substance.validate_substance_manifest(man, tmp_path)

    assert ok is True and reason is None


def test_red_green_names_are_compared_after_unicode_nfc(tmp_path):
    _contract_file(tmp_path, "AC-001")
    tf = _test_file(tmp_path, "app.test.ts",
                    "test('é renders', () => { expect(view()).toBe('ok') })")
    man = _manifest(tmp_path, test_files=[tf], red=["e\u0301 renders"],
                    green=["é renders"], coverage={"AC-001": ["é renders"]},
                    language="typescript", analyzer_warnings=[])

    ok, reason = substance.validate_substance_manifest(man, tmp_path)

    assert ok is True and reason is None


def test_analyzer_warnings_must_be_declared_by_identity(tmp_path):
    _contract_file(tmp_path, "AC-001")
    tf = _test_file(tmp_path, "broken.test.ts", "test('broken', () => { expect(x).toBe(1)")
    man = _manifest(tmp_path, test_files=[tf], red=["broken"], green=["broken"],
                    coverage={"AC-001": ["broken"]}, language="typescript",
                    analyzer_warnings=[])

    ok, reason = substance.validate_substance_manifest(man, tmp_path)

    assert ok is False
    assert reason == "missing-analyzer-warning:analyzer-limitation:1"

    man["analyzer_warnings"] = [{"code": "analyzer-limitation", "line": 1,
                                 "message": "different wording is allowed"}]
    ok, reason = substance.validate_substance_manifest(man, tmp_path)
    assert ok is True and reason is None


def test_state_profile_rejects_manifest_language_mismatch(tmp_path):
    _contract_file(tmp_path, "AC-001")
    tf = _test_file(tmp_path, "ui/App.test.tsx",
                    "test('renders empty state', () => { expect(view()).toBe('empty') })")
    state = _language_profile(tmp_path, [{
        "language": "typescript",
        "roots": ["ui"],
        "test_runners": ["vitest"],
        "package_managers": ["npm"],
        "capabilities": {},
    }])
    man = _manifest(tmp_path, test_files=[tf], red=["renders empty state"],
                    green=["renders empty state"], coverage={"AC-001": ["renders empty state"]},
                    language="python")

    ok, reason = substance.validate_substance_manifest(man, tmp_path, state=state)

    assert ok is False
    assert reason == "language-profile-mismatch"


def test_state_profile_allows_matching_multilanguage_root(tmp_path):
    _contract_file(tmp_path, "AC-001")
    tf = _test_file(tmp_path, "ui/App.test.tsx",
                    "test('renders empty state', () => { expect(view()).toBe('empty') })")
    state = _language_profile(tmp_path, [
        {"language": "java", "roots": ["api"], "test_runners": ["maven"],
         "package_managers": [], "capabilities": {}},
        {"language": "typescript", "roots": ["ui"], "test_runners": ["vitest"],
         "package_managers": ["npm"], "capabilities": {}},
    ])
    man = _manifest(tmp_path, test_files=[tf], red=["renders empty state"],
                    green=["renders empty state"], coverage={"AC-001": ["renders empty state"]},
                    language="typescript", analyzer_warnings=[])

    ok, reason = substance.validate_substance_manifest(man, tmp_path, state=state)

    assert ok is True and reason is None
