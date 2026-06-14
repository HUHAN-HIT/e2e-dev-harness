"""IMPLEMENTED-phase test-substance manifest validation (link ③).

The implementation worker submits a manifest declaring which tests prove which
acceptance items. The manifest is validated structurally AND against ground
truth: empty-shell detection re-analyses the real test files, and AC coverage is
cross-checked against the genuine acceptance contract from CLARIFIED — neither
can be satisfied by self-report alone.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from e2e_harness.core import acceptance, test_substance

SCHEMA = "e2e-dev-harness.test-substance.v1"
SUPPORTED_LANGUAGES = ("python", "java", "javascript", "typescript")


def _read_json(repo_root, rel: str):
    full = Path(rel)
    if not full.is_absolute():
        full = Path(repo_root) / rel
    if not full.is_file():
        return None, None
    try:
        return json.loads(full.read_text(encoding="utf-8")), full
    except (ValueError, OSError):
        return False, full


def validate_substance_manifest(obj, repo_root, state: dict | None = None,
                                module_hint: str | None = None) -> tuple[bool, str | None]:
    if not isinstance(obj, dict):
        return False, "not-object"
    if obj.get("schema") != SCHEMA:
        return False, "bad-schema"

    language = obj.get("language", "python")
    test_files = obj.get("test_files")
    if not isinstance(test_files, list) or not test_files:
        return False, "no-test-files"

    if state is not None:
        ok, reason = _validate_profile_grounding(obj, repo_root, state, test_files, language, module_hint)
        if not ok:
            return False, reason

    if language not in SUPPORTED_LANGUAGES:
        return False, "bad-language"

    red, green = obj.get("red_tests"), obj.get("green_tests")
    if not isinstance(red, list) or not red or not isinstance(green, list) or not green:
        return False, "no-red-green"
    if {_nfc(v) for v in red} != {_nfc(v) for v in green}:
        return False, "red-green-mismatch"  # RED and GREEN must be the same batch

    coverage = obj.get("ac_coverage")
    if not isinstance(coverage, dict) or not coverage:
        return False, "no-ac-coverage"

    # Cross-check coverage against the genuine contract (not self-reported ids).
    contract_path = obj.get("acceptance_contract_path")
    if not contract_path:
        return False, "no-contract-path"
    contract, _full = _read_json(repo_root, contract_path)
    if contract is None:
        return False, "contract-not-found"
    if contract is False:
        return False, "contract-not-json"
    ok, reason = acceptance.validate_contract(contract)
    if not ok:
        return False, f"bad-contract:{reason}"
    for ac_id in acceptance.ids(contract):
        if ac_id not in coverage:
            return False, f"uncovered:{ac_id}"

    # Empty-shell detection re-analyses the real files (not self-reportable).
    for rel in test_files:
        full = Path(rel)
        if not full.is_absolute():
            full = Path(repo_root) / rel
        if not full.is_file():
            return False, f"test-file-not-found:{rel}"
        source = full.read_text(encoding="utf-8", errors="replace")
        diag = test_substance.analyze_with_diagnostics(source, language)
        missing = _missing_warning(diag.get("warnings", []), obj.get("analyzer_warnings", []))
        if missing:
            return False, "missing-analyzer-warning:" + missing
        empties = [name for name, verdict in diag.get("verdicts", []) if verdict == "empty"]
        if empties:
            return False, f"empty-test:{rel}::{empties[0]}"

    return True, None


def _nfc(value) -> str:
    return unicodedata.normalize("NFC", str(value))


def _warning_key(warning) -> tuple[str | None, int | None]:
    if not isinstance(warning, dict):
        return None, None
    code = warning.get("code")
    line = warning.get("line")
    if line is None:
        return code, None
    return code, int(line)


def _missing_warning(required, declared) -> str | None:
    declared_keys = {_warning_key(w) for w in declared if isinstance(w, dict)}
    for warning in required:
        key = _warning_key(warning)
        if key not in declared_keys:
            code, line = key
            return f"{code}:{line}" if line is not None else str(code)
    return None


def _validate_profile_grounding(obj, repo_root, state, test_files, language,
                                module_hint: str | None) -> tuple[bool, str | None]:
    del obj, module_hint  # reserved for module-plan narrowing in the public validator shape
    binding = state.get("language") if isinstance(state, dict) else None
    if not isinstance(binding, dict) or not binding.get("profile_path"):
        return True, None
    profile, _full = _read_json(repo_root, binding["profile_path"])
    if profile in (None, False):
        return False, "language-profile-not-found" if profile is None else "language-profile-not-json"
    profiles = profile.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        return False, "bad-language-profile"
    matches = []
    for rel in test_files:
        file_matches = _matching_profiles(repo_root, rel, profiles)
        if len(file_matches) != 1:
            return False, "test-file-language-mismatch"
        matches.append(file_matches[0])
    langs = {m.get("language") for m in matches}
    if len(langs) != 1:
        return False, "test-file-language-mismatch"
    matched_language = next(iter(langs))
    if matched_language not in SUPPORTED_LANGUAGES:
        return False, "unsupported-test-substance-language"
    if language != matched_language:
        return False, "language-profile-mismatch"
    return True, None


def _matching_profiles(repo_root, rel, profiles) -> list[dict]:
    full = Path(rel)
    if not full.is_absolute():
        full = Path(repo_root) / rel
    try:
        rel_path = full.resolve().relative_to(Path(repo_root).resolve())
    except ValueError:
        return []
    out = []
    for prof in profiles:
        for root in prof.get("roots", []):
            root_path = Path("." if root in ("", ".") else root)
            try:
                rel_path.relative_to(root_path)
                out.append(prof)
                break
            except ValueError:
                continue
    return out
