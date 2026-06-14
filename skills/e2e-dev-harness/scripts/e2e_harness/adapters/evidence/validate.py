"""Validate a worker's evidence artifact: exists + non-empty + hash + command-evidence.

Command-evidence artifacts (test/verification commands) must additionally be *genuine*:
produced by command_evidence.record_command, not hand-written. We enforce that
structurally — real records always carry an `environment` block and 64-hex content
hashes; forged JSON with placeholder hashes (e.g. "verification_stdout") is rejected.
"""
from __future__ import annotations

import json
import shlex
from pathlib import Path

from e2e_harness.adapters.evidence import (
    adversarial, audit_replay, command_evidence, dispatch_invocation, hashing, substance,
)
from e2e_harness.adapters.evidence import scope as scope_ev
from e2e_harness.core import acceptance, module_plan, multitrack

# Evidence keys whose artifact must be command-evidence JSON with a specific exit code.
COMMAND_KEYS = {"failing_tests": "nonzero", "passing_tests": "zero", "verification": "zero"}

# Evidence keys whose artifact must be a JSON document passing a structural validator.
# Each validator takes (parsed_obj, repo_root) -> (ok, reason). A prose/empty file
# can no longer satisfy these gates.
#   acceptance_contract — link ①: machine-checkable acceptance criteria.
#   test_substance      — link ③: tests derive from the contract, assert real behaviour.
def _validate_acceptance_contract(obj, _repo) -> tuple[bool, str | None]:
    """Structure + clarification-completeness (link ①, fix A2).

    The contract must be well-formed AND carry no still-`open` question — an
    unresolved ledger means clarification has not run to completion, so CLARIFIED
    must not pass. Reason `open-questions:<id,id>` names exactly what is unresolved.
    """
    ok, reason = acceptance.validate_contract(obj)
    if not ok:
        return False, reason
    unresolved = acceptance.unresolved_questions(obj)
    if unresolved:
        return False, "open-questions:" + ",".join(unresolved)
    return True, None


STRUCTURED_KEYS = {
    "acceptance_contract": _validate_acceptance_contract,
    # link ④: PLANNED must emit a machine-readable module plan (functional slices
    # + dependency graph) so the engine can drive per-module progressive dev.
    "module_plan": lambda obj, _repo: module_plan.validate_module_plan(obj),
    "test_substance": substance.validate_substance_manifest,
    # link ②: VERIFIED requires a scope manifest; a COMPLETE claim on a grounded
    # subset is rejected (forces honest PARTIAL). PARTIAL itself is allowed.
    "scope_manifest": scope_ev.validate_scope_manifest,
    # F5: audited VERIFIED audit_replay must be a manifest whose every claim is backed
    # by genuine command-evidence — prose can no longer satisfy the gate.
    "audit_replay": audit_replay.validate_audit_replay,
    # F4: audited VERIFIED agent_team_dispatch must be a real dispatch-invocation whose
    # referenced team plan resolves — enforces the agent-team chain via the submit gate.
    "agent_team_dispatch": dispatch_invocation.validate_dispatch_invocation,
    # opt-in adversarial pipeline: each REVIEWED perspective key must be a structured
    # adversarial-review.v1 artifact whose `perspective` matches the key. Prose, empty
    # files, and mismatched/under-justified verdicts no longer satisfy the gate.
    "adversarial_code_review": lambda obj, _repo: adversarial.validate_adversarial_review(obj, "code"),
    "adversarial_design_review": lambda obj, _repo: adversarial.validate_adversarial_review(obj, "design"),
    "adversarial_test_design_review": lambda obj, _repo: adversarial.validate_adversarial_review(obj, "test-design"),
}

# Final-gate keys whose exit code is NEVER trusted from the record: the harness
# re-runs the recorded command and judges by the *replayed* exit code (#1 replay).
# This catches a worker that records a genuine failing run then hand-edits exit_code.
REPLAY_KEYS = {"verification"}

_PYTHON_TEST_MODULES = {"pytest", "unittest"}
_DIRECT_TEST_COMMANDS = {"pytest", "pytest3"}
_NODE_TEST_COMMANDS = {"vitest", "playwright"}
# jest sub-commands/flags that are NOT a test run. A bare `npx jest` and flag-only
# runs (e.g. `npx jest --runInBand`) ARE full test runs, so we cannot require a
# "test" token; instead we reject jest's known non-test entry points.
_JEST_NON_TEST_ARGS = {"--init", "--help", "-h", "--version", "-v"}


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
        if not args:
            return False
        runner = _command_name(args[0])
        rest = args[1:]
        if runner in _NODE_TEST_COMMANDS:        # vitest / playwright: unchanged, strict
            return "test" in rest
        if runner == "jest":                      # bare/flag jest = full test run; deny non-test subcommands
            return not (rest and rest[0] in _JEST_NON_TEST_ARGS)
        return False
    if name == "go":                              # first subcommand must be `test`
        return args[:1] == ["test"]
    if name == "cargo":                           # must invoke the `test` subcommand (stricter than `"test" in args`)
        return args[:1] == ["test"]
    if name in {"pnpm", "yarn"}:                  # mirror the npm rule
        return args[:1] == ["test"] or args[:2] == ["run", "test"]
    if name == "node":
        return len(args) >= 2 and args[0] == "--check"
    if name == "mvn":
        return "test" in args or any(arg.endswith(":test") for arg in args)
    if name in {"gradle", "gradlew"}:
        return "test" in args
    return False


def _path_of(entry) -> str:
    return entry["path"] if isinstance(entry, dict) else entry


def validate_evidence(repo_root, key: str, entry, *, skip_replay: bool = False,
                      state: dict | None = None) -> tuple[bool, str | None]:
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
    # Multi-track (B2): a per-module evidence key like `passing_tests#auth` is
    # validated by its base key's rule — the module suffix only namespaces which
    # module's gate the artifact satisfies, not how it is checked.
    lookup = multitrack.base_key(key)
    if lookup in STRUCTURED_KEYS:
        try:
            obj = json.loads(full.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False, "not-json"
        # F-4 and language profiles: validators that need trusted run-state keep
        # the same branch shape as scope_manifest instead of loading state again.
        if lookup == "scope_manifest":
            ok, reason = scope_ev.validate_scope_manifest(obj, repo_root, state)
        elif lookup == "test_substance":
            ok, reason = substance.validate_substance_manifest(
                obj, repo_root, state, module_hint=multitrack.module_of(key))
        else:
            ok, reason = STRUCTURED_KEYS[lookup](obj, repo_root)
        if not ok:
            return False, reason
    if lookup in COMMAND_KEYS:
        try:
            obj = json.loads(full.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False, "not-json"
        if not command_evidence.is_command_evidence(obj):
            return False, "not-command-evidence"
        if not command_evidence.is_genuine_command_evidence(obj):
            return False, "forged-evidence"
        ec = obj.get("exit_code")
        want = COMMAND_KEYS[lookup]
        if want == "zero" and ec != 0:
            return False, f"exit-code-{ec}"
        if want == "nonzero" and (ec == 0 or ec is None):
            return False, f"exit-code-{ec}"
        # #1 replay: the recorded exit code claims success — re-run the command and
        # judge by reality, so a hand-edited exit_code on an otherwise-genuine record
        # cannot pass the final gate.
        if lookup in REPLAY_KEYS and not skip_replay:
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
