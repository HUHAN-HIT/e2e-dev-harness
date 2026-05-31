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
    "create",
    "edit",
    "update",
    "multiedit",
    "notebookedit",
    "applypatch",
    "replace",
    "strreplace",
    "strreplaceeditor",
    "strreplaceedit",
    "str_replace",
    "str_replace_editor",
    "shellcommand",
    "shell",
    "bash",
    "powershell",
}
SHELL_TOOLS = {"shellcommand", "shell", "bash", "powershell"}
READ_TOOLS = {"read", "grep", "glob", "ls", "list", "search"}
TASK_TOOLS = {"task", "taskcreate", "agent", "subagent"}
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
HOOK_CONFIG_PATHS = {
    ".claude/settings.json",
    ".codex/hooks/e2e-dev-harness-pre-action.json",
    ".gemini/hooks/e2e-dev-harness-pre-tool-use.json",
    ".opencode/plugins/e2e-dev-harness.js",
}
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
PYTHON_PATH_LITERAL_RE = re.compile(
    r"(?:open|Path)\s*\(\s*['\"](?P<path>[A-Za-z0-9_./\\:-]+\.[A-Za-z0-9.-]+)['\"]",
    re.IGNORECASE,
)
CONTROL_PATH_LITERAL_RE = re.compile(
    r"(?P<path>(?:[A-Za-z]:)?[A-Za-z0-9_./\\:-]*docs[\\/]+agent-runs[\\/]+[A-Za-z0-9_.-]+[\\/]+(?:\.phase-lock|run-state\.json|artifact-registry\.json|agent-schedule\.json))",
    re.IGNORECASE,
)
SHELL_MUTATION_RE = re.compile(
    r"(?:\bpython(?:3)?(?:\.exe)?\s+(?:-[c]|-)\b|\bnode(?:\.exe)?\s+(?:-[e]|-)\b|\bpowershell(?:\.exe)?\b.*\b-Command\b|"
    r"\bwith\s+open\s*\(|\bopen\s*\(|\.write_text\s*\(|\.write_bytes\s*\(|\bjson\.dump\s*\(|\byaml\.dump\s*\(|"
    r"\bshutil\.(?:copy|copyfile|move)\s*\(|\bos\.(?:remove|unlink|rename|replace)\s*\(|"
    r"\b(?:Set-Content|Add-Content|Out-File|New-Item|Remove-Item|Move-Item|Copy-Item)\b|(?:^|\s)(?:>|>>)\s*)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
CONTROL_FILENAME_RE = re.compile(r"(?:\.phase-lock|run-state\.json|artifact-registry\.json|agent-schedule\.json)", re.IGNORECASE)
HOOK_PATH_KEYS = {
    "file_path",
    "filepath",
    "filePath",
    "path",
    "paths",
    "target",
    "targets",
    "notebook_path",
    "notebookPath",
    "absolute_path",
    "absolutePath",
    "glob",
    "pattern",
}
TASK_TEXT_KEYS = {"description", "prompt", "task", "subagent_type", "title", "todos", "content"}
CODE_TASK_RE = re.compile(
    r"(?:\b(?:implement|code|coding|write\s+code|edit\s+code|modify\s+code|create\s+(?:class|entity|service|controller|mapper))\b|"
    r"开发|实现|编码|写代码|修改代码|创建(?:实体|服务|控制器|类))",
    re.IGNORECASE,
)

import run_state  # noqa: E402
import session_checkpoint  # noqa: E402


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


def resolve_for_repo(repo: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo / path


def is_inside_repo(repo: Path, path: Path) -> bool:
    resolved = resolve_for_repo(repo, path)
    if not resolved.is_absolute():
        return True
    try:
        resolved.resolve().relative_to(repo.resolve())
        return True
    except ValueError:
        return False


def result_path(repo: Path, path: Path) -> str:
    return posix_relative(repo, resolve_for_repo(repo, path))


def result_paths(repo: Path, paths: list[Path]) -> list[str]:
    return [result_path(repo, path) for path in paths]


def is_code_path(repo: Path, path: Path) -> bool:
    resolved = resolve_for_repo(repo, path)
    if not is_inside_repo(repo, resolved):
        return False
    relative = posix_relative(repo, resolved)
    if relative.startswith(ARTIFACT_PREFIXES):
        return False
    if relative.startswith(DOC_PREFIXES):
        return False
    name = resolved.name
    return name in CODE_FILENAMES or resolved.suffix in CODE_SUFFIXES


def is_code_like_path(path: Path) -> bool:
    return path.name in CODE_FILENAMES or path.suffix in CODE_SUFFIXES


def is_harness_control_path(repo: Path, path: Path) -> bool:
    relative = posix_relative(repo, path if path.is_absolute() else repo / path)
    if not relative.startswith(ARTIFACT_PREFIXES):
        return False
    return Path(relative).name in CONTROL_FILENAMES


def is_hook_config_path(repo: Path, path: Path) -> bool:
    relative = posix_relative(repo, resolve_for_repo(repo, path))
    return relative in HOOK_CONFIG_PATHS


def state_path_display(repo: Path, lock: Path | None) -> str:
    if not lock:
        return "docs/agent-runs/<run>/run-state.json"
    return posix_relative(repo, run_state_path_for_lock(repo, lock))


def guidance_for_lifecycle(repo: Path, lock: Path | None, lifecycle: str = "") -> dict:
    state_path = state_path_display(repo, lock)
    base = {
        "not_deadlock": True,
        "next_valid_command": f"e2e_dev_harness.py next . --state {state_path}",
        "forbidden_actions": [
            "edit run-state.json directly",
            "edit .phase-lock directly",
            "edit artifact-registry.json directly",
            "disable or edit harness hooks",
            "ask the user to bypass hooks instead of following the next harness phase",
        ],
    }
    actions = {
        "": {
            "allowed_actions": ["run e2e_dev_harness.py start . --feature <feature> --request <request>"],
            "phase_guidance": "No active phase lock was found. Start a controlled harness run before code exploration or implementation.",
        },
        "CREATED": {
            "allowed_actions": [
                "edit docs/design/<feature>.md",
                "run e2e_dev_harness.py clarify . --design-doc <design> --run-state " + state_path,
                "run e2e_dev_harness.py next . --state " + state_path,
            ],
            "phase_guidance": "Current lifecycle is CREATED. Fill the design document and pass clarify before planning or coding.",
        },
        "CLARIFIED": {
            "allowed_actions": [
                "run e2e_dev_harness.py plan . --design-doc <design> --run-state " + state_path,
                "create R1 design review artifacts",
                "run e2e_dev_harness.py next . --state " + state_path,
            ],
            "phase_guidance": "Current lifecycle is CLARIFIED. Plan and review design before TDD or implementation.",
        },
        "SERVICE_DESIGN_REQUIRED": {
            "allowed_actions": [
                "fill docs/agent-runs/<run>/service-designs/<service>.md",
                "run e2e_dev_harness.py service-design . --run-state " + state_path,
                "run e2e_dev_harness.py next . --state " + state_path,
            ],
            "phase_guidance": "Current lifecycle requires service design slices before service code agents can proceed.",
        },
        "PLANNED": {
            "allowed_actions": [
                "write red tests only",
                "capture red-test evidence",
                "create R2 test review artifacts",
                "run e2e_dev_harness.py gate . --phase implementation --run-state " + state_path,
            ],
            "phase_guidance": "Current lifecycle is PLANNED. Production code is still locked; complete TDD red and R2 before implementation gate.",
        },
        "RED_READY": {
            "allowed_actions": [
                "run e2e_dev_harness.py gate . --phase implementation --run-state " + state_path,
                "run e2e_dev_harness.py next . --state " + state_path,
            ],
            "phase_guidance": "Current lifecycle is RED_READY. Open production-code writes only through the implementation gate.",
        },
        "IMPLEMENTED": {
            "allowed_actions": [
                "continue TDD green/refactor within declared scope",
                "run e2e_dev_harness.py ac-progress ...",
                "create R3 review artifacts after all assigned ACs are covered",
            ],
            "phase_guidance": "Current lifecycle is IMPLEMENTED. Continue assigned ACs to completion; do not stop after compile only.",
        },
    }
    selected = actions.get(lifecycle, actions[""])
    return {**base, **selected, "lifecycle": lifecycle or "<missing>"}


def guidance_from_lock(repo: Path, lock: Path | None) -> dict:
    if not lock or not lock.exists():
        return guidance_for_lifecycle(repo, None, "")
    lock_data = load_json(lock)
    lifecycle = str(lock_data.get("lifecycle") or "")
    guidance = guidance_for_lifecycle(repo, lock, lifecycle)
    guidance["phase_lock"] = str(lock)
    guidance["run_state"] = str(run_state_path_for_lock(repo, lock))
    return guidance


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
        blocked.extend(run_state.validate_lifecycle_provenance(repo, state_path, state_data))
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
    if isinstance(tool_input, dict):
        paths.extend(collect_hook_paths(tool_input))
    patch_text = ""
    if isinstance(tool_input, dict):
        patch_text = str(tool_input.get("patch") or tool_input.get("input") or tool_input.get("text") or "")
    if normalize_tool(tool) == "applypatch" or "*** Begin Patch" in patch_text:
        paths.extend(paths_from_patch(patch_text))
    command_text = extract_hook_command_text(text)
    if normalize_tool(tool) in {"shellcommand", "shell", "bash", "powershell"}:
        paths.extend(paths_from_shell_command(command_text))
    return tool, paths


def collect_hook_paths(value) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in HOOK_PATH_KEYS:
                paths.extend(path_values(item))
            elif isinstance(item, (dict, list)):
                paths.extend(collect_hook_paths(item))
    elif isinstance(value, list):
        for item in value:
            paths.extend(collect_hook_paths(item))
    seen: set[str] = set()
    unique: list[str] = []
    for path in paths:
        if path not in seen:
            unique.append(path)
            seen.add(path)
    return unique


def path_values(value) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Path):
        return [str(value)]
    if isinstance(value, list):
        paths: list[str] = []
        for item in value:
            paths.extend(path_values(item))
        return paths
    if isinstance(value, dict):
        for nested_key in ("path", "file_path", "filePath", "absolute_path", "absolutePath"):
            nested = value.get(nested_key)
            if nested:
                return path_values(nested)
    return []


def extract_hook_command_text(text: str) -> str:
    if not text.strip():
        return ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return ""
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else data
    if not isinstance(tool_input, dict):
        return ""
    command_text = str(tool_input.get("command") or tool_input.get("cmd") or tool_input.get("script") or "")
    if not command_text and isinstance(tool_input.get("tool_input"), dict):
        nested = tool_input.get("tool_input")
        command_text = str(nested.get("command") or nested.get("cmd") or nested.get("script") or "")
    return command_text


def extract_task_text(text: str) -> str:
    if not text.strip():
        return ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return ""
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else data
    return " ".join(collect_task_text(tool_input))


def collect_task_text(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        text: list[str] = []
        for item in value:
            text.extend(collect_task_text(item))
        return text
    if isinstance(value, dict):
        text: list[str] = []
        for key, item in value.items():
            if key in TASK_TEXT_KEYS:
                text.extend(collect_task_text(item))
            elif isinstance(item, (dict, list)):
                text.extend(collect_task_text(item))
        return text
    return []


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
    for pattern in (PYTHON_PATH_LITERAL_RE, CONTROL_PATH_LITERAL_RE):
        for match in pattern.finditer(command or ""):
            value = match.group("path")
            if value and value not in paths:
                paths.append(value)
    return paths


def shell_mutates_files(command: str) -> bool:
    return bool(SHELL_MUTATION_RE.search(command or ""))


def shell_mentions_harness_control(command: str) -> bool:
    return bool(CONTROL_FILENAME_RE.search(command or ""))


def validate_action(
    repo: Path,
    tool: str,
    paths: list[Path],
    lock_path: Path | None = None,
    run_dir: Path | None = None,
    require_active_run_for_read: bool = False,
    command_text: str = "",
    task_text: str = "",
    require_session_checkpoint: bool = False,
    checkpoint_max_age_minutes: int = 30,
) -> dict:
    repo = repo.resolve()
    normalized = normalize_tool(tool)
    shell_mutation = normalized in SHELL_TOOLS and shell_mutates_files(command_text)
    warnings: list[str] = []
    outside_repo_paths = [path for path in paths if path.is_absolute() and not is_inside_repo(repo, path)]
    outside_repo_code_paths = [path for path in outside_repo_paths if is_code_like_path(path)]
    if outside_repo_paths and normalized in READ_TOOLS:
        warnings.append(
            "Read target is outside the configured harness repository; phase_guard will not treat it as project code. "
            + "If this is unexpected, reinstall hooks with the correct target repository."
        )
    if outside_repo_code_paths and normalized in WRITE_TOOLS:
        return {
            "ready": False,
            "blocked_reasons": [
                "Code write blocked: tool target is outside the configured harness repository. "
                + "Reinstall hooks for the active project or run the correct project's harness."
            ],
            "warnings": warnings,
            "repo": str(repo),
            "outside_repo_paths": [str(path) for path in outside_repo_code_paths],
        }
    if shell_mutation and shell_mentions_harness_control(command_text):
        return {
            "ready": False,
            "blocked_reasons": [
                "Harness control file write blocked: shell command appears to mutate phase/run control files; use e2e_dev_harness.py gate, service-design, or agent-task instead."
            ],
            "warnings": warnings,
        }
    protected_paths = [path for path in paths if is_harness_control_path(repo, resolve_for_repo(repo, path))]
    if normalized in WRITE_TOOLS and protected_paths and (normalized not in SHELL_TOOLS or shell_mutation):
        return {
            "ready": False,
            "blocked_reasons": [
                "Harness control file write blocked: use e2e_dev_harness.py, run_state.py, service-design, gate, or agent-task commands instead of direct file edits."
            ],
            "warnings": warnings,
            "protected_paths": result_paths(repo, protected_paths),
        }
    lock = discover_lock(repo, lock_path, run_dir)
    if normalized in TASK_TOOLS:
        text = task_text.strip()
        code_task = bool(CODE_TASK_RE.search(text))
        if code_task:
            if not lock or not lock.exists():
                return {
                    "ready": False,
                    "blocked_reasons": [
                        "Code-agent dispatch blocked: start an e2e-dev-harness run and pass clarify/plan/TDD gates before assigning implementation work."
                    ],
                    "warnings": warnings,
                    "action": "run e2e_dev_harness.py start . --feature <feature> --request <request>",
                }
            lock_data, state_data, state_blockers = lock_state_pair(repo, lock)
            if state_blockers:
                return {
                    "ready": False,
                    "blocked_reasons": state_blockers,
                    "warnings": warnings,
                    "phase_lock": str(lock),
                    "run_state": str(run_state_path_for_lock(repo, lock)),
                }
            lifecycle = str(state_data.get("lifecycle", ""))
            allowed_runtime = set(lock_data.get("allowed_code_write_lifecycles") or DEFAULT_ALLOWED_RUNTIME_LIFECYCLES)
            if lifecycle not in allowed_runtime:
                return {
                    "ready": False,
                    "blocked_reasons": [
                        f"Code-agent dispatch blocked: lifecycle {lifecycle or '<missing>'} is not in allowed implementation phases: "
                        + ", ".join(sorted(allowed_runtime))
                        + ". Complete clarify, plan, TDD red, R2 review, and implementation gate before dispatching code developers."
                    ],
                    "warnings": warnings,
                    "phase_lock": str(lock),
                    "run_state": str(run_state_path_for_lock(repo, lock)),
                    "lifecycle": lifecycle,
                }
        return {"ready": True, "blocked_reasons": [], "warnings": warnings}
    if require_active_run_for_read and normalized in READ_TOOLS:
        read_targets = list(paths)
        repo_wide = not read_targets or any(is_repo_wide_path(repo, path) for path in read_targets)
        read_code_paths = [path for path in read_targets if is_code_path(repo, resolve_for_repo(repo, path))]
        if not lock or not lock.exists():
            if repo_wide or read_code_paths:
                return {
                    "ready": False,
                    "blocked_reasons": [
                        "Code exploration blocked: start an e2e-dev-harness run before reading/searching project code."
                    ],
                    "warnings": warnings,
                    "action": "run e2e_dev_harness.py start . --feature <feature> --request <request>",
                    "read_paths": result_paths(repo, read_targets),
                }
        else:
            _, _, state_blockers = lock_state_pair(repo, lock)
            if state_blockers:
                return {
                    "ready": False,
                    "blocked_reasons": state_blockers,
                    "warnings": warnings,
                    "phase_lock": str(lock),
                    "run_state": str(run_state_path_for_lock(repo, lock)),
                    "read_paths": result_paths(repo, read_targets),
                }
    code_paths = [path for path in paths if is_code_path(repo, resolve_for_repo(repo, path))]
    test_code_paths = [path for path in code_paths if is_test_code_path(repo, resolve_for_repo(repo, path))]
    runtime_code_paths = [path for path in code_paths if path not in test_code_paths]
    if shell_mutation and not paths:
        return {
            "ready": False,
            "blocked_reasons": [
                "Shell write blocked: command appears to mutate files but no target paths were parsed; pass explicit --path/pre-code targets or use a file tool so phase scope can be enforced."
            ],
            "warnings": warnings,
        }
    if normalized not in WRITE_TOOLS and normalized not in READ_TOOLS and code_paths:
        return {
            "ready": False,
            "blocked_reasons": [
                f"Code write blocked: unrecognized tool {tool or '<missing>'} touched code paths; update phase_guard WRITE_TOOLS or use a supported file tool."
            ],
            "warnings": warnings,
            "code_paths": result_paths(repo, code_paths),
            "test_code_paths": result_paths(repo, test_code_paths),
            "runtime_code_paths": result_paths(repo, runtime_code_paths),
        }
    if normalized not in WRITE_TOOLS or not code_paths:
        return {"ready": True, "blocked_reasons": [], "warnings": warnings, "code_paths": result_paths(repo, code_paths)}
    if not lock or not lock.exists():
        return {
            "ready": False,
            "blocked_reasons": ["Code write blocked: phase lock not found for active agent run."],
            "warnings": warnings,
            "code_paths": result_paths(repo, code_paths),
        }
    lock_data, state_data, state_blockers = lock_state_pair(repo, lock)
    if state_blockers:
        return {
            "ready": False,
            "blocked_reasons": state_blockers,
            "warnings": warnings,
            "phase_lock": str(lock),
            "run_state": str(run_state_path_for_lock(repo, lock)),
            "code_paths": result_paths(repo, code_paths),
            "test_code_paths": result_paths(repo, test_code_paths),
            "runtime_code_paths": result_paths(repo, runtime_code_paths),
        }
    data = state_data
    if require_session_checkpoint:
        checkpoint_result = session_checkpoint.validate(
            repo,
            run_state_path_for_lock(repo, lock),
            checkpoint_max_age_minutes,
        )
        if not checkpoint_result["ready"]:
            return {
                "ready": False,
                "blocked_reasons": [
                    "Session resume checkpoint required before code write: " + reason
                    for reason in checkpoint_result["blocked_reasons"]
                ],
                "warnings": warnings + checkpoint_result["warnings"],
                "phase_lock": str(lock),
                "run_state": str(run_state_path_for_lock(repo, lock)),
                "checkpoint": checkpoint_result["checkpoint"],
                "action": "Run e2e_dev_harness.py next --state docs/agent-runs/<run>/run-state.json before continuing.",
                "code_paths": result_paths(repo, code_paths),
                "test_code_paths": result_paths(repo, test_code_paths),
                "runtime_code_paths": result_paths(repo, runtime_code_paths),
            }
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
            "warnings": warnings,
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
            "warnings": warnings,
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
                "warnings": warnings,
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
                "warnings": warnings,
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
                "warnings": warnings,
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
                    "warnings": warnings,
                    "phase_lock": str(lock),
                    "run_state": str(run_state_path_for_lock(repo, lock)),
                    "lifecycle": lifecycle,
                    "code_paths": result_paths(repo, code_paths),
                    "touched_services": sorted(touched_services),
                }
    return {
        "ready": True,
        "blocked_reasons": [],
        "warnings": warnings,
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
    parser.add_argument("--require-session-checkpoint", action="store_true")
    parser.add_argument("--checkpoint-max-age-minutes", type=int, default=30)
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
        command_text = extract_hook_command_text(hook_text)
        task_text = extract_task_text(hook_text)
    else:
        command_text = ""
        task_text = ""
    result = validate_action(
        args.repo,
        tool,
        paths,
        args.lock,
        args.run_dir,
        args.require_active_run_for_read,
        command_text=command_text,
        task_text=task_text,
        require_session_checkpoint=args.require_session_checkpoint,
        checkpoint_max_age_minutes=args.checkpoint_max_age_minutes,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if not result["ready"]:
            summary = "; ".join(result.get("blocked_reasons") or ["blocked"])
            print("Phase guard BLOCKED: " + summary, file=sys.stderr)
            action = result.get("action")
            if action:
                print("Next action: " + str(action), file=sys.stderr)
    else:
        print("Phase guard: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
