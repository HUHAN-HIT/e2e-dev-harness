"""Validate a worker's evidence artifact: exists + non-empty + hash + command-evidence.

Command-evidence artifacts (test/verification commands) must additionally be *genuine*:
produced by command_evidence.record_command, not hand-written. We enforce that
structurally — real records always carry an `environment` block and 64-hex content
hashes; forged JSON with placeholder hashes (e.g. "verification_stdout") is rejected.
"""
from __future__ import annotations

import json
import re
import shlex
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
_PYTHON_TEST_MODULES = {"pytest", "unittest"}
_DIRECT_TEST_COMMANDS = {"pytest", "pytest3"}
_NODE_TEST_COMMANDS = {"vitest", "playwright"}


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _command_name(value: str) -> str:
    name = Path(value).name.lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _replay_cwd(repo_root, recorded_cwd) -> tuple[Path | None, str | None]:
    repo = Path(repo_root).resolve()
    cwd = Path(recorded_cwd or repo).resolve()
    if not _is_relative_to(cwd, repo):
        return None, "replay-cwd-outside-repo"
    return cwd, None


def _replay_command_allowed(command: str) -> bool:
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        return False
    if not argv:
        return False
    name = _command_name(argv[0])
    args = argv[1:]
    if name in {"python", "python3", "py"}:
        return len(args) >= 2 and args[0] == "-m" and args[1] in _PYTHON_TEST_MODULES
    if name in _DIRECT_TEST_COMMANDS:
        return True
    if name == "npm":
        return args[:1] == ["test"] or args[:2] == ["run", "test"]
    if name == "npx":
        return bool(args) and _command_name(args[0]) in _NODE_TEST_COMMANDS and "test" in args[1:]
    if name == "node":
        return len(args) >= 2 and args[0] == "--check"
    if name == "mvn":
        return "test" in args or any(arg.endswith(":test") for arg in args)
    if name in {"gradle", "gradlew"}:
        return "test" in args
    return False


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


def validate_evidence(repo_root, key: str, entry, *, skip_replay: bool = False) -> tuple[bool, str | None]:
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
        if key in REPLAY_KEYS and not skip_replay:
            command = obj.get("command", "")
            cwd, reason = _replay_cwd(repo_root, obj.get("cwd"))
            if reason:
                return False, reason
            if not _replay_command_allowed(command):
                return False, "replay-command-disallowed"
            replay = command_evidence.record_command(cwd, command)
            actual = replay.get("exit_code")
            if want == "zero" and actual != 0:
                return False, f"replay-exit-{actual}"
            if want == "nonzero" and (actual == 0 or actual is None):
                return False, f"replay-exit-{actual}"
    return True, None
