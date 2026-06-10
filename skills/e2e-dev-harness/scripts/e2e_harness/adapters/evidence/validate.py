"""Validate a worker's evidence artifact: exists + non-empty + hash + command-evidence.

Command-evidence artifacts (test/verification commands) must additionally be *genuine*:
produced by command_evidence.record_command, not hand-written. We enforce that
structurally — real records always carry an `environment` block and 64-hex content
hashes; forged JSON with placeholder hashes (e.g. "verification_stdout") is rejected.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from e2e_harness.adapters.evidence import command_evidence, hashing, substance
from e2e_harness.adapters.evidence import scope as scope_ev
from e2e_harness.core import acceptance

# Evidence keys whose artifact must be command-evidence JSON with a specific exit code.
COMMAND_KEYS = {"failing_tests": "nonzero", "passing_tests": "zero", "verification": "zero"}

# Evidence keys whose artifact must be a JSON document passing a structural validator.
# Each validator takes (parsed_obj, repo_root) -> (ok, reason). A prose/empty file
# can no longer satisfy these gates.
#   acceptance_contract — link ①: machine-checkable acceptance criteria.
#   test_substance      — link ③: tests derive from the contract, assert real behaviour.
STRUCTURED_KEYS = {
    "acceptance_contract": lambda obj, _repo: acceptance.validate_contract(obj),
    "test_substance": substance.validate_substance_manifest,
    # link ②: VERIFIED requires a scope manifest; a COMPLETE claim on a grounded
    # subset is rejected (forces honest PARTIAL). PARTIAL itself is allowed.
    "scope_manifest": scope_ev.validate_scope_manifest,
}

# Final-gate keys whose exit code is NEVER trusted from the record: the harness
# re-runs the recorded command and judges by the *replayed* exit code (#1 replay).
# This catches a worker that records a genuine failing run then hand-edits exit_code.
REPLAY_KEYS = {"verification"}

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _path_of(entry) -> str:
    return entry["path"] if isinstance(entry, dict) else entry


def _is_genuine_command_evidence(obj) -> bool:
    """True only for records that bear record_command's tamper-evident structure."""
    if not isinstance(obj.get("environment"), dict):
        return False
    for hash_key in ("stdout_sha256", "stderr_sha256"):
        value = obj.get(hash_key)
        if not isinstance(value, str) or not _HEX64.match(value):
            return False
    return True


def validate_evidence(repo_root, key: str, entry) -> tuple[bool, str | None]:
    path = _path_of(entry)
    if not path:
        return False, "no-path"
    candidate = Path(path)
    full = candidate if candidate.is_absolute() else Path(repo_root) / candidate
    if not full.is_file():
        return False, "file-not-found"
    if full.stat().st_size == 0:
        return False, "empty-file"
    if isinstance(entry, dict) and entry.get("sha256"):
        if hashing.sha256_file(full) != entry["sha256"]:
            return False, "hash-mismatch"
    if key in STRUCTURED_KEYS:
        try:
            obj = json.loads(full.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False, "not-json"
        ok, reason = STRUCTURED_KEYS[key](obj, repo_root)
        if not ok:
            return False, reason
    if key in COMMAND_KEYS:
        try:
            obj = json.loads(full.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False, "not-json"
        if not command_evidence.is_command_evidence(obj):
            return False, "not-command-evidence"
        if not _is_genuine_command_evidence(obj):
            return False, "forged-evidence"
        ec = obj.get("exit_code")
        want = COMMAND_KEYS[key]
        if want == "zero" and ec != 0:
            return False, f"exit-code-{ec}"
        if want == "nonzero" and (ec == 0 or ec is None):
            return False, f"exit-code-{ec}"
        # #1 replay: the recorded exit code claims success — re-run the command and
        # judge by reality, so a hand-edited exit_code on an otherwise-genuine record
        # cannot pass the final gate.
        if key in REPLAY_KEYS:
            replay = command_evidence.record_command(obj.get("cwd") or repo_root, obj.get("command", ""))
            actual = replay.get("exit_code")
            if want == "zero" and actual != 0:
                return False, f"replay-exit-{actual}"
            if want == "nonzero" and (actual == 0 or actual is None):
                return False, f"replay-exit-{actual}"
    return True, None
