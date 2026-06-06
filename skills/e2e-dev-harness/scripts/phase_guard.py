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
TODO_TOOLS = {"todowrite", "todo", "updatetodo", "updatetodos", "tasklist"}
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
DISPATCH_GATED_READ_LIFECYCLES = {"CLARIFIED", "SERVICE_DESIGN_REQUIRED", "PLANNED", "IMPLEMENTED"}
TEST_CODE_MARKERS = ("/src/test/", "/test/", "/tests/")
REVIEW_DISPATCH_PHASES = {"r1-review", "r2-review", "r3-review"}
REVIEW_REPORT_NAME_RE = re.compile(r"^R[123](?:[-_].*)?\.md$", re.IGNORECASE)
ACTIVE_DISPATCH_STATUSES = {
    "awaiting_runtime_spawn",
    "waiting_dispatch",
    "worker_dispatched",
    "dispatched",
    "worker_running",
    "worker_running_unverified",
}
PENDING_DISPATCH_ACK_STATUSES = {"awaiting_runtime_spawn", "waiting_dispatch", "worker_dispatched", "dispatched"}
DEFAULT_ALLOWED_RUNTIME_LIFECYCLES = {"IMPLEMENTED"}
DEFAULT_ALLOWED_TEST_LIFECYCLES = {"PLANNED", "RED_READY", "IMPLEMENTED"}
COORDINATOR_INLINE_WRITE_WARN_CHARS = 8_000
COORDINATOR_INLINE_WRITE_BLOCK_CHARS = 24_000
COORDINATOR_INLINE_WRITE_PREFIXES = (
    "docs/design/",
    "docs/requirements/",
    "docs/superpowers/plans/",
)
COORDINATOR_INLINE_WRITE_EXCLUDED_RUN_PARTS = (
    "/reviews/",
    "/evidence/",
    "/context-packs/",
    "/dispatch/",
    "/cli-responses/",
)
PATCH_FILE_RE = re.compile(
    r"^\s*(?:\*\*\* (?:Add|Update|Delete) File:|\*\*\* Move to:|---|\+\+\+)\s+(?P<path>.+?)\s*$",
    re.MULTILINE,
)
SHELL_WRITE_RE = re.compile(
    r"(?:Set-Content|Add-Content|Out-File|New-Item)\b[^\r\n]*?(?:-Path|-LiteralPath|-FilePath|-Name)?\s*['\"]?(?P<cmdlet>[A-Za-z0-9_./\\:-]+\.[A-Za-z0-9]+)['\"]?"
    r"|(?:^|\s)(?:>|>>)\s*['\"]?(?P<redir>[A-Za-z0-9_./\\:-]+\.[A-Za-z0-9]+)['\"]?"
    r"|(?:^|\s)tee(?:\s+-a)?\s+['\"]?(?P<tee>[A-Za-z0-9_./\\:-]+\.[A-Za-z0-9]+)['\"]?",
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
    r"\b(?:Set-Content|Add-Content|Out-File|New-Item|Remove-Item|Move-Item|Copy-Item)\b|"
    r"(?:^|\s)tee(?:\s+-a)?\s+|<<\s*['\"]?[A-Za-z0-9_-]+['\"]?\s*(?:>|>>)?|(?:^|\s)(?:>|>>)\s*)",
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
WRITE_PAYLOAD_KEYS = {"content", "input", "new_string", "old_string", "patch", "replacement", "text"}
CODE_TASK_RE = re.compile(
    r"(?:\b(?:implement|code|coding|write\s+code|edit\s+code|modify\s+code|create\s+(?:class|entity|service|controller|mapper))\b|"
    r"开发|实现|编码|写代码|修改代码|创建(?:实体|服务|控制器|类))",
    re.IGNORECASE,
)
CODE_TODO_RE = re.compile(
    r"\b(?:implement|implementation|coding|write\s+code|edit\s+code|modify\s+code|production\s+code|"
    r"entity|mapper|repository|controller|dto|dao|mq|dmq|kafka)\b|"
    r"(?:开发|实现|编码|代码|生产代码|实体|常量|模型|控制器|仓储|消息队列|模块开发|修改[^。；\n]{0,12}代码)",
    re.IGNORECASE,
)
EXPLORATION_TODO_RE = re.compile(
    r"\b(?:explore|analyze|analyse|trace|impact|dependency|dependencies|affected|call\s*path|"
    r"service\s+ownership|route|topic|contract)\b|(?:探索|分析|影响|依赖|调用链|链路|范围|服务归属|接口|主题|契约)",
    re.IGNORECASE,
)
GITNEXUS_TODO_RE = re.compile(
    r"\b(?:gitnexus|knowledge\s*graph|kg_refresh|kg\s+status|context/impact|query/context/impact)\b",
    re.IGNORECASE,
)
CLARIFICATION_TODO_RE = re.compile(
    r"\b(?:clarify|clarification|design\s+doc|requirements?|restated\s+intent|open\s+questions?|acceptance\s+criteria)\b|"
    r"(?:\u6f84\u6e05|\u8bbe\u8ba1\u6587\u6863|\u9700\u6c42|\u610f\u56fe\u56de\u663e|\u5f00\u653e\u95ee\u9898|\u9a8c\u6536)",
    re.IGNORECASE,
)
PHASE_TASK_RE = re.compile(
    r"\b(?:clarify|clarification|requirements?|use[-\s]?case|design|test(?:ing)?|tdd|red\s+test|review|coverage)\b|"
    r"(?:\u6f84\u6e05|\u9700\u6c42|\u7528\u4f8b|\u8bbe\u8ba1|\u6d4b\u8bd5|\u8bc4\u5ba1|\u8986\u76d6)",
    re.IGNORECASE,
)
READ_ONLY_EXPLORATION_TASK_RE = re.compile(
    r"\b(?:read[-\s]?only|explor(?:e|ation)|inspect|map|trace|summari[sz]e)\b|"
    r"(?:\u53ea\u8bfb|\u63a2\u7d22|\u68c0\u67e5|\u8ffd\u8e2a|\u603b\u7ed3)",
    re.IGNORECASE,
)
USER_INTERACTION_TODO_RE = re.compile(
    r"\b(?:ask|confirm|confirmation|clarifying\s+questions?|obtain\s+user\s+approval|wait\s+for\s+user|user\s+answer|relay)\b|"
    r"(?:\u7528\u6237|\u786e\u8ba4|\u63d0\u95ee|\u7b49\u5f85\u56de\u7b54|\u56de\u7b54|\u6279\u51c6)",
    re.IGNORECASE,
)
CREATED_COORDINATOR_TODO_RE = re.compile(
    r"\b(?:dispatch-beat|dispatch-next|requirements-clarifier|dispatch-complete|worker\s+handle|context\s+pack|relay)\b",
    re.IGNORECASE,
)

import lifecycle_policy  # noqa: E402
import dispatcher  # noqa: E402
import run_state  # noqa: E402
import session_checkpoint  # noqa: E402

DISPATCH_TASK_ID_RE = re.compile(r"(?:Task ID|task[_ -]?id)\s*[:=]\s*(?P<task>[A-Za-z0-9_.-]+)", re.IGNORECASE)
DISPATCH_CONTEXT_PACK_RE = re.compile(
    r"(?:Context Pack|context[_ -]?pack)\s*[:=]\s*(?P<path>(?:[A-Za-z]:)?[A-Za-z0-9_./\\:-]*context-packs[\\/][A-Za-z0-9_.-]+\.json)",
    re.IGNORECASE,
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


def is_coordinator_inline_write_path(repo: Path, path: Path) -> bool:
    relative = posix_relative(repo, resolve_for_repo(repo, path)).replace("\\", "/")
    if relative.startswith(COORDINATOR_INLINE_WRITE_PREFIXES):
        return True
    if not relative.startswith("docs/agent-runs/"):
        return False
    if is_harness_control_path(repo, path):
        return False
    return not any(part in f"/{relative}" for part in COORDINATOR_INLINE_WRITE_EXCLUDED_RUN_PARTS)


def is_requirements_clarifier_owned_artifact(repo: Path, path: Path) -> bool:
    relative = posix_relative(repo, resolve_for_repo(repo, path)).replace("\\", "/")
    return (
        relative.startswith("docs/design/")
        or relative.endswith("/handoffs/01-requirements-clarifier.md")
        or relative.endswith("/evidence/impact-summary.md")
        or relative.endswith("/evidence/impact-analysis.json")
    )


def requirements_clarifier_task_for_state(repo: Path, state_path: Path, state_data: dict) -> dict:
    schedule_path = state_path.parent / "agent-schedule.json"
    schedule: dict = {}
    if schedule_path.exists():
        try:
            schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            schedule = {}
    tasks = [task for task in schedule.get("tasks", []) or [] if isinstance(task, dict)]
    current = state_data.get("dispatch") if isinstance(state_data.get("dispatch"), dict) else {}
    task_id = str(current.get("current_task_id", "")).strip()
    return next(
        (
            task
            for task in tasks
            if str(task.get("id", "")).strip() == task_id
            or str(task.get("agent", "")).strip() == "requirements-clarifier"
            or str(task.get("phase", "")).strip().lower() == "clarify"
        ),
        {
            "id": task_id or "T01",
            "agent": "requirements-clarifier",
            "outputs": ["docs/agent-runs/<run>/handoffs/01-requirements-clarifier.md"],
        },
    )


def required_todo_list_for_lifecycle(lifecycle: str) -> list[str]:
    return lifecycle_policy.required_todo_list_for_lifecycle(lifecycle)


def exploration_policy_for_lifecycle(lifecycle: str) -> dict:
    return lifecycle_policy.exploration_policy_for_lifecycle(lifecycle)


def clarification_interaction_for_lifecycle(lifecycle: str) -> dict:
    return lifecycle_policy.clarification_interaction_for_lifecycle(lifecycle)


def state_path_display(repo: Path, lock: Path | None) -> str:
    if not lock:
        return "docs/agent-runs/<run>/run-state.json"
    return posix_relative(repo, run_state_path_for_lock(repo, lock))


def pending_dispatch_ack_guidance(repo: Path, lock: Path | None) -> dict:
    if not lock:
        return {}
    state_path = run_state_path_for_lock(repo, lock)
    state = load_json(state_path)
    if not state:
        return {}
    dispatches: list[dict] = []
    dispatch = state.get("dispatch") if isinstance(state.get("dispatch"), dict) else {}
    if dispatch:
        dispatches.append(dispatch)
    all_dispatches = state.get("dispatches") if isinstance(state.get("dispatches"), dict) else {}
    for value in all_dispatches.values():
        if isinstance(value, dict) and value not in dispatches:
            dispatches.append(value)
    for item in dispatches:
        status = str(item.get("status", "")).strip()
        if status not in PENDING_DISPATCH_ACK_STATUSES:
            continue
        task_id = str(item.get("current_task_id", "")).strip()
        agent = str(item.get("current_agent", "")).strip()
        context_pack = str(item.get("context_pack", "")).strip()
        if not task_id or not context_pack:
            continue
        run_id = str(state.get("run_id", "")).strip() or posix_relative(repo, state_path.parent)
        spawn_request = f"{run_id.rstrip('/')}/dispatch-spawn-requests/{task_id}-spawn-request.json"
        ack_command = (
            "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-ack . "
            f"--state {posix_relative(repo, state_path)} --task-id {task_id}"
        )
        if agent:
            ack_command += f" --agent {agent}"
        ack_command += " --worker-handle <runtime-worker-id>"
        next_valid = (
            f"Spawn or acknowledge Task from {spawn_request} (Task ID: {task_id}; Context Pack: {context_pack}), "
            f"then run {ack_command}"
        )
        return {
            "next_valid_command": next_valid,
            "pending_dispatch": {
                "schema": "e2e-dev-harness.pending-dispatch-guidance.v1",
                "status": status,
                "task_id": task_id,
                "agent": agent,
                "context_pack": context_pack,
                "spawn_request": spawn_request,
                "ack_command": ack_command,
                "next_gate": "spawn_worker",
            },
        }
    return {}


def guidance_for_lifecycle(repo: Path, lock: Path | None, lifecycle: str = "") -> dict:
    state_path = state_path_display(repo, lock)
    todo_list = required_todo_list_for_lifecycle(lifecycle)
    base = {
        "not_deadlock": True,
        "next_valid_command": f"e2e_dev_harness.py next . --state {state_path}",
        "todo_policy": {
            "schema": "e2e-dev-harness.todo-policy.v1",
            "mode": "phase-scoped",
            "lifecycle": lifecycle or "<missing>",
            "rule": "TodoList must describe only the current lifecycle phase; do not include future implementation/code tasks before the implementation gate.",
        },
        "required_todo_list": todo_list,
        "exploration_policy": exploration_policy_for_lifecycle(lifecycle),
        "clarification_interaction": clarification_interaction_for_lifecycle(lifecycle),
        "allowed_direct_exploration_tools": ["Read", "Grep", "Glob", "List", "Search"],
        "direct_exploration_guidance": (
            "Start the harness run first, then use GitNexus first for impact analysis, call paths, cross-service dependencies, and route/topic/contract ownership. "
            "Use direct Read/Grep/Glob/List/Search only to discover missing seeds or quote small evidence after GitNexus points to a file."
        ),
        "agent_dispatch_guidance": (
            "Only spawn dispatcher-generated Task/subagent workers; they require "
            "dispatch-next, a context pack, and a scheduled task."
        ),
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
                "run dispatch-beat --max-workers 1 for requirements-clarifier",
                "record dispatch-ack for the spawned requirements worker",
                "run dispatch-complete with returned requirements evidence paths",
                "run e2e_dev_harness.py next . --state " + state_path,
            ],
            "phase_guidance": "Current lifecycle is CREATED. Coordinator dispatches requirements-clarifier and relays only returned questions/evidence.",
        },
        "CLARIFIED": {
            "allowed_actions": [
                "run plan --create-archive only when the full schedule/archive is missing",
                "run dispatch-beat/dispatch-next for R1 design review",
                "record dispatch-ack and dispatch-complete for R1 evidence",
                "run e2e_dev_harness.py next . --state " + state_path,
            ],
            "phase_guidance": "Current lifecycle is CLARIFIED. Coordinator dispatches R1/design workers; it does not perform design review locally.",
        },
        "SERVICE_DESIGN_REQUIRED": {
            "allowed_actions": [
                "run dispatch-beat/dispatch-next for service-design workers",
                "run e2e_dev_harness.py service-design . --run-state " + state_path,
                "run e2e_dev_harness.py next . --state " + state_path,
            ],
            "phase_guidance": "Current lifecycle requires dispatched service-design slice evidence before service code agents can proceed.",
        },
        "PLANNED": {
            "allowed_actions": [
                "run dispatch-beat/dispatch-next for TDD red and R2 workers",
                "record dispatch-ack for spawned workers",
                "run dispatch-complete with scheduled red-test and R2 evidence",
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
                "run dispatch-beat/dispatch-next for code-developer workers",
                "record dispatch-complete with green-test and manifest evidence",
                "run e2e_dev_harness.py ac-progress ...",
                "dispatch R3 review after all assigned ACs are covered",
            ],
            "phase_guidance": "Current lifecycle is IMPLEMENTED. Coordinator monitors dispatched code work and gates; it does not code locally.",
        },
    }
    selected = actions.get(lifecycle, actions[""])
    dispatch_guidance = pending_dispatch_ack_guidance(repo, lock)
    if dispatch_guidance:
        selected = {
            **selected,
            "phase_guidance": (
                "Current lifecycle is "
                + (lifecycle or "<missing>")
                + " and dispatcher task "
                + dispatch_guidance["pending_dispatch"]["task_id"]
                + " is awaiting worker acknowledgement. Spawn or acknowledge the generated Task, then record dispatch-ack."
            ),
        }
    if dispatch_guidance and lifecycle == "CREATED":
        selected = {
            **selected,
            "allowed_actions": [
                "spawn the dispatcher-generated Task from " + dispatch_guidance["pending_dispatch"]["spawn_request"],
                "record dispatch-ack for the spawned requirements worker",
                *selected.get("allowed_actions", []),
            ],
        }
    return {**base, **selected, **dispatch_guidance, "lifecycle": lifecycle or "<missing>"}


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


def normalized_shared_scope_owners(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for scope, owner in value.items():
        scope_key = str(scope).strip("/").replace("\\", "/")
        owner_key = str(owner).strip("/").replace("\\", "/")
        if scope_key and owner_key:
            result[scope_key] = owner_key
    return result


def owner_task_worker_running(state_data: dict, owner: dict) -> bool:
    task_id = str(owner.get("task_id", "")).strip()
    if not task_id:
        return False
    dispatch = dispatch_for_task(state_data, task_id)
    return (
        str(dispatch.get("status", "")).lower() == "worker_running"
        and str(dispatch.get("current_task_id", "")).strip() in {"", task_id}
        and "code-developer" in str(dispatch.get("current_agent", "")).strip().lower()
    )


def first_match(pattern: re.Pattern[str], text: str, group: str) -> str:
    match = pattern.search(text)
    return match.group(group).strip() if match else ""


def dispatcher_task_id(text: str) -> str:
    return first_match(DISPATCH_TASK_ID_RE, text, "task")


def dispatcher_context_pack(text: str) -> str:
    return first_match(DISPATCH_CONTEXT_PACK_RE, text, "path")


def schedule_task(schedule: dict, task_id: str) -> dict:
    for task in schedule.get("tasks", []) or []:
        if isinstance(task, dict) and str(task.get("id", "")) == task_id:
            return task
    return {}


def normalized_repo_path_text(repo: Path, value: str) -> str:
    text = str(value).strip()
    if not text:
        return ""
    path = Path(text)
    return posix_relative(repo, path if path.is_absolute() else repo / path)


def is_review_report_path(repo: Path, path: Path) -> bool:
    relative = posix_relative(repo, resolve_for_repo(repo, path)).replace("\\", "/")
    name = relative.rsplit("/", 1)[-1]
    return (
        relative.startswith("docs/agent-runs/")
        and "/reviews/" in f"/{relative}"
        and REVIEW_REPORT_NAME_RE.match(name) is not None
    )


def task_for_review_output(repo: Path, schedule: dict, review_path: Path) -> dict:
    target = posix_relative(repo, resolve_for_repo(repo, review_path)).replace("\\", "/")
    for task in schedule.get("tasks", []) or []:
        if not isinstance(task, dict):
            continue
        outputs = task.get("outputs") if isinstance(task.get("outputs"), list) else []
        normalized_outputs = {
            normalized_repo_path_text(repo, str(output)).replace("\\", "/")
            for output in outputs
            if str(output).strip()
        }
        if target in normalized_outputs:
            return task
    return {}


def dispatch_for_task(state_data: dict, task_id: str) -> dict:
    dispatches = state_data.get("dispatches") if isinstance(state_data.get("dispatches"), dict) else {}
    dispatch = dispatches.get(task_id) if isinstance(dispatches.get(task_id), dict) else {}
    if dispatch:
        return dispatch
    latest = state_data.get("dispatch") if isinstance(state_data.get("dispatch"), dict) else {}
    if str(latest.get("current_task_id", "")) == task_id:
        return latest
    return {}


def requirements_clarifier_worker_running(state_data: dict) -> bool:
    return active_worker_running(state_data, ["requirements-clarifier"])


def active_worker_running(state_data: dict, agent_markers: list[str] | None = None) -> bool:
    dispatches = state_data.get("dispatches") if isinstance(state_data.get("dispatches"), dict) else {}
    candidates = [value for value in dispatches.values() if isinstance(value, dict)]
    latest = state_data.get("dispatch") if isinstance(state_data.get("dispatch"), dict) else {}
    if latest:
        candidates.append(latest)
    markers = [marker.lower() for marker in agent_markers or [] if marker]
    return any(
        str(item.get("status", "")).lower() == "worker_running"
        and (not markers or any(marker in str(item.get("current_agent", "")).strip().lower() for marker in markers))
        for item in candidates
    )


def review_report_write_blockers(repo: Path, lock: Path | None, review_paths: list[Path]) -> list[str]:
    if not review_paths:
        return []
    if not lock or not lock.exists():
        return [
            "Review report write blocked: start an e2e-dev-harness run, then use dispatch-beat/dispatch-next to launch an isolated reviewer worker before writing R1/R2/R3 review reports."
        ]
    _, state_data, state_blockers = lock_state_pair(repo, lock)
    if state_blockers:
        return state_blockers
    schedule_path = lock.parent / "agent-schedule.json"
    schedule = load_json(schedule_path)
    if schedule.get("schema") != "e2e-dev-harness.agent-schedule.v1":
        return [
            f"Review report write blocked: dispatcher schedule is missing or invalid beside run-state: {posix_relative(repo, schedule_path)}."
        ]
    blocked: list[str] = []
    for review_path in review_paths:
        relative = posix_relative(repo, resolve_for_repo(repo, review_path)).replace("\\", "/")
        task = task_for_review_output(repo, schedule, review_path)
        task_id = str(task.get("id", "")).strip()
        if not task_id:
            blocked.append(
                f"Review report write blocked: {relative} is not owned by any scheduled reviewer task output; use dispatch-beat/dispatch-next from the harness schedule."
            )
            continue
        phase = str(task.get("phase", "")).lower()
        role_group = str(task.get("role_group", "")).lower()
        if phase not in REVIEW_DISPATCH_PHASES or role_group != "review":
            blocked.append(
                f"Review report write blocked: {relative} must be produced by an R1/R2/R3 review task, not phase {phase or '<missing>'}."
            )
            continue
        owner = str(task.get("owner", "")).strip()
        task_status = str(task.get("status", "")).lower()
        expected_agent = str(task.get("agent", "")).strip()
        if not owner or task_status not in CLAIMED_OWNER_STATUSES:
            blocked.append(f"Review report write blocked: reviewer task {task_id} must be claimed before writing {relative}.")
            continue
        dispatch = dispatch_for_task(state_data, task_id)
        if str(dispatch.get("status", "")) != "worker_running":
            blocked.append(
                f"Review report write blocked: {relative} must be written by active reviewer worker for task {task_id}. Run dispatch-beat/dispatch-next, spawn the requested worker, then dispatch-ack or let the hook auto-confirm before writing."
            )
            continue
        if str(dispatch.get("current_task_id", "")) not in {"", task_id}:
            blocked.append(f"Review report write blocked: active dispatch does not match reviewer task {task_id}.")
            continue
        current_agent = str(dispatch.get("current_agent", "")).strip()
        if expected_agent and current_agent and current_agent != expected_agent:
            blocked.append(
                f"Review report write blocked: active dispatch agent {current_agent} does not match scheduled reviewer {expected_agent} for task {task_id}."
            )
            continue
        if not (dispatch.get("worker_handle") or dispatch.get("spawn_confirmed_by") or dispatch.get("spawn_acknowledged_at")):
            blocked.append(f"Review report write blocked: reviewer task {task_id} has no runtime spawn confirmation.")
    return blocked


def active_dispatches(state_data: dict) -> list[dict]:
    dispatches: list[dict] = []
    current = state_data.get("dispatch") if isinstance(state_data.get("dispatch"), dict) else {}
    if current:
        dispatches.append(current)
    all_dispatches = state_data.get("dispatches") if isinstance(state_data.get("dispatches"), dict) else {}
    for dispatch in all_dispatches.values():
        if isinstance(dispatch, dict) and dispatch not in dispatches:
            dispatches.append(dispatch)
    return [
        dispatch
        for dispatch in dispatches
        if str(dispatch.get("status", "")).strip() in ACTIVE_DISPATCH_STATUSES
        and str(dispatch.get("current_task_id", "")).strip()
    ]


def task_outputs_for_dispatch(repo: Path, state_path: Path, task_id: str) -> set[str]:
    schedule_path = state_path.parent / "agent-schedule.json"
    schedule = load_json(schedule_path)
    outputs: set[str] = set()
    for task in schedule.get("tasks", []) or []:
        if not isinstance(task, dict) or str(task.get("id", "")).strip() != task_id:
            continue
        outputs.update(posix_relative(repo, resolve_for_repo(repo, Path(item))) for item in task.get("outputs", []) or [])
    return outputs


def worker_output_write_blockers(repo: Path, lock: Path | None, output_paths: list[Path]) -> list[str]:
    if not lock or not lock.exists() or not output_paths:
        return []
    _lock_data, state_data, state_blockers = lock_state_pair(repo, lock)
    if state_blockers:
        return state_blockers
    state_path = run_state_path_for_lock(repo, lock)
    requested = {
        posix_relative(repo, resolve_for_repo(repo, path))
        for path in output_paths
        if not is_review_report_path(repo, path)
    }
    if not requested:
        return []
    blocked: list[str] = []
    for dispatch in active_dispatches(state_data):
        task_id = str(dispatch.get("current_task_id", "")).strip()
        owned_outputs = task_outputs_for_dispatch(repo, state_path, task_id)
        touched = sorted(requested & owned_outputs)
        if not touched:
            continue
        if not worker_output_write_confirmed(dispatch):
            blocked.append(
                "Worker output write blocked: scheduled output is owned by active dispatch "
                + task_id
                + "; spawn the dispatcher-generated worker and let the Task hook prove the worker session before writing "
                + ", ".join(touched)
                + "."
            )
    return blocked


def worker_output_write_confirmed(dispatch: dict) -> bool:
    if str(dispatch.get("status", "")).strip() != "worker_running":
        return False
    confirmed_by = str(dispatch.get("spawn_confirmed_by", "")).strip()
    if confirmed_by == "phase_guard":
        return False
    if confirmed_by == "dispatch_ack":
        return bool(
            dispatch.get("manual_worker_confirmed") is True
            and str(dispatch.get("worker_handle", "")).strip()
            and str(dispatch.get("spawn_acknowledged_at", "")).strip()
        )
    return False


def todo_list_blockers(repo: Path, lock: Path | None, task_text: str) -> tuple[list[str], str]:
    text = task_text.strip()
    if not text:
        return [], ""
    has_code_todo = CODE_TODO_RE.search(text) is not None
    if not lock or not lock.exists():
        if has_code_todo or EXPLORATION_TODO_RE.search(text):
            return [
                "Todo list blocked: start an e2e-dev-harness run before planning implementation/code tasks or codebase exploration."
            ], ""
        return [], ""
    _, state_data, state_blockers = lock_state_pair(repo, lock)
    if state_blockers:
        return state_blockers, ""
    lifecycle = str(state_data.get("lifecycle", ""))
    if lifecycle != "IMPLEMENTED":
        if lifecycle == "CREATED" and not CREATED_COORDINATOR_TODO_RE.search(text):
            return [
                "Todo list blocked: CREATED coordinator work is dispatch-only. Run dispatch-beat --max-workers 1 for requirements-clarifier, relay only worker-returned Restated Intent/Open Questions, and do not perform local clarification or code exploration."
            ], lifecycle
        if has_code_todo:
            return [
                "Todo list blocked: current lifecycle "
                + (lifecycle or "<missing>")
                + " requires a phase-scoped TodoList. Do not list implementation/code/module-development tasks until the implementation gate opens."
            ], lifecycle
        if lifecycle == "CREATED" and EXPLORATION_TODO_RE.search(text):
            return [
                "Todo list blocked: CREATED coordinator work must dispatch requirements-clarifier instead of doing local GitNexus/rg/Read exploration."
            ], lifecycle
        if lifecycle == "CREATED" and CLARIFICATION_TODO_RE.search(text) and not USER_INTERACTION_TODO_RE.search(text):
            return [
                "Todo list blocked: clarification requires an explicit user interaction step. Add a TodoList item to ask/confirm the user's Restated Intent and resolve open questions before plan, TDD, or code work."
            ], lifecycle
        if EXPLORATION_TODO_RE.search(text) and not GITNEXUS_TODO_RE.search(text):
            return [
                "Todo list blocked: GitNexus-first exploration is required for impact analysis, call paths, dependencies, affected services, routes, topics, or contracts. Add a GitNexus/knowledge graph evidence step before direct rg/Read exploration."
            ], lifecycle
    return [], lifecycle


def validate_dispatch_context(repo: Path, state_data: dict, task_text: str) -> list[str]:
    task_id = first_match(DISPATCH_TASK_ID_RE, task_text, "task")
    context_pack_text = first_match(DISPATCH_CONTEXT_PACK_RE, task_text, "path")
    if not task_id or not context_pack_text:
        return [
            "Code-agent dispatch blocked: implementation Task must include a dispatcher context pack and Task ID generated by e2e_dev_harness.py dispatch-next."
        ]
    context_path = Path(context_pack_text)
    resolved_context = context_path if context_path.is_absolute() else repo / context_path
    pack = load_json(resolved_context)
    if not pack:
        return [f"Code-agent dispatch blocked: dispatcher context pack is missing or invalid: {context_pack_text}"]
    blocked: list[str] = []
    if pack.get("schema") != "e2e-dev-harness.context-pack.v1":
        blocked.append("Code-agent dispatch blocked: dispatcher context pack schema is invalid.")
    pack_task = pack.get("task") if isinstance(pack.get("task"), dict) else {}
    if str(pack_task.get("id", "")) != task_id:
        blocked.append("Code-agent dispatch blocked: dispatcher context pack task id does not match Task prompt.")
    schedule_text = str(pack.get("schedule", "")).strip()
    schedule_path = Path(schedule_text)
    resolved_schedule = schedule_path if schedule_path.is_absolute() else repo / schedule_path
    schedule = load_json(resolved_schedule)
    if not schedule:
        blocked.append(f"Code-agent dispatch blocked: dispatcher schedule is missing or invalid: {schedule_text or '<missing>'}")
        return blocked
    task = schedule_task(schedule, task_id)
    if not task:
        blocked.append(f"Code-agent dispatch blocked: task {task_id} is not present in dispatcher schedule.")
        return blocked
    owner = str(task.get("owner", "")).strip()
    status = str(task.get("status", "")).lower()
    if not owner or status not in CLAIMED_OWNER_STATUSES:
        blocked.append(f"Code-agent dispatch blocked: task {task_id} must be claimed before implementation Task dispatch.")
    expected_agent = str(pack_task.get("agent", "")).strip()
    if expected_agent and owner and owner != expected_agent:
        blocked.append("Code-agent dispatch blocked: claimed task owner does not match dispatcher context pack agent.")
    dispatches = state_data.get("dispatches") if isinstance(state_data.get("dispatches"), dict) else {}
    dispatch = dispatches.get(task_id) if isinstance(dispatches.get(task_id), dict) else {}
    if not dispatch:
        dispatch = state_data.get("dispatch") if isinstance(state_data.get("dispatch"), dict) else {}
    if dispatch and str(dispatch.get("current_task_id", "")) not in {"", task_id}:
        blocked.append("Code-agent dispatch blocked: run-state dispatch current_task_id does not match Task prompt.")
    return blocked


def auto_confirm_dispatcher_task(repo: Path, lock: Path, state_data: dict, task_text: str) -> str:
    """Emit guidance when a dispatcher worker-task prompt is observed.

    Option A: observing a worker-task prompt is too weak a signal to advance the
    dispatch lifecycle. This function no longer fabricates a confirmed spawn
    (it does not set ``worker_running_unverified``, write a synthetic
    ``phase-guard-auto-confirm`` handle, or persist run-state). It leaves the
    dispatch in ``awaiting_runtime_spawn`` and returns a guidance note pointing
    at the real ``dispatch-ack`` handle / manual-worker packet. The name is kept
    because its sole caller is ``_evaluate_dispatch_task``.
    """
    task_id = dispatcher_task_id(task_text)
    if not task_id:
        return ""
    state_path = run_state_path_for_lock(repo, lock)
    current_state = load_json(state_path) or state_data
    dispatches = current_state.get("dispatches") if isinstance(current_state.get("dispatches"), dict) else {}
    dispatch = dispatches.get(task_id) if isinstance(dispatches.get(task_id), dict) else {}
    if not dispatch:
        dispatch = current_state.get("dispatch") if isinstance(current_state.get("dispatch"), dict) else {}
    status = str(dispatch.get("status", ""))
    if status not in {"awaiting_runtime_spawn", "worker_dispatched", "dispatched"}:
        return ""
    if str(dispatch.get("current_task_id", "")) not in {"", task_id}:
        return ""
    return (
        f"Dispatcher task {task_id} prompt observed; phase_guard will NOT auto-confirm. "
        "Run dispatch-ack with a fresh worker handle (or use the manual-worker packet) "
        "before completion."
    )


def _evaluate_dispatch_task(
    repo: Path,
    lock: Path | None,
    text: str,
    warnings: list[str],
    *,
    blocked_message: str,
    require_lifecycle: bool,
) -> dict | None:
    """Validate a dispatcher-generated worker task (review or code) before launch.

    Returns a blocked response dict when the task must not proceed, or ``None``
    when it may proceed. On success any auto-confirmation note is appended to
    ``warnings``. ``require_lifecycle`` enforces the allowed implementation-phase
    check that only applies to code-agent dispatch.
    """
    if not lock or not lock.exists():
        return {
            "ready": False,
            "blocked_reasons": [blocked_message],
            "warnings": warnings,
            "action": "run e2e_dev_harness.py start . --feature <feature> --request <request>",
            **guidance_from_lock(repo, lock),
        }
    lock_data, state_data, state_blockers = lock_state_pair(repo, lock)
    if state_blockers:
        return {
            "ready": False,
            "blocked_reasons": state_blockers,
            "warnings": warnings,
            "phase_lock": str(lock),
            "run_state": str(run_state_path_for_lock(repo, lock)),
            **guidance_from_lock(repo, lock),
        }
    lifecycle = str(state_data.get("lifecycle", ""))
    if require_lifecycle:
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
                **guidance_from_lock(repo, lock),
            }
    dispatch_blockers = validate_dispatch_context(repo, state_data, text)
    if dispatch_blockers:
        return {
            "ready": False,
            "blocked_reasons": dispatch_blockers,
            "warnings": warnings,
            "phase_lock": str(lock),
            "run_state": str(run_state_path_for_lock(repo, lock)),
            "lifecycle": lifecycle,
            **guidance_from_lock(repo, lock),
        }
    confirmation = auto_confirm_dispatcher_task(repo, lock, state_data, text)
    if confirmation:
        warnings.append(confirmation)
    return None


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


def extract_hook_write_payload_text(text: str) -> str:
    if not text.strip():
        return ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return ""
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else data
    return "\n".join(collect_write_payload_text(tool_input))


def collect_write_payload_text(value, include: bool = False) -> list[str]:
    if isinstance(value, str):
        return [value] if include else []
    if isinstance(value, list):
        text: list[str] = []
        for item in value:
            text.extend(collect_write_payload_text(item, include))
        return text
    if isinstance(value, dict):
        text: list[str] = []
        for key, item in value.items():
            key_matches = str(key) in WRITE_PAYLOAD_KEYS
            text.extend(collect_write_payload_text(item, include or key_matches))
        return text
    return []


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
        value = match.group("cmdlet") or match.group("redir") or match.group("tee") or ""
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


def coordinator_write_budget(
    repo: Path,
    normalized_tool: str,
    paths: list[Path],
    shell_mutation: bool,
    command_text: str,
    write_payload_text: str,
) -> tuple[dict, list[str], list[str]]:
    if normalized_tool not in WRITE_TOOLS:
        return {}, [], []
    if normalized_tool in SHELL_TOOLS and not shell_mutation:
        return {}, [], []
    payload_chars = len(write_payload_text or "")
    if normalized_tool in SHELL_TOOLS:
        payload_chars = max(payload_chars, len(command_text or ""))
    budget_paths = [path for path in paths if is_coordinator_inline_write_path(repo, path)]
    if not payload_chars or not budget_paths:
        return {}, [], []
    details = {
        "schema": "e2e-dev-harness.coordinator-write-budget.v1",
        "inline_payload_chars": payload_chars,
        "warn_at_chars": COORDINATOR_INLINE_WRITE_WARN_CHARS,
        "block_at_chars": COORDINATOR_INLINE_WRITE_BLOCK_CHARS,
        "paths": result_paths(repo, budget_paths),
        "recommended_action": (
            "For long coordinator artifacts, dispatch a worker and require an evidence path, "
            "or use a checked-in generator/harness CLI command that writes the file without echoing the body into chat."
        ),
    }
    warnings: list[str] = []
    blockers: list[str] = []
    if payload_chars >= COORDINATOR_INLINE_WRITE_BLOCK_CHARS:
        blockers.append(
            "Coordinator write budget blocked: inline artifact body is "
            + str(payload_chars)
            + " chars, which exceeds "
            + str(COORDINATOR_INLINE_WRITE_BLOCK_CHARS)
            + ". Write long details through a worker evidence file or generator script, then keep only the path in coordinator chat."
        )
    elif payload_chars >= COORDINATOR_INLINE_WRITE_WARN_CHARS:
        warnings.append(
            "Coordinator write budget warning: inline artifact body is "
            + str(payload_chars)
            + " chars. Prefer worker evidence paths or generator scripts before the coordinator context grows."
        )
    return details, warnings, blockers


def _validate_action(
    repo: Path,
    tool: str,
    paths: list[Path],
    lock_path: Path | None = None,
    run_dir: Path | None = None,
    require_active_run_for_read: bool = False,
    command_text: str = "",
    task_text: str = "",
    write_payload_text: str = "",
    require_session_checkpoint: bool = False,
    checkpoint_max_age_minutes: int = 30,
) -> dict:
    repo = repo.resolve()
    normalized = normalize_tool(tool)
    shell_mutation = normalized in SHELL_TOOLS and shell_mutates_files(command_text)
    warnings: list[str] = []
    lock = discover_lock(repo, lock_path, run_dir)
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
            **guidance_from_lock(repo, lock),
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
            **guidance_from_lock(repo, lock),
        }
    hook_config_paths = [path for path in paths if is_hook_config_path(repo, path)]
    if normalized in WRITE_TOOLS and hook_config_paths and (normalized not in SHELL_TOOLS or shell_mutation):
        return {
            "ready": False,
            "blocked_reasons": [
                "Harness hook config edit blocked: disabling or loosening hooks is a bypass attempt. Use e2e_dev_harness.py install, install_hooks.py --check, or policy approval commands instead."
            ],
            "warnings": warnings,
            "protected_paths": result_paths(repo, hook_config_paths),
            **guidance_from_lock(repo, lock),
        }
    write_budget, write_budget_warnings, write_budget_blockers = coordinator_write_budget(
        repo,
        normalized,
        paths,
        shell_mutation,
        command_text,
        write_payload_text,
    )
    warnings.extend(write_budget_warnings)
    if write_budget_blockers:
        return {
            "ready": False,
            "blocked_reasons": write_budget_blockers,
            "warnings": warnings,
            "coordinator_write_budget": write_budget,
            **guidance_from_lock(repo, lock),
        }
    review_report_paths = [path for path in paths if is_review_report_path(repo, path)]
    if normalized in WRITE_TOOLS and review_report_paths and (normalized not in SHELL_TOOLS or shell_mutation):
        review_blockers = review_report_write_blockers(repo, lock, review_report_paths)
        if review_blockers:
            return {
                "ready": False,
                "blocked_reasons": review_blockers,
                "warnings": warnings,
                "review_report_paths": result_paths(repo, review_report_paths),
                **guidance_from_lock(repo, lock),
            }
    if normalized in WRITE_TOOLS and (normalized not in SHELL_TOOLS or shell_mutation):
        output_blockers = worker_output_write_blockers(repo, lock, paths)
        if output_blockers:
            return {
                "ready": False,
                "blocked_reasons": output_blockers,
                "warnings": warnings,
                "artifact_paths": result_paths(repo, paths),
                **guidance_from_lock(repo, lock),
            }
    if normalized in TODO_TOOLS:
        todo_blockers, todo_lifecycle = todo_list_blockers(repo, lock, task_text)
        if todo_blockers:
            guidance = guidance_for_lifecycle(repo, lock, todo_lifecycle) if todo_lifecycle else guidance_from_lock(repo, lock)
            return {
                "ready": False,
                "blocked_reasons": todo_blockers,
                "warnings": warnings,
                **guidance,
            }
        return {"ready": True, "blocked_reasons": [], "warnings": warnings, **guidance_from_lock(repo, lock)}
    if normalized in TASK_TOOLS:
        text = task_text.strip()
        code_task = bool(CODE_TASK_RE.search(text))
        dispatcher_task = bool(dispatcher_task_id(text) and dispatcher_context_pack(text))
        read_only_exploration_task = bool(READ_ONLY_EXPLORATION_TASK_RE.search(text)) and not code_task
        if dispatcher_task and not code_task:
            blocked = _evaluate_dispatch_task(
                repo,
                lock,
                text,
                warnings,
                blocked_message="Dispatcher task blocked: start an e2e-dev-harness run before assigning dispatcher-generated worker tasks.",
                require_lifecycle=False,
            )
            if blocked is not None:
                return blocked
        if code_task:
            blocked = _evaluate_dispatch_task(
                repo,
                lock,
                text,
                warnings,
                blocked_message="Code-agent dispatch blocked: start an e2e-dev-harness run and pass clarify/plan/TDD gates before assigning implementation work.",
                require_lifecycle=True,
            )
            if blocked is not None:
                return blocked
        if not dispatcher_task and PHASE_TASK_RE.search(text) and not read_only_exploration_task:
            return {
                "ready": False,
                "blocked_reasons": [
                    "Phase worker dispatch blocked: use dispatcher-generated Task prompts from dispatch-beat/dispatch-next with a Task ID and Context Pack."
                ],
                "warnings": warnings,
                **guidance_from_lock(repo, lock),
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
                    **guidance_from_lock(repo, lock),
                }
        else:
            _, state_data, state_blockers = lock_state_pair(repo, lock)
            if state_blockers:
                return {
                    "ready": False,
                    "blocked_reasons": state_blockers,
                    "warnings": warnings,
                    "phase_lock": str(lock),
                    "run_state": str(run_state_path_for_lock(repo, lock)),
                    "read_paths": result_paths(repo, read_targets),
                    **guidance_from_lock(repo, lock),
                }
            lifecycle = str(state_data.get("lifecycle", ""))
            if lifecycle == "CREATED" and (repo_wide or read_code_paths) and not requirements_clarifier_worker_running(state_data):
                return {
                    "ready": False,
                    "blocked_reasons": [
                        "Code exploration blocked: CREATED coordinator must dispatch requirements-clarifier and wait for worker acknowledgement before any code Read/Grep/Glob exploration; design-doc analysis may continue without direct code evidence."
                    ],
                    "warnings": warnings,
                    "phase_lock": str(lock),
                    "run_state": str(run_state_path_for_lock(repo, lock)),
                    "read_paths": result_paths(repo, read_targets),
                    **guidance_from_lock(repo, lock),
                }
            if lifecycle in DISPATCH_GATED_READ_LIFECYCLES and (repo_wide or read_code_paths) and not active_worker_running(state_data):
                return {
                    "ready": False,
                    "blocked_reasons": [
                        "Code exploration blocked: lifecycle "
                        + lifecycle
                        + " requires an active dispatched worker before Read/Grep/Glob code exploration; coordinator may only run next/dispatch/gate commands and relay evidence paths."
                    ],
                    "warnings": warnings,
                    "phase_lock": str(lock),
                    "run_state": str(run_state_path_for_lock(repo, lock)),
                    "read_paths": result_paths(repo, read_targets),
                    **guidance_from_lock(repo, lock),
                }
    clarifier_artifact_paths = [path for path in paths if is_requirements_clarifier_owned_artifact(repo, path)]
    if normalized in WRITE_TOOLS and clarifier_artifact_paths and (normalized not in SHELL_TOOLS or shell_mutation):
        if lock and lock.exists():
            _, state_data, state_blockers = lock_state_pair(repo, lock)
            state_path = run_state_path_for_lock(repo, lock)
            lifecycle = str(state_data.get("lifecycle", ""))
            if state_blockers:
                return {
                    "ready": False,
                    "blocked_reasons": state_blockers,
                    "warnings": warnings,
                    "phase_lock": str(lock),
                    "run_state": str(state_path),
                    "artifact_paths": result_paths(repo, clarifier_artifact_paths),
                    **guidance_from_lock(repo, lock),
                }
            if lifecycle == "CREATED" and not requirements_clarifier_worker_running(state_data):
                task = requirements_clarifier_task_for_state(repo, state_path, state_data)
                schedule_path = state_path.parent / "agent-schedule.json"
                dispatch = dispatcher.dispatch_for_task(state_data, str(task.get("id", "")).strip())
                recovery = dispatcher.dispatch_recovery_packet(repo, schedule_path, state_path, task, dispatch)
                return {
                    "ready": False,
                    "blocked_reasons": [
                        "Requirements-clarifier artifact write blocked: CREATED coordinator must wait for an active requirements-clarifier worker before writing design, requirements handoff, or impact evidence."
                    ],
                    "warnings": warnings,
                    "phase_lock": str(lock),
                    "run_state": str(state_path),
                    "artifact_paths": result_paths(repo, clarifier_artifact_paths),
                    **recovery,
                    **guidance_from_lock(repo, lock),
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
        result = {"ready": True, "blocked_reasons": [], "warnings": warnings, "code_paths": result_paths(repo, code_paths)}
        if write_budget:
            result["coordinator_write_budget"] = write_budget
        return result
    if not lock or not lock.exists():
        return {
            "ready": False,
            "blocked_reasons": ["Code write blocked: phase lock not found for active agent run."],
            "warnings": warnings,
            "code_paths": result_paths(repo, code_paths),
            **guidance_from_lock(repo, lock),
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
            **guidance_from_lock(repo, lock),
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
                **guidance_from_lock(repo, lock),
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
            **guidance_from_lock(repo, lock),
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
            **guidance_from_lock(repo, lock),
        }
    if test_code_paths and not runtime_code_paths and lifecycle == "PLANNED" and not active_worker_running(data, ["test-case-developer"]):
        return {
            "ready": False,
            "blocked_reasons": [
                "Test write blocked: PLANNED coordinator must dispatch a test-case-developer worker for TDD red evidence before writing test files."
            ],
            "warnings": warnings,
            "phase_lock": str(lock),
            "run_state": str(run_state_path_for_lock(repo, lock)),
            "lifecycle": lifecycle,
            "code_paths": result_paths(repo, code_paths),
            "test_code_paths": result_paths(repo, test_code_paths),
            "runtime_code_paths": result_paths(repo, runtime_code_paths),
            **guidance_from_lock(repo, lock),
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
        shared_scope_owners = normalized_shared_scope_owners(data.get("shared_edit_scope_owners"))
        touched_shared_scopes = {
            shared_scope_for_code_path(repo, path, shared_edit_scopes)
            for path in runtime_code_paths
        }
        touched_shared_scopes.discard("")
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
        for scope in sorted(touched_shared_scopes):
            required_owner = shared_scope_owners.get(scope)
            if not required_owner:
                continue
            owner = owners.get(required_owner) if isinstance(owners.get(required_owner), dict) else {}
            status = str(owner.get("status", "")).lower()
            agent = str(owner.get("agent", "")).strip()
            if not agent or status not in CLAIMED_OWNER_STATUSES:
                return {
                    "ready": False,
                    "blocked_reasons": [
                        "Multi-service code write blocked: shared edit scope "
                        + scope
                        + " is owned by "
                        + required_owner
                        + ", which has no claimed code-developer task in run-state owners."
                    ],
                    "warnings": warnings,
                    "phase_lock": str(lock),
                    "run_state": str(run_state_path_for_lock(repo, lock)),
                    "lifecycle": lifecycle,
                    "code_paths": result_paths(repo, code_paths),
                    "shared_scope": scope,
                    "required_owner": required_owner,
                }
            if not owner_task_worker_running(data, owner):
                return {
                    "ready": False,
                    "blocked_reasons": [
                        "Multi-service code write blocked: shared edit scope "
                        + scope
                        + " must be written by the active code-developer worker for "
                        + required_owner
                        + "."
                    ],
                    "warnings": warnings,
                    "phase_lock": str(lock),
                    "run_state": str(run_state_path_for_lock(repo, lock)),
                    "lifecycle": lifecycle,
                    "code_paths": result_paths(repo, code_paths),
                    "shared_scope": scope,
                    "required_owner": required_owner,
                }
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
    if code_paths and lifecycle == "IMPLEMENTED" and not active_worker_running(data, ["code-developer"]):
        return {
            "ready": False,
            "blocked_reasons": [
                "Code write blocked: IMPLEMENTED coordinator must dispatch an active code-developer worker before writing production or test code."
            ],
            "warnings": warnings,
            "phase_lock": str(lock),
            "run_state": str(run_state_path_for_lock(repo, lock)),
            "lifecycle": lifecycle,
            "code_paths": result_paths(repo, code_paths),
            "test_code_paths": result_paths(repo, test_code_paths),
            "runtime_code_paths": result_paths(repo, runtime_code_paths),
            **guidance_from_lock(repo, lock),
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


def compact_guidance_result(result: dict) -> dict:
    compact = dict(result)
    full_guidance_keys = {
        "required_todo_list",
        "exploration_policy",
        "clarification_interaction",
        "todo_policy",
        "allowed_direct_exploration_tools",
        "direct_exploration_guidance",
        "agent_dispatch_guidance",
        "forbidden_actions",
        "allowed_actions",
    }
    for key in full_guidance_keys:
        compact.pop(key, None)
    next_action = str(result.get("next_valid_command") or "")
    if not next_action:
        actions = result.get("allowed_actions", [])
        if isinstance(actions, list) and actions:
            next_action = str(actions[0])
    compact["next_single_action"] = next_action
    if isinstance(result.get("pending_dispatch"), dict):
        compact["guidance_ref"] = "Use pending_dispatch.spawn_request, pending_dispatch.task_id, and pending_dispatch.ack_command."
    else:
        ref = str(result.get("run_state") or result.get("phase_lock") or "docs/agent-runs/<run>/run-state.json")
        compact["guidance_ref"] = f"Run e2e_dev_harness.py next . --state {ref} for full phase guidance."
    return compact


def validate_action(
    repo: Path,
    tool: str,
    paths: list[Path],
    lock_path: Path | None = None,
    run_dir: Path | None = None,
    require_active_run_for_read: bool = False,
    command_text: str = "",
    task_text: str = "",
    write_payload_text: str = "",
    require_session_checkpoint: bool = False,
    checkpoint_max_age_minutes: int = 30,
    compact_guidance: bool = False,
) -> dict:
    result = _validate_action(
        repo,
        tool,
        paths,
        lock_path,
        run_dir,
        require_active_run_for_read,
        command_text=command_text,
        task_text=task_text,
        write_payload_text=write_payload_text,
        require_session_checkpoint=require_session_checkpoint,
        checkpoint_max_age_minutes=checkpoint_max_age_minutes,
    )
    return compact_guidance_result(result) if compact_guidance else result


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
    parser.add_argument("--compact-guidance", action="store_true")
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
        write_payload_text = extract_hook_write_payload_text(hook_text)
        task_text = extract_task_text(hook_text)
    else:
        command_text = ""
        write_payload_text = ""
        task_text = ""
    result = validate_action(
        args.repo,
        tool,
        paths,
        args.lock,
        args.run_dir,
        args.require_active_run_for_read,
        command_text=command_text,
        write_payload_text=write_payload_text,
        task_text=task_text,
        require_session_checkpoint=args.require_session_checkpoint,
        checkpoint_max_age_minutes=args.checkpoint_max_age_minutes,
        compact_guidance=args.compact_guidance,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if not result["ready"]:
            summary = "; ".join(result.get("blocked_reasons") or ["blocked"])
            print("Phase guard BLOCKED: " + summary, file=sys.stderr)
            action = result.get("action")
            if action:
                print("Next action: " + str(action), file=sys.stderr)
            if result.get("phase_guidance"):
                print("Guidance: " + str(result["phase_guidance"]), file=sys.stderr)
            if result.get("next_valid_command"):
                print("Next valid command: " + str(result["next_valid_command"]), file=sys.stderr)
            if result.get("forbidden_actions"):
                print("Forbidden bypasses: " + "; ".join(str(item) for item in result["forbidden_actions"]), file=sys.stderr)
    else:
        print("Phase guard: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
