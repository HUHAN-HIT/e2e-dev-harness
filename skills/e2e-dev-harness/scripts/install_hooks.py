#!/usr/bin/env python3
"""Install or validate e2e-dev-harness hook configuration in a repository."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
HOOKS_DIR = SKILL_DIR / "hooks"
RUNTIME_TEMPLATES = {
    "claude": HOOKS_DIR / "claude-code-settings.example.json",
    "codex": HOOKS_DIR / "codex-pre-action.example.json",
    "gemini": HOOKS_DIR / "gemini-pre-action.example.json",
}
DEFAULT_TARGETS = {
    "claude": Path(".claude/settings.json"),
    "codex": Path(".codex/hooks/e2e-dev-harness-pre-action.json"),
    "gemini": Path(".gemini/hooks/e2e-dev-harness-pre-tool-use.json"),
}


def atomic_write_text(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        Path(tmp_name).unlink(missing_ok=True)
        raise


def repo_path(repo: Path, path: Path) -> Path:
    root = repo.resolve()
    resolved = (path if path.is_absolute() else root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"Hook target resolves outside repository: {path}") from error
    return resolved


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def template(runtime: str) -> dict:
    return load_json(RUNTIME_TEMPLATES[runtime])


def guard_script_path() -> Path:
    return SCRIPT_DIR / "phase_guard.py"


def quote_command_path(path: Path) -> str:
    return '"' + str(path).replace('"', '\\"') + '"'


def runtime_guard_command(repo: Path) -> str:
    return (
        f"{quote_command_path(Path(sys.executable))} "
        f"{quote_command_path(guard_script_path())} "
        f"{quote_command_path(repo.resolve())} "
        "--hook-input - --json"
    )


def rewrite_guard_command(value, repo: Path):
    if isinstance(value, dict):
        rewritten = {}
        for key, item in value.items():
            if key == "command" and isinstance(item, str) and "phase_guard.py" in item:
                rewritten[key] = runtime_guard_command(repo)
            else:
                rewritten[key] = rewrite_guard_command(item, repo)
        return rewritten
    if isinstance(value, list):
        return [rewrite_guard_command(item, repo) for item in value]
    return value


def hook_for_repo(runtime: str, repo: Path) -> dict:
    return rewrite_guard_command(template(runtime), repo)


def command_present(value) -> bool:
    if isinstance(value, dict):
        return any(command_present(item) for item in value.values())
    if isinstance(value, list):
        return any(command_present(item) for item in value)
    if isinstance(value, str):
        return "phase_guard.py" in value and "--hook-input" in value
    return False


def command_strings(value) -> list[str]:
    if isinstance(value, dict):
        results: list[str] = []
        for item in value.values():
            results.extend(command_strings(item))
        return results
    if isinstance(value, list):
        results: list[str] = []
        for item in value:
            results.extend(command_strings(item))
        return results
    if isinstance(value, str) and "phase_guard.py" in value:
        return [value]
    return []


def guard_command_targets_existing_script(data: dict) -> bool:
    expected = str(guard_script_path())
    commands = command_strings(data)
    return bool(commands) and guard_script_path().exists() and all(expected in command for command in commands)


def claude_bash_matcher_present(data: dict) -> bool:
    hooks = data.get("hooks", {})
    entries = hooks.get("PreToolUse") if isinstance(hooks, dict) else []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        matcher = str(entry.get("matcher", ""))
        if "Bash" in matcher:
            return True
    return False


def blocking_present(data: dict) -> bool:
    if data.get("blocking") is True:
        return True
    hooks = data.get("hooks", {})
    return isinstance(hooks, dict) and bool(hooks.get("PreToolUse"))


def validate_config(path: Path) -> dict:
    data = load_json(path)
    blocked: list[str] = []
    if not data:
        blocked.append(f"Hook config not found or unreadable: {path}")
    elif not command_present(data):
        blocked.append("Hook config must call phase_guard.py with --hook-input.")
    elif not blocking_present(data):
        blocked.append("Hook config must be blocking or define a PreToolUse blocking hook.")
    elif not guard_command_targets_existing_script(data):
        blocked.append("Hook command must point to the installed phase_guard.py absolute path, not a target-repo relative skills path.")
    elif path.as_posix().endswith(".claude/settings.json") and not claude_bash_matcher_present(data):
        blocked.append("Claude Code hook matcher must include Bash so shell-based code writes are checked.")
    return {
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": [],
        "target": str(path),
    }


def merge_claude(existing: dict, hook: dict) -> dict:
    merged = dict(existing)
    hooks = merged.setdefault("hooks", {})
    pre_tool = hooks.setdefault("PreToolUse", [])
    incoming = hook.get("hooks", {}).get("PreToolUse", [])
    existing_serialized = {json.dumps(item, sort_keys=True) for item in pre_tool if isinstance(item, dict)}
    for item in incoming:
        serialized = json.dumps(item, sort_keys=True)
        if serialized not in existing_serialized:
            pre_tool.append(item)
            existing_serialized.add(serialized)
    return merged


def install(repo: Path, runtime: str, target: Path | None = None, dry_run: bool = False) -> dict:
    repo = repo.resolve()
    target_path = repo_path(repo, target or DEFAULT_TARGETS[runtime])
    hook = hook_for_repo(runtime, repo)
    if runtime == "claude":
        current = rewrite_guard_command(load_json(target_path), repo)
        output = merge_claude(current, hook)
    else:
        output = hook
    result = {
        "ready": True,
        "blocked_reasons": [],
        "warnings": [],
        "runtime": runtime,
        "target": str(target_path),
        "dry_run": dry_run,
        "installed": not dry_run,
    }
    if dry_run:
        result["planned_config"] = output
        return result
    atomic_write_text(target_path, json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    validation = validate_config(target_path)
    result["ready"] = validation["ready"]
    result["blocked_reasons"] = validation["blocked_reasons"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--runtime", choices=sorted(RUNTIME_TEMPLATES), required=True)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        target = repo_path(args.repo, args.target or DEFAULT_TARGETS[args.runtime])
        result = validate_config(target) if args.check else install(args.repo, args.runtime, args.target, args.dry_run)
    except ValueError as error:
        result = {"ready": False, "blocked_reasons": [str(error)], "warnings": []}
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Hook install: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
