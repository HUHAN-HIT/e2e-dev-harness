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
    "opencode": HOOKS_DIR / "opencode-plugin.example.js",
}
DEFAULT_TARGETS = {
    "claude": Path(".claude/settings.json"),
    "codex": Path(".codex/hooks/e2e-dev-harness-pre-action.json"),
    "gemini": Path(".gemini/hooks/e2e-dev-harness-pre-tool-use.json"),
    "opencode": Path(".opencode/plugins/e2e-dev-harness.js"),
}
TEXT_RUNTIMES = {"opencode"}


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


def template_text(runtime: str) -> str:
    return RUNTIME_TEMPLATES[runtime].read_text(encoding="utf-8")


def render_runtime_paths(value, repo: Path):
    if isinstance(value, dict):
        return {key: render_runtime_paths(item, repo) for key, item in value.items()}
    if isinstance(value, list):
        return [render_runtime_paths(item, repo) for item in value]
    if isinstance(value, str):
        return (
            value.replace("C:\\absolute\\path\\to\\python.exe", sys.executable)
            .replace("C:\\absolute\\path\\to\\skills\\e2e-dev-harness\\scripts\\phase_guard.py", str(SCRIPT_DIR / "phase_guard.py"))
            .replace("C:\\absolute\\path\\to\\skills\\e2e-dev-harness\\scripts\\harness_stop_guard.py", str(SCRIPT_DIR / "harness_stop_guard.py"))
            .replace("C:\\absolute\\path\\to\\target-repo", str(repo.resolve()))
        )
    return value


def render_runtime_text(value: str, repo: Path) -> str:
    return (
        value.replace("__E2E_DEV_HARNESS_PYTHON__", json.dumps(sys.executable))
        .replace("__E2E_DEV_HARNESS_PHASE_GUARD__", json.dumps(str(SCRIPT_DIR / "phase_guard.py")))
        .replace("__E2E_DEV_HARNESS_TARGET_REPO__", json.dumps(str(repo.resolve())))
        .replace("__E2E_DEV_HARNESS_STOP_GUARD__", json.dumps(str(SCRIPT_DIR / "harness_stop_guard.py")))
    )


def phase_guard_command_present(value) -> bool:
    if isinstance(value, dict):
        return any(phase_guard_command_present(item) for item in value.values())
    if isinstance(value, list):
        return any(phase_guard_command_present(item) for item in value)
    if isinstance(value, str):
        return "phase_guard.py" in value and "--hook-input" in value
    return False


def current_guard_script_present(value, script_name: str) -> bool:
    expected = str(SCRIPT_DIR / script_name).replace("\\", "/")
    if isinstance(value, dict):
        return any(current_guard_script_present(item, script_name) for item in value.values())
    if isinstance(value, list):
        return any(current_guard_script_present(item, script_name) for item in value)
    if isinstance(value, str):
        return expected in value.replace("\\", "/")
    return False


def normalized_path_text(value: str) -> str:
    text = value.replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text


def target_repo_present(value, repo: Path) -> bool:
    expected = normalized_path_text(str(repo.resolve()))
    if isinstance(value, dict):
        return any(target_repo_present(item, repo) for item in value.values())
    if isinstance(value, list):
        return any(target_repo_present(item, repo) for item in value)
    if isinstance(value, str):
        return expected in normalized_path_text(value)
    return False


def claude_hook_entries(data: dict, event: str) -> list:
    hooks = data.get("hooks", {})
    entries = hooks.get(event) if isinstance(hooks, dict) else []
    return entries if isinstance(entries, list) else []


def opencode_plugin_target(path: Path) -> bool:
    normalized = path.as_posix()
    return normalized.endswith(".opencode/plugins/e2e-dev-harness.js")


def validate_opencode_plugin(path: Path) -> dict:
    blocked: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    if not text:
        blocked.append(f"OpenCode plugin not found or unreadable: {path}")
    elif "tool.execute.before" not in text:
        blocked.append("OpenCode plugin must register a blocking tool.execute.before handler.")
    elif "phase_guard.py" not in text or "--hook-input" not in text:
        blocked.append("OpenCode plugin must call phase_guard.py with --hook-input.")
    elif repo_relative_guard_present(text):
        blocked.append("OpenCode plugin must use absolute paths to harness guard scripts, not repo-relative skills/e2e-dev-harness paths.")
    elif "--require-active-run-for-read" not in text:
        blocked.append("OpenCode plugin must include --require-active-run-for-read so code exploration starts inside an active harness run.")
    elif "--require-session-checkpoint" not in text:
        blocked.append("OpenCode plugin must include --require-session-checkpoint so resumed sessions reload run-state before code writes.")
    elif "throw new Error" not in text:
        blocked.append("OpenCode plugin must throw on phase_guard.py failure so the tool execution is blocked.")
    return {
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": [],
        "target": str(path),
        "runtime": "opencode",
    }


def stop_guard_command_present(value) -> bool:
    if isinstance(value, dict):
        return any(stop_guard_command_present(item) for item in value.values())
    if isinstance(value, list):
        return any(stop_guard_command_present(item) for item in value)
    if isinstance(value, str):
        return "harness_stop_guard.py" in value and "--hook-input" in value
    return False


def strict_stop_guard_present(value) -> bool:
    if isinstance(value, dict):
        return any(strict_stop_guard_present(item) for item in value.values())
    if isinstance(value, list):
        return any(strict_stop_guard_present(item) for item in value)
    if isinstance(value, str):
        return "harness_stop_guard.py" in value and "--strict" in value
    return False


def read_guard_present(value) -> bool:
    if isinstance(value, dict):
        return any(read_guard_present(item) for item in value.values())
    if isinstance(value, list):
        return any(read_guard_present(item) for item in value)
    if isinstance(value, str):
        return "--require-active-run-for-read" in value
    return False


def session_checkpoint_guard_present(value) -> bool:
    if isinstance(value, dict):
        return any(session_checkpoint_guard_present(item) for item in value.values())
    if isinstance(value, list):
        return any(session_checkpoint_guard_present(item) for item in value)
    if isinstance(value, str):
        return "--require-session-checkpoint" in value
    return False


def conflicting_fact_force_hook_present(data: dict) -> bool:
    for entry in claude_hook_entries(data, "PreToolUse"):
        if not isinstance(entry, dict):
            continue
        matcher = str(entry.get("matcher", ""))
        matched_tools = {part.strip() for part in matcher.split("|") if part.strip()}
        if not matched_tools.intersection({"Write", "Edit", "Update", "MultiEdit", "NotebookEdit", "Bash"}):
            continue
        serialized = json.dumps(entry, ensure_ascii=False).lower()
        if "gateguard-fact-force" in serialized:
            return True
    return False


def repo_relative_guard_present(value) -> bool:
    if isinstance(value, dict):
        return any(repo_relative_guard_present(item) for item in value.values())
    if isinstance(value, list):
        return any(repo_relative_guard_present(item) for item in value)
    if isinstance(value, str):
        normalized = value.replace("\\", "/")
        absolute_phase_guard = str(SCRIPT_DIR / "phase_guard.py").replace("\\", "/")
        absolute_stop_guard = str(SCRIPT_DIR / "harness_stop_guard.py").replace("\\", "/")
        phase_relative = "skills/e2e-dev-harness/scripts/phase_guard.py" in normalized and absolute_phase_guard not in normalized
        stop_relative = "skills/e2e-dev-harness/scripts/harness_stop_guard.py" in normalized and absolute_stop_guard not in normalized
        return phase_relative or stop_relative
    return False


def claude_matcher_has(data: dict, required: str) -> bool:
    for entry in claude_hook_entries(data, "PreToolUse"):
        if not isinstance(entry, dict):
            continue
        matcher = str(entry.get("matcher", ""))
        if required in {part.strip() for part in matcher.split("|")}:
            return True
    return False


def claude_stop_hook_present(data: dict) -> bool:
    return stop_guard_command_present(claude_hook_entries(data, "Stop"))


def blocking_present(data: dict) -> bool:
    if data.get("blocking") is True:
        return True
    hooks = data.get("hooks", {})
    return isinstance(hooks, dict) and bool(hooks.get("PreToolUse"))


def validate_config(path: Path, repo: Path | None = None) -> dict:
    if opencode_plugin_target(path):
        return validate_opencode_plugin(path)
    data = load_json(path)
    blocked: list[str] = []
    is_claude = path.as_posix().endswith(".claude/settings.json")
    pre_tool_entries = claude_hook_entries(data, "PreToolUse") if is_claude else []
    stop_entries = claude_hook_entries(data, "Stop") if is_claude else []
    if not data:
        blocked.append(f"Hook config not found or unreadable: {path}")
    elif is_claude and not phase_guard_command_present(pre_tool_entries):
        blocked.append("Claude Code hook config must call phase_guard.py from PreToolUse; PostToolUse is audit-only and cannot block writes.")
    elif not is_claude and not phase_guard_command_present(data):
        blocked.append("Hook config must call phase_guard.py with --hook-input.")
    elif repo_relative_guard_present(data):
        blocked.append("Hook config must use absolute paths to harness guard scripts, not repo-relative skills/e2e-dev-harness paths.")
    elif is_claude and not current_guard_script_present(pre_tool_entries, "phase_guard.py"):
        blocked.append(
            "Claude Code PreToolUse hook must call the installed phase_guard.py at "
            + str(SCRIPT_DIR / "phase_guard.py")
            + "; rerun install_hooks.py instead of hand-editing settings."
        )
    elif not is_claude and not current_guard_script_present(data, "phase_guard.py"):
        blocked.append(
            "Hook config must call the installed phase_guard.py at "
            + str(SCRIPT_DIR / "phase_guard.py")
            + "; rerun install_hooks.py instead of hand-editing settings."
        )
    elif repo and is_claude and not target_repo_present(pre_tool_entries, repo):
        blocked.append("Claude Code PreToolUse hook must target this repository: " + str(repo.resolve()))
    elif repo and not is_claude and not target_repo_present(data, repo):
        blocked.append("Hook config must target this repository: " + str(repo.resolve()))
    elif not read_guard_present(data):
        blocked.append("Hook config must include --require-active-run-for-read so code exploration starts inside an active harness run.")
    elif is_claude and not session_checkpoint_guard_present(pre_tool_entries):
        blocked.append("Claude Code hook config must include --require-session-checkpoint so resumed sessions reload run-state before code writes.")
    elif not blocking_present(data):
        blocked.append("Hook config must be blocking or define a PreToolUse blocking hook.")
    elif is_claude and not claude_matcher_has(data, "Bash"):
        blocked.append("Claude Code hook matcher must include Bash so shell-based code writes are checked.")
    elif is_claude and not claude_matcher_has(data, "Update"):
        blocked.append("Claude Code hook matcher must include Update so Claude's update-style code edits are checked.")
    elif is_claude and not claude_matcher_has(data, "Task"):
        blocked.append("Claude Code hook matcher must include Task so code-agent dispatch cannot bypass clarify/TDD gates.")
    elif is_claude and conflicting_fact_force_hook_present(data):
        blocked.append(
            "Claude Code hook config contains gateguard-fact-force on code-write tools; scope or remove it because it can block harness design, evidence, and handoff artifact writes."
        )
    elif is_claude and not claude_stop_hook_present(data):
        blocked.append("Claude Code hook config must include a Stop hook that calls harness_stop_guard.py.")
    elif is_claude and not current_guard_script_present(stop_entries, "harness_stop_guard.py"):
        blocked.append(
            "Claude Code Stop hook must call the installed harness_stop_guard.py at "
            + str(SCRIPT_DIR / "harness_stop_guard.py")
            + "; phase_guard.py is not a Stop guard."
        )
    elif repo and is_claude and not target_repo_present(stop_entries, repo):
        blocked.append("Claude Code Stop hook must target this repository: " + str(repo.resolve()))
    elif is_claude and not strict_stop_guard_present(stop_entries):
        blocked.append("Claude Code Stop hook must pass --strict so every non-terminal lifecycle blocks finalization.")
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
    stop = hooks.setdefault("Stop", [])
    incoming = hook.get("hooks", {}).get("PreToolUse", [])
    incoming_stop = hook.get("hooks", {}).get("Stop", [])
    pre_tool[:] = [item for item in pre_tool if not phase_guard_command_present(item)]
    stop[:] = [item for item in stop if not stop_guard_command_present(item)]
    existing_serialized = {json.dumps(item, sort_keys=True) for item in pre_tool if isinstance(item, dict)}
    for item in incoming:
        serialized = json.dumps(item, sort_keys=True)
        if serialized not in existing_serialized:
            pre_tool.append(item)
            existing_serialized.add(serialized)
    existing_stop_serialized = {json.dumps(item, sort_keys=True) for item in stop if isinstance(item, dict)}
    for item in incoming_stop:
        serialized = json.dumps(item, sort_keys=True)
        if serialized not in existing_stop_serialized:
            stop.append(item)
            existing_stop_serialized.add(serialized)
    return merged


def install(repo: Path, runtime: str, target: Path | None = None, dry_run: bool = False) -> dict:
    repo = repo.resolve()
    target_path = repo_path(repo, target or DEFAULT_TARGETS[runtime])
    if runtime in TEXT_RUNTIMES:
        output = render_runtime_text(template_text(runtime), repo)
    else:
        hook = render_runtime_paths(template(runtime), repo)
        output = merge_claude(load_json(target_path), hook) if runtime == "claude" else hook
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
    if runtime in TEXT_RUNTIMES:
        atomic_write_text(target_path, output)
    else:
        atomic_write_text(target_path, json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    validation = validate_config(target_path, repo)
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
        result = validate_config(target, args.repo) if args.check else install(args.repo, args.runtime, args.target, args.dry_run)
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
