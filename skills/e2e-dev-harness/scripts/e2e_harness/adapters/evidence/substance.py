"""IMPLEMENTED-phase test-substance manifest validation (link ③).

The implementation worker submits a manifest declaring which tests prove which
acceptance items. The manifest is validated structurally AND against ground
truth: empty-shell detection re-analyses the real test files, and AC coverage is
cross-checked against the genuine acceptance contract from CLARIFIED — neither
can be satisfied by self-report alone.
"""
from __future__ import annotations

import json
from pathlib import Path

from e2e_harness.core import acceptance, test_substance

SCHEMA = "e2e-dev-harness.test-substance.v1"


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


def validate_substance_manifest(obj, repo_root) -> tuple[bool, str | None]:
    if not isinstance(obj, dict):
        return False, "not-object"
    if obj.get("schema") != SCHEMA:
        return False, "bad-schema"

    language = obj.get("language", "python")
    if language not in ("python", "java"):
        return False, "bad-language"

    test_files = obj.get("test_files")
    if not isinstance(test_files, list) or not test_files:
        return False, "no-test-files"

    red, green = obj.get("red_tests"), obj.get("green_tests")
    if not isinstance(red, list) or not red or not isinstance(green, list) or not green:
        return False, "no-red-green"
    if set(red) != set(green):
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
        empties = test_substance.empties(source, language)
        if empties:
            return False, f"empty-test:{rel}::{empties[0]}"

    return True, None
