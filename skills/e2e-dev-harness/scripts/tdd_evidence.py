#!/usr/bin/env python3
"""Validate TDD red/green evidence at the depth required by the task."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import coverage_gate  # noqa: E402


MODES = ("off", "advisory", "basic", "strict", "auto")
STRICT_TIERS = {"critical", "audited"}
RED_HINT_RE = re.compile(r"\b(red|fail|failed|failure|expected)\b|\u5931\u8d25|\u9884\u671f", re.IGNORECASE)


def resolve_mode(mode: str, workflow_tier: str = "basic") -> str:
    if mode != "auto":
        return mode
    return "strict" if workflow_tier in STRICT_TIERS else "basic"


def repo_path(repo: Path, path: Path | None) -> Path | None:
    if path is None:
        return None
    root = repo.resolve()
    resolved = (path if path.is_absolute() else root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"TDD evidence path resolves outside repository: {path}") from error
    return resolved


def read_text(path: Path | None) -> tuple[str, list[str]]:
    if path is None:
        return "", ["TDD red evidence is required."]
    if not path.exists():
        return "", [f"TDD evidence is missing: {path}"]
    text = path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
    if not text.strip():
        return text, [f"TDD evidence is empty: {path}"]
    return text, []


def command_entries(text: str) -> tuple[list[dict], list[str]]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        return [], [f"TDD strict evidence must be JSON command evidence: {error}"]
    entries = coverage_gate.command_entries(parsed)
    if not entries:
        return [], ["TDD strict evidence must include command and exit_code."]
    return entries, []


def validate_red_basic(text: str) -> tuple[list[str], list[str]]:
    blocked: list[str] = []
    warnings: list[str] = []
    if not RED_HINT_RE.search(text):
        blocked.append("Basic TDD red evidence must state that the test failed for the expected reason.")
    if "todo" in text.lower() or "tbd" in text.lower():
        blocked.append("TDD red evidence contains unresolved TODO/TBD markers.")
    if not re.search(r"\b(test|tests|junit|mvn|assert)\b", text, re.IGNORECASE):
        warnings.append("Basic TDD red evidence should name the failing test or command.")
    return blocked, warnings


def validate_red_strict(text: str) -> tuple[list[dict], list[str], list[str]]:
    blocked: list[str] = []
    warnings: list[str] = []
    entries, parse_blockers = command_entries(text)
    blocked.extend(parse_blockers)
    normalized: list[dict] = []
    for index, entry in enumerate(entries, start=1):
        command = str(entry.get("command", "")).strip()
        exit_code = entry.get("exit_code")
        output = f"{entry.get('stdout_tail', '')}\n{entry.get('stderr_tail', '')}"
        if entry.get("skipped") is True:
            blocked.append(f"TDD red command {index} was skipped.")
        if not command:
            blocked.append(f"TDD red command {index} is missing command.")
        if not isinstance(exit_code, int):
            blocked.append(f"TDD red command {index} is missing integer exit_code.")
        elif exit_code == 0:
            blocked.append(f"TDD red command {index} unexpectedly passed; red evidence must fail before implementation.")
        if not RED_HINT_RE.search(output + " " + command):
            warnings.append(f"TDD red command {index} output should show the expected failing test or failure reason.")
        normalized.append({"command": command, "exit_code": exit_code})
    return normalized, blocked, warnings


def validate_green_strict(text: str) -> tuple[list[dict], list[str]]:
    blocked: list[str] = []
    entries, parse_blockers = command_entries(text)
    blocked.extend(parse_blockers)
    normalized: list[dict] = []
    for index, entry in enumerate(entries, start=1):
        command = str(entry.get("command", "")).strip()
        exit_code = entry.get("exit_code")
        if entry.get("skipped") is True:
            blocked.append(f"TDD green command {index} was skipped.")
        if not command:
            blocked.append(f"TDD green command {index} is missing command.")
        if not isinstance(exit_code, int):
            blocked.append(f"TDD green command {index} is missing integer exit_code.")
        elif exit_code != 0:
            blocked.append(f"TDD green command {index} failed with exit_code {exit_code}.")
        normalized.append({"command": command, "exit_code": exit_code})
    return normalized, blocked


def validate(
    repo: Path,
    red_evidence: Path | None,
    green_evidence: Path | None = None,
    phase: str = "implementation",
    mode: str = "basic",
    workflow_tier: str = "basic",
) -> dict:
    repo = repo.resolve()
    effective_mode = resolve_mode(mode, workflow_tier)
    blocked: list[str] = []
    warnings: list[str] = []
    red_commands: list[dict] = []
    green_commands: list[dict] = []
    if effective_mode == "off":
        return {
            "repo": str(repo),
            "ready": True,
            "blocked_reasons": [],
            "warnings": ["TDD evidence validation is disabled."],
            "mode": mode,
            "effective_mode": effective_mode,
        }
    try:
        red_path = repo_path(repo, red_evidence)
        green_path = repo_path(repo, green_evidence)
    except ValueError as error:
        return {"repo": str(repo), "ready": False, "blocked_reasons": [str(error)], "warnings": []}
    red_text, red_errors = read_text(red_path)
    blocked.extend(red_errors)
    if red_text:
        if effective_mode == "strict":
            red_commands, red_blocked, red_warnings = validate_red_strict(red_text)
            blocked.extend(red_blocked)
            warnings.extend(red_warnings)
        else:
            red_blocked, red_warnings = validate_red_basic(red_text)
            blocked.extend(red_blocked)
            warnings.extend(red_warnings)
    if effective_mode == "strict" and phase == "completion":
        green_text, green_errors = read_text(green_path)
        if green_errors:
            blocked.extend(error.replace("red", "green") for error in green_errors)
        elif green_text:
            green_commands, green_blocked = validate_green_strict(green_text)
            blocked.extend(green_blocked)
    if effective_mode == "advisory":
        warnings.extend(blocked)
        blocked = []
    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "mode": mode,
        "effective_mode": effective_mode,
        "phase": phase,
        "red_evidence": str(red_path) if red_path else None,
        "green_evidence": str(green_path) if green_path else None,
        "red_commands": red_commands,
        "green_commands": green_commands,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--red-evidence", type=Path)
    parser.add_argument("--green-evidence", type=Path)
    parser.add_argument("--phase", choices=["implementation", "completion"], default="implementation")
    parser.add_argument("--mode", choices=MODES, default="basic")
    parser.add_argument("--workflow-tier", default="basic")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = validate(args.repo, args.red_evidence, args.green_evidence, args.phase, args.mode, args.workflow_tier)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("TDD evidence: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
