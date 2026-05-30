#!/usr/bin/env python3
"""Pre-action guard that blocks code writes outside the implementation phase."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


WRITE_TOOLS = {
    "write",
    "edit",
    "multiedit",
    "notebookedit",
    "applypatch",
    "shellcommand",
    "shell",
    "bash",
    "powershell",
}
READ_TOOLS = {"read", "grep", "glob", "ls", "list", "search"}
CODE_SUFFIXES = {
    ".java",
    ".kt",
    ".groovy",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".sql",
    ".xml",
    ".yml",
    ".yaml",
    ".properties",
    ".gradle",
}
CODE_FILENAMES = {"pom.xml", "build.gradle", "settings.gradle", "Dockerfile"}
ARTIFACT_PREFIXES = ("docs/agent-runs/",)
DOC_PREFIXES = ("docs/design/", "docs/requirements/", "docs/review-profiles/", ".e2e/")
CONTROL_FILENAMES = {".phase-lock", "run-state.json", "artifact-registry.json", "agent-schedule.json"}
CLAIMED_OWNER_STATUSES = {"claimed", "in-progress", "in_progress", "completed"}
TEST_CODE_MARKERS = ("/src/test/", "/test/", "/tests/")
DEFAULT_ALLOWED_RUNTIME_LIFECYCLES = {"IMPLEMENTED"}
DEFAULT_ALLOWED_TEST_LIFECYCLES = {"PLANNED", "RED_READY", "IMPLEMENTED"}
PATCH_FILE_RE = re.compile(
    r"^\s*(?:\*\*\* (?:Add|Update|Delete) File:|\*\*\* Move to:|---|\+\+\+)\s+(?P<path>.+?)\s*$",
    re.MULTILINE,
)
SHELL_WRITE_RE = re.compile(
    r"(?:Set-Content|Add-Content|Out-File|New-Item)\b[^\r\n]*?(?:-Path|-LiteralPath|-FilePath|-Name)?\s*['\"]?(?P<cmdlet>[A-Za-z0-9_./\\:-]+\.[A-Za-z0-9]+)['\"]?"
    r"|(?:^|\s)(?:>|>>)\s*['\"]?(?P<redir>[A-Za-z0-9_./\\:-]+\.[A-Za-z0-9]+)['\"]?",
    re.IGNORECASE | re.MULTILINE,
)


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def normalize_tool(value: str) -> str:
    return value.strip().lower().replace("_", "").replace("-", "")


def posix_relative(repo: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/").lstrip("/")


def result_path(repo: Path, path: Path) -> str:
    return posix_relative(repo, path if path.is_absolute() else repo / path)


def result_paths(repo: Path, paths: list[Path]) -> list[str]:
    return [result_path(repo, path) for path in paths]


def is_code_path(repo: Path, path: Path) -> bool:
    relative = posix_relative(repo, path)
    if relative.startswith(ARTIFACT_PREFIXES):
        return False
    if relative.startswith(DOC_PREFIXES):
        return False
    name = path.name
    return name in CODE_FILENAMES or path.suffix in CODE_SUFFIXES


def is_harness_control_path(repo: Path, path: Path) -> bool:
    relative = posix_relative(repo, path if path.is_absolute() else repo / path)
    if not relative.startswith(ARTIFACT_PREFIXES):
        return False
    return Path(relative).name in CONTROL_FILENAMES


def is_test_code_path(repo: Path, path: Path) -> bool:
    relative = "/" + posix_relative(repo, path).lower()
    return any(marker in relative for marker in TEST_CODE_MARKERS) or path.name.lower().startswith("test_")


def is_repo_wide_path(repo: Path, path: Path) -> bool:
    relative = posix_relative(repo, path if path.is_absolute() else repo / path).strip("/")
    return relative in {"", ".", "*"}


def service_for_code_path(repo: Path, path: Path, services: list[str]) -> str:
    relative = posix_relative(repo, path if path.is_absolute() else repo / path)
    matches = [
        service
        for service in services
        if relative == service.strip("/").replace("\\", "/")
        or relative.startswith(service.strip("/").replace("\\", "/") + "/")
    ]
    if not matches:
        return ""
    return sorted(matches, key=len, reverse=True)[0]


def discover_lock(repo: Path, explicit: Path | None = None, run_dir: Path | None = None) -> Path | None:
    if explicit:
        return explicit if explicit.is_absolute() else repo / explicit
    if run_dir:
        base = run_dir if run_dir.is_absolute() else repo / run_dir
        return base / ".phase-lock"
    runs = repo / "docs" / "agent-runs"
    if not runs.exists():
        return None
    matches = sorted(runs.glob("*/.phase-lock"), key=lambda path: path.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def run_state_path_for_lock(repo: Path, lock: Path) -> Path:
    return lock.parent / "run-state.json"


def lock_state_pair(repo: Path, lock: Path) -> tuple[dict, dict, list[str]]:
    blocked: list[str] = []
    lock_data = load_json(lock)
    if lock_data.get("schema") != "e2e-dev-harness.phase-lock.v1":
        blocked.append("Phase lock is missing or invalid; rerun run_state.py or e2e_dev_harness.py gate.")
    state_path = run_state_path_for_lock(repo, lock)
    state_data = load_json(state_path)
    if state_data.get("schema") != "e2e-dev-harness.run-state.v1":
        blocked.append(f"Run state beside phase lock is missing or invalid: {state_path}")
    if not blocked:
        lock_run = str(lock_data.get("run_id") or "")
        state_run = str(state_data.get("run_id") or "")
        if lock_run and state_run and lock_run != state_run:
            blocked.append(f"Phase lock run_id does not match run-state: {lock_run} != {state_run}")
        lock_lifecycle = str(lock_data.get("lifecycle") or "")
        state_lifecycle = str(state_data.get("lifecycle") or "")
        if lock_lifecycle != state_lifecycle:
            blocked.append(
                "Phase lock lifecycle does not match run-state lifecycle: "
                + f"{lock_lifecycle or '<missing>'} != {state_lifecycle or '<missing>'}. "
                + "Rerun the last successful harness transition before writing code."
            )
    return lock_data, state_data, blocked


def shared_scope_for_code_path(repo: Path, path: Path, shared_edit_scopes: list[str]) -> str:
    relative = posix_relative(repo, path if path.is_absolute() else repo / path)
    for scope in sorted([scope.strip("/").replace("\\", "/") for scope in shared_edit_scopes], key=len, reverse=True):
        if relative == scope or relative.startswith(scope + "/"):
            return scope
    return ""


def claimed_owners(owners: dict) -> list[str]:
    claimed: list[str] = []
    for service, owner in owners.items():
        if not isinstance(owner, dict):
            continue
        status = str(owner.get("status", "")).lower()
        agent = str(owner.get("agent", "")).strip()
        if agent and status in CLAIMED_OWNER_STATUSES:
            claimed.append(str(service))
    return claimed


def parse_hook_input(text: str) -> tuple[str, list[str]]:
    if not text.strip():
        return "", []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return "", []
    tool = str(data.get("tool_name") or data.get("tool") or "")
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else data
    paths: list[str] = []
    for key in ("file_path", "path", "target", "notebook_path"):
        value = tool_input.get(key) if isinstance(tool_input, dict) else None
        if value:
            paths.append(str(value))
    patch_text = ""
    command_text = ""
    if isinstance(tool_input, dict):
        patch_text = str(tool_input.get("patch") or tool_input.get("input") or tool_input.get("text") or "")
        command_text = str(tool_input.get("command") or tool_input.get("cmd") or tool_input.get("script") or "")
        if not command_text and isinstance(tool_input.get("tool_input"), dict):
            nested = tool_input.get("tool_input")
            command_text = str(nested.get("command") or nested.get("cmd") or nested.get("script") or "")
    if normalize_tool(tool) == "applypatch" or "*** Begin Patch" in patch_text:
        paths.extend(paths_from_patch(patch_text))
    if normalize_tool(tool) in {"shellcommand", "shell", "bash", "powershell"}:
        paths.extend(paths_from_shell_command(command_text))
    return tool, paths


def paths_from_patch(text: str) -> list[str]:
    paths: list[str] = []
    for match in PATCH_FILE_RE.finditer(text or ""):
        value = match.group("path").strip()
        if value.startswith(("a/", "b/")):
            value = value[2:]
        if value and value != "/dev/null":
            paths.append(value)
    return paths


def paths_from_shell_command(command: str) -> list[str]:
    paths: list[str] = []
    for match in SHELL_WRITE_RE.finditer(command or ""):
        value = match.group("cmdlet") or match.group("redir") or ""
        if value:
            paths.append(value)
    return paths


def validate_action(
    repo: Path,
    tool: str,
    paths: list[Path],
    lock_path: Path | None = None,
    run_dir: Path | None = None,
    require_active_run_for_read: bool = False,
) -> dict:
    repo = repo.resolve()
    normalized = normalize_tool(tool)
    protected_paths = [path for path in paths if is_harness_control_path(repo, path if path.is_absolute() else repo / path)]
    if normalized in WRITE_TOOLS and protected_paths:
        return {
            "ready": False,
            "blocked_reasons": [
                "Harness control file write blocked: use e2e_dev_harness.py, run_state.py, service-design, gate, or agent-task commands instead of direct file edits."
            ],
            "warnings": [],
            "protected_paths": result_paths(repo, protected_paths),
        }
    lock = discover_lock(repo, lock_path, run_dir)
    if require_active_run_for_read and normalized in READ_TOOLS:
        read_targets = list(paths)
        repo_wide = not read_targets or any(is_repo_wide_path(repo, path) for path in read_targets)
        read_code_paths = [path for path in read_targets if is_code_path(repo, path if path.is_absolute() else repo / path)]
        if not lock or not lock.exists():
            if repo_wide or read_code_paths:
                return {
                    "ready": False,
                    "blocked_reasons": [
                        "Code exploration blocked: start an e2e-dev-harness run before reading/searching project code."
                    ],
                    "warnings": [],
                    "action": "run e2e_dev_harness.py start . --feature <feature> --request <request>",
                    "read_paths": result_paths(repo, read_targets),
                }
        else:
            _, _, state_blockers = lock_state_pair(repo, lock)
            if state_blockers:
                return {
                    "ready": False,
                    "blocked_reasons": state_blockers,
                    "warnings": [],
                    "phase_lock": str(lock),
                    "run_state": str(run_state_path_for_lock(repo, lock)),
                    "read_paths": result_paths(repo, read_targets),
                }
    code_paths = [path for path in paths if is_code_path(repo, path if path.is_absolute() else repo / path)]
    test_code_paths = [path for path in code_paths if is_test_code_path(repo, path if path.is_absolute() else repo / path)]
    runtime_code_paths = [path for path in code_paths if path not in test_code_paths]
    if normalized not in WRITE_TOOLS or not code_paths:
        return {"ready": True, "blocked_reasons": [], "warnings": [], "code_paths": result_paths(repo, code_paths)}
    if not lock or not lock.exists():
        return {
            "ready": False,
            "blocked_reasons": ["Code write blocked: phase lock not found for active agent run."],
            "warnings": [],
            "code_paths": result_paths(repo, code_paths),
        }
    lock_data, state_data, state_blockers = lock_state_pair(repo, lock)
    if state_blockers:
        return {
            "ready": False,
            "blocked_reasons": state_blockers,
            "warnings": [],
            "phase_lock": str(lock),
            "run_state": str(run_state_path_for_lock(repo, lock)),
            "code_paths": result_paths(repo, code_paths),
            "test_code_paths": result_paths(repo, test_code_paths),
            "runtime_code_paths": result_paths(repo, runtime_code_paths),
        }
    data = state_data
    lifecycle = str(data.get("lifecycle", ""))
    allowed_runtime = set(lock_data.get("allowed_code_write_lifecycles") or DEFAULT_ALLOWED_RUNTIME_LIFECYCLES)
    allowed_test = set(lock_data.get("allowed_test_write_lifecycles") or DEFAULT_ALLOWED_TEST_LIFECYCLES)
    if runtime_code_paths and lifecycle not in allowed_runtime:
        return {
            "ready": False,
            "blocked_reasons": [
                f"Code write blocked: lifecycle {lifecycle or '<missing>'} is not in allowed phases: "
                + ", ".join(sorted(allowed_runtime))
            ],
            "warnings": [],
            "phase_lock": str(lock),
            "run_state": str(run_state_path_for_lock(repo, lock)),
            "lifecycle": lifecycle,
            "code_paths": result_paths(repo, code_paths),
            "test_code_paths": result_paths(repo, test_code_paths),
            "runtime_code_paths": result_paths(repo, runtime_code_paths),
        }
    if test_code_paths and not runtime_code_paths and lifecycle not in allowed_test:
        return {
            "ready": False,
            "blocked_reasons": [
                f"Test write blocked: lifecycle {lifecycle or '<missing>'} is not in allowed test phases: "
                + ", ".join(sorted(allowed_test))
            ],
            "warnings": [],
            "phase_lock": str(lock),
            "run_state": str(run_state_path_for_lock(repo, lock)),
            "lifecycle": lifecycle,
            "code_paths": result_paths(repo, code_paths),
            "test_code_paths": result_paths(repo, test_code_paths),
            "runtime_code_paths": result_paths(repo, runtime_code_paths),
        }
    selected_mode = str(data.get("selected_mode", ""))
    services = [str(service).replace("\\", "/").strip("/") for service in data.get("services", []) or []]
    if selected_mode == "multi" and services and runtime_code_paths:
        touched_services = {
            service_for_code_path(repo, path, services)
            for path in runtime_code_paths
        }
        touched_services.discard("")
        shared_edit_scopes = [str(scope) for scope in data.get("shared_edit_scopes", []) or []]
        unscoped_runtime = [
            path
            for path in runtime_code_paths
            if not service_for_code_path(repo, path, services)
            and not shared_scope_for_code_path(repo, path, shared_edit_scopes)
        ]
        if unscoped_runtime:
            return {
                "ready": False,
                "blocked_reasons": [
                    "Multi-service code write blocked: runtime code path is outside claimed services and shared edit scopes."
                ],
                "warnings": [],
                "phase_lock": str(lock),
                "run_state": str(run_state_path_for_lock(repo, lock)),
                "lifecycle": lifecycle,
                "code_paths": result_paths(repo, code_paths),
                "runtime_code_paths": result_paths(repo, runtime_code_paths),
                "unscoped_runtime_paths": result_paths(repo, unscoped_runtime),
            }
        if len(touched_services) > 1:
            return {
                "ready": False,
                "blocked_reasons": [
                    "Multi-service code write blocked: one claimed code-developer task may edit only one service/module."
                ],
                "warnings": [],
                "phase_lock": str(lock),
                "run_state": str(run_state_path_for_lock(repo, lock)),
                "lifecycle": lifecycle,
                "code_paths": result_paths(repo, code_paths),
                "touched_services": sorted(touched_services),
            }
        owners = data.get("owners") if isinstance(data.get("owners"), dict) else {}
        if not touched_services and runtime_code_paths and not claimed_owners(owners):
            return {
                "ready": False,
                "blocked_reasons": [
                    "Multi-service code write blocked: shared edit scope has no claimed code-developer task."
                ],
                "warnings": [],
                "phase_lock": str(lock),
                "run_state": str(run_state_path_for_lock(repo, lock)),
                "lifecycle": lifecycle,
                "code_paths": result_paths(repo, code_paths),
            }
        for service in sorted(touched_services):
            owner = owners.get(service) if isinstance(owners.get(service), dict) else {}
            status = str(owner.get("status", "")).lower()
            agent = str(owner.get("agent", "")).strip()
            if not agent or status not in CLAIMED_OWNER_STATUSES:
                return {
                    "ready": False,
                    "blocked_reasons": [
                        "Multi-service code write blocked: service "
                        + service
                        + " has no claimed code-developer task in run-state owners."
                    ],
                    "warnings": [],
                    "phase_lock": str(lock),
                    "run_state": str(run_state_path_for_lock(repo, lock)),
                    "lifecycle": lifecycle,
                    "code_paths": result_paths(repo, code_paths),
                    "touched_services": sorted(touched_services),
                }
    return {
        "ready": True,
        "blocked_reasons": [],
        "warnings": [],
        "phase_lock": str(lock),
        "run_state": str(run_state_path_for_lock(repo, lock)),
        "lifecycle": lifecycle,
        "code_paths": result_paths(repo, code_paths),
        "test_code_paths": result_paths(repo, test_code_paths),
        "runtime_code_paths": result_paths(repo, runtime_code_paths),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--tool", default="")
    parser.add_argument("--path", action="append", type=Path)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--require-active-run-for-read", action="store_true")
    parser.add_argument("--hook-input", help="JSON hook input, or '-' for stdin.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    tool = args.tool
    paths = list(args.path or [])
    if args.hook_input:
        hook_text = sys.stdin.read() if args.hook_input == "-" else args.hook_input
        hook_tool, hook_paths = parse_hook_input(hook_text)
        tool = tool or hook_tool
        paths.extend(Path(path) for path in hook_paths)
    result = validate_action(args.repo, tool, paths, args.lock, args.run_dir, args.require_active_run_for_read)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Phase guard: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
