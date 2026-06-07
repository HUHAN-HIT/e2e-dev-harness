"""Validate a worker's evidence artifact: exists + non-empty + hash + command-evidence."""
from __future__ import annotations

import json
from pathlib import Path

from harness_v2.adapters.evidence import command_evidence, hashing

# Evidence keys whose artifact must be command-evidence JSON with a specific exit code.
COMMAND_KEYS = {"failing_tests": "nonzero", "passing_tests": "zero"}


def _path_of(entry) -> str:
    return entry["path"] if isinstance(entry, dict) else entry


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
    if key in COMMAND_KEYS:
        try:
            obj = json.loads(full.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False, "not-json"
        if not command_evidence.is_command_evidence(obj):
            return False, "not-command-evidence"
        ec = obj.get("exit_code")
        want = COMMAND_KEYS[key]
        if want == "zero" and ec != 0:
            return False, f"exit-code-{ec}"
        if want == "nonzero" and (ec == 0 or ec is None):
            return False, f"exit-code-{ec}"
    return True, None
