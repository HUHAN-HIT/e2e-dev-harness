#!/usr/bin/env python3
"""Environment doctor for e2e-dev-harness adoption."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import install_hooks  # noqa: E402
import dispatcher  # noqa: E402
import dir_graph  # noqa: E402
import event_log  # noqa: E402
import kg_refresh  # noqa: E402
import plugin_registry  # noqa: E402
import run_state  # noqa: E402


MIN_PYTHON = (3, 10)


def check(check_id: str, status: str, severity: str, message: str, remediation: str = "") -> dict:
    return {
        "id": check_id,
        "status": status,
        "severity": severity,
        "message": message,
        "remediation": remediation,
    }


def executable(name: str) -> str:
    return shutil.which(name) or ""


def python_check() -> dict:
    version = sys.version_info
    text = f"Python {version.major}.{version.minor}.{version.micro}"
    if (version.major, version.minor) < MIN_PYTHON:
        return check(
            "python",
            "fail",
            "error",
            text + " is below the supported minimum.",
            "Install Python 3.10+ and rerun doctor.",
        )
    return check("python", "pass", "info", text)


def skill_layout_check() -> dict:
    required = [
        SKILL_DIR / "SKILL.md",
        SCRIPT_DIR / "e2e_dev_harness.py",
        SCRIPT_DIR / "phase_guard.py",
        SCRIPT_DIR / "harness_stop_guard.py",
        SCRIPT_DIR / "session_checkpoint.py",
        SKILL_DIR / "hooks" / "claude-code-settings.example.json",
        SKILL_DIR / "hooks" / "opencode-plugin.example.js",
        SKILL_DIR / "review-profiles" / "default.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return check(
            "skill-layout",
            "fail",
            "error",
            "Required skill files are missing: " + ", ".join(missing),
            "Reinstall or repair the e2e-dev-harness skill directory.",
        )
    return check("skill-layout", "pass", "info", f"Skill directory looks complete: {SKILL_DIR}")


def repo_shape_check(repo: Path) -> dict:
    markers = [".git", "pom.xml", "services", "docs"]
    present = [marker for marker in markers if (repo / marker).exists()]
    if not present:
        return check(
            "repo-shape",
            "warn",
            "warning",
            "No common project markers were found at repo root.",
            "Run doctor from the target repository root.",
        )
    return check("repo-shape", "pass", "info", "Detected project markers: " + ", ".join(present))


def pytest_check() -> dict:
    if executable("pytest"):
        return check("pytest", "pass", "info", "pytest is available.")
    return check(
        "pytest",
        "warn",
        "warning",
        "pytest is not on PATH.",
        "Install test dependencies before running harness self-tests.",
    )


def maven_check(repo: Path) -> dict:
    has_maven_project = (repo / "pom.xml").exists() or any(repo.glob("*/pom.xml"))
    mvn = executable("mvn") or executable("mvn.cmd")
    if mvn:
        return check("maven", "pass", "info", f"Maven is available: {mvn}")
    if has_maven_project:
        return check(
            "maven",
            "fail",
            "error",
            "Maven project detected but mvn/mvn.cmd is not on PATH.",
            "Install Maven or add mvn.cmd to PATH.",
        )
    return check("maven", "warn", "warning", "No Maven executable found; no pom.xml was detected.")


def gitnexus_check(repo: Path) -> dict:
    gitnexus = executable("gitnexus")
    if gitnexus:
        index = kg_refresh.detect_gitnexus_index(repo)
        if not index.get("exists"):
            return check(
                "gitnexus",
                "pass",
                "info",
                f"GitNexus CLI is available: {gitnexus}; index metadata not found at {index.get('meta_path')}.",
                index.get("recommended_refresh_command") or "gitnexus analyze .",
            )
        summary = (
            f"GitNexus CLI is available: {gitnexus}; "
            f"lastCommit={index.get('last_commit') or 'unknown'}; "
            f"HEAD={index.get('current_head') or 'unknown'}; "
            f"indexedAt={index.get('indexed_at') or 'unknown'}; "
            f"graph={index.get('graph_status') or 'unknown'}; "
            f"FTS={index.get('fts_status') or 'unknown'}; "
            f"nodes={index.get('nodes') or 'unknown'}; "
            f"edges={index.get('edges') or 'unknown'}."
        )
        if index.get("is_stale"):
            return check(
                "gitnexus",
                "warn",
                "warning",
                "GitNexus index is stale; " + summary,
                index.get("recommended_refresh_command") or "gitnexus analyze .",
            )
        if index.get("repo_path") and not index.get("repo_path_matches"):
            return check(
                "gitnexus",
                "warn",
                "warning",
                "GitNexus index repoPath does not match this repository; " + summary,
                index.get("recommended_refresh_command") or "gitnexus analyze .",
            )
        return check("gitnexus", "pass", "info", summary)
    return check(
        "gitnexus",
        "warn",
        "warning",
        "GitNexus CLI is not on PATH.",
        "Install GitNexus or plan an approved degradation path for critical/audited Java impact evidence.",
    )


def dir_graph_check(repo: Path) -> dict:
    loaded = dir_graph.load_dir_graph(repo)
    path = str(loaded.get("path", repo / dir_graph.DIR_GRAPH_PATH))
    if not loaded.get("exists"):
        return check(
            "dir-graph",
            "warn",
            "warning",
            f"Dir graph contract not found: {path}.",
            "Create .e2e/dir-graph.yaml to make directory roles, lifecycle, pipeline, and skill IO contracts visible to doctor/preflight.",
        )
    blocked = [str(reason) for reason in loaded.get("blocked_reasons", []) or []]
    graph = loaded.get("graph", {})
    if not isinstance(graph, dict):
        blocked.append("Dir graph contract must parse to an object.")
    else:
        blocked.extend(dir_graph.validate_dir_graph(repo, graph))
    if blocked:
        return check(
            "dir-graph",
            "fail",
            "error",
            " ".join(blocked),
            "Update .e2e/dir-graph.yaml so it matches run_state lifecycles, gate transitions, and coordinator_flow.BLUEPRINT_STEPS.",
        )
    roles = [
        str(item.get("role", "")).strip()
        for item in graph.get("skill_contracts", []) or []
        if isinstance(item, dict) and str(item.get("role", "")).strip()
    ]
    return check(
        "dir-graph",
        "pass",
        "info",
        f"Dir graph contract is valid: {path}; roles={len(roles)}.",
    )


def claude_hook_check(repo: Path) -> dict:
    project_target = repo / ".claude" / "settings.json"
    user_target = Path.home() / ".claude" / "settings.json"
    project = install_hooks.validate_config(project_target, repo)
    user = install_hooks.validate_config(user_target, repo)
    if project["ready"]:
        return check("claude-hooks", "pass", "info", f"Project Claude PreToolUse and Stop hooks are ready: {project_target}")
    if user["ready"]:
        return check(
            "claude-hooks",
            "pass",
            "info",
            f"User Claude PreToolUse and Stop hooks are ready: {user_target}",
            "Project hook is not ready; user-level hook is currently providing enforcement.",
        )
    if project_target.parent.exists():
        return check(
            "claude-hooks",
            "fail",
            "error",
            "Project Claude hook directory exists but no enforcing e2e-dev-harness PreToolUse/Stop hook pair is ready: "
            + "; ".join(project.get("blocked_reasons", [])),
            "Run install_hooks.py . --runtime claude --json and confirm PreToolUse includes Read/Grep/Glob/Bash and Stop calls harness_stop_guard.py.",
        )
    if user_target.parent.exists():
        return check(
            "claude-hooks",
        "warn",
        "warning",
        "User Claude hook config exists but is not an enforcing e2e-dev-harness PreToolUse/Stop hook pair.",
        "Install project-local hooks for this repository or use pre-code in runtimes without blocking hooks.",
        )
    return check(
        "claude-hooks",
        "warn",
        "warning",
        "No Claude hook configuration directory was found.",
        "Run install_hooks.py . --runtime claude --json when using Claude Code, or use pre-code in runtimes without blocking hooks.",
    )


def opencode_hook_check(repo: Path) -> dict:
    target = repo / ".opencode" / "plugins" / "e2e-dev-harness.js"
    result = install_hooks.validate_config(target, repo)
    if result["ready"]:
        return check("opencode-hooks", "pass", "info", f"Project OpenCode tool.execute.before plugin is ready: {target}")
    if target.parent.exists():
        return check(
            "opencode-hooks",
            "fail",
            "error",
            "Project OpenCode plugin directory exists but no enforcing e2e-dev-harness plugin is ready: "
            + "; ".join(result.get("blocked_reasons", [])),
            "Run install_hooks.py . --runtime opencode --json and confirm .opencode/plugins/e2e-dev-harness.js is loaded.",
        )
    return check(
        "opencode-hooks",
        "warn",
        "warning",
        "No OpenCode plugin directory was found.",
        "Run install_hooks.py . --runtime opencode --json when using OpenCode, or use pre-code before code edits.",
    )


def resolve_repo_path(repo: Path, value: Path) -> Path:
    return value if value.is_absolute() else repo / value


def read_json_file(path: Path) -> tuple[dict | None, str]:
    if not path.exists():
        return None, f"File not found: {path}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, f"File is not readable JSON: {path}: {error}"
    if not isinstance(data, dict):
        return None, f"File must contain a JSON object: {path}"
    return data, ""


def completed_schedule_tasks(schedule: dict) -> list[dict]:
    return [
        task
        for task in schedule.get("tasks", []) or []
        if isinstance(task, dict) and str(task.get("status", "")).lower() == "completed"
    ]


def run_timeline(run_dir: Path) -> list[dict]:
    timeline: list[dict] = []
    for item in event_log.read_events(run_dir):
        timeline.append(
            {
                "sequence": item.get("sequence", 0),
                "event": item.get("event", ""),
                "task_id": item.get("task_id", ""),
                "agent": item.get("agent", ""),
                "status": item.get("status", ""),
                "created_at": item.get("created_at", ""),
            }
        )
    return timeline


def active_dispatch_recommendation(state_data: dict, state_path: Path) -> tuple[list[dict], str]:
    dispatch = state_data.get("dispatch") if isinstance(state_data.get("dispatch"), dict) else {}
    task_id = str(dispatch.get("current_task_id", "")).strip()
    agent = str(dispatch.get("current_agent", "")).strip()
    status = str(dispatch.get("status", "")).strip()
    if not task_id or status not in {"awaiting_runtime_spawn", "waiting_dispatch", "worker_running", "worker_dispatched", "dispatched"}:
        return [], ""
    state_arg = state_path.as_posix()
    schedule_arg = (state_path.parent / "agent-schedule.json").as_posix()
    taxonomy = [
        {
            "code": "dispatch-complete",
            "task_id": task_id,
            "status": status,
            "message": f"Task {task_id} has an active dispatch that has not closed with validated evidence.",
        }
    ]
    command = (
        "Spawn or acknowledge the worker if needed, then run "
        "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-complete . "
        f"--schedule {schedule_arg} --state {state_arg} --task-id {task_id} --agent {agent} "
        "--evidence <worker-output-path>"
    )
    return taxonomy, command


def recovery_plan(
    repo: Path,
    state: Path,
    schedule: Path | None = None,
    task_id: str = "",
    agent: str = "",
    evidence: list[str] | None = None,
) -> dict:
    repo = repo.resolve()
    state_path = resolve_repo_path(repo, state)
    schedule_path = resolve_repo_path(repo, schedule) if schedule else state_path.parent / "agent-schedule.json"
    evidence = evidence or []
    state_data, _state_error = read_json_file(state_path)
    dispatch = state_data.get("dispatch") if isinstance(state_data, dict) and isinstance(state_data.get("dispatch"), dict) else {}
    resolved_task_id = task_id or str(dispatch.get("current_task_id", "")).strip()
    resolved_agent = agent or str(dispatch.get("current_agent", "")).strip()
    request_path = state_path.parent / "recovery-requests" / f"{resolved_task_id or 'dispatch'}-recovery.json"
    request_result = dispatcher.write_recovery_request(
        repo,
        request_path,
        resolved_task_id,
        resolved_agent,
        evidence,
        reason="Manual recovery requested from harness doctor recovery plan.",
    )
    command = (
        "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-status . "
        f"--schedule {schedule_path.as_posix()} --state {state_path.as_posix()} "
        f"--write-recovery-request {request_path.as_posix()} --task-id {resolved_task_id} --agent {resolved_agent}"
    )
    for item in evidence:
        command += f" --evidence {item}"
    taxonomy, recommended_command = active_dispatch_recommendation(state_data or {}, state_path)
    blockers = [] if request_result.get("ready") else list(request_result.get("blocked_reasons", []) or [])
    if request_result.get("ready"):
        blockers.append("Recovery request is written but still requires explicit user approval before dispatch-complete --manual-recovery can close the task.")
    approval_status = {
        "status": "approval_required" if request_result.get("ready") else "request_blocked",
        "approval_schema": "e2e-dev-harness.recovery-approval.v1",
        "request_path": request_result.get("path", str(request_path)),
        "approved": False,
    }
    return {
        "schema": "e2e-dev-harness.recovery-plan.v1",
        "ready": False,
        "blocked_reasons": blockers,
        "warnings": list(request_result.get("warnings", []) or []),
        "repo": str(repo),
        "state": str(state_path),
        "schedule": str(schedule_path),
        "task_id": resolved_task_id,
        "agent": resolved_agent,
        "run_timeline": run_timeline(state_path.parent),
        "failure_taxonomy": taxonomy,
        "recommended_command": recommended_command,
        "recovery_request_command": command,
        "recovery_request_path": request_result.get("path", str(request_path)),
        "recovery_request": request_result.get("request", {}),
        "recovery_approval_status": approval_status,
    }


def state_consistency_checks(repo: Path, state: Path) -> list[dict]:
    state_path = resolve_repo_path(repo, state)
    state_data, state_error = read_json_file(state_path)
    if state_error or state_data is None:
        return [
            check(
                "state-run-state",
                "fail",
                "error",
                state_error,
                "Pass --state docs/agent-runs/<run>/run-state.json from an existing harness run.",
            )
        ]

    run_dir = state_path.parent
    schedule_path = run_dir / "agent-schedule.json"
    schedule_data, schedule_error = read_json_file(schedule_path)
    task_blockers: list[str] = []
    if schedule_error or schedule_data is None:
        task_blockers.append(f"agent-schedule.json is missing or invalid beside run-state: {schedule_error}")
        schedule_data = {}

    dispatches = state_data.get("dispatches", {}) if isinstance(state_data.get("dispatches"), dict) else {}
    top_dispatch = state_data.get("dispatch", {}) if isinstance(state_data.get("dispatch"), dict) else {}
    event_dir = run_dir / "dispatch-events"
    for task in completed_schedule_tasks(schedule_data):
        task_id = str(task.get("id", ""))
        if not task_id:
            continue
        event_path = event_dir / f"{task_id}-completed.json"
        if not event_path.exists():
            task_blockers.append(
                f"Schedule task {task_id} is completed but dispatch event is missing: {event_path.name}."
            )
        dispatch = dispatches.get(task_id, {})
        if not isinstance(dispatch, dict):
            dispatch = {}
        status = str(dispatch.get("status", ""))
        if not status and str(top_dispatch.get("current_task_id", "")) == task_id:
            status = str(top_dispatch.get("status", ""))
        if status in {"worker_running", "worker_dispatched", "dispatched", "waiting_dispatch", "awaiting_runtime_spawn"}:
            task_blockers.append(
                f"Schedule task {task_id} is completed but dispatch status is still {status}."
            )

    task_check = check(
        "state-dispatch-tasks",
        "pass" if not task_blockers else "fail",
        "info" if not task_blockers else "error",
        "Run-state dispatch tasks are consistent with schedule and completion events."
        if not task_blockers
        else " ".join(task_blockers),
        "Run dispatch-complete or manual recovery dispatch-complete for the completed task so schedule, dispatches, and dispatch-events close together.",
    )

    view_blockers: list[str] = []
    current_task = str(top_dispatch.get("current_task_id", ""))
    if current_task and isinstance(dispatches.get(current_task), dict):
        nested = dispatches[current_task]
        for key in ("status", "current_agent", "worker_handle", "worker_session"):
            top_value = str(top_dispatch.get(key, ""))
            nested_value = str(nested.get(key, ""))
            if top_value and nested_value and top_value != nested_value:
                view_blockers.append(
                    f"Top-level dispatch {key}={top_value} does not match dispatches[{current_task}].{key}={nested_value}."
                )
    view_check = check(
        "state-dispatch-view",
        "pass" if not view_blockers else "fail",
        "info" if not view_blockers else "error",
        "Top-level dispatch compatibility view matches dispatches."
        if not view_blockers
        else " ".join(view_blockers),
        "Rebuild the top-level dispatch compatibility view from run-state dispatches without changing lifecycle.",
    )

    lifecycle = str(state_data.get("lifecycle", "")).strip()
    lifecycle_status = "pass"
    lifecycle_severity = "info"
    lifecycle_message = "Run-state lifecycle is present and uses a main workflow phase."
    lifecycle_remediation = "Keep dispatch waiting under dispatches[task_id].status; do not edit run-state.json directly."
    if not lifecycle:
        lifecycle_status = "fail"
        lifecycle_severity = "error"
        lifecycle_message = "Run-state lifecycle is missing."
        lifecycle_remediation = (
            "Repair run-state.json first by restoring one main lifecycle from dispatch.previous_lifecycle, "
            ".phase-lock, or transition history, then rerun doctor/next so derived views rebuild."
        )
    elif lifecycle not in run_state.LIFECYCLE:
        lifecycle_status = "fail"
        lifecycle_severity = "error"
        lifecycle_message = f"Run-state lifecycle is invalid: {lifecycle}."
        lifecycle_remediation = (
            "Repair run-state.json first with a valid main lifecycle, then rerun doctor/next so derived views rebuild."
        )
    elif lifecycle == "WAITING_DISPATCH":
        lifecycle_status = "warn"
        lifecycle_severity = "warning"
        lifecycle_message = (
            "Legacy run-state lifecycle WAITING_DISPATCH detected; dispatch waiting should live in dispatches[task_id].status."
        )
        lifecycle_remediation = (
            "Migrate by restoring the previous main lifecycle and preserving waiting_dispatch under dispatches[task_id].status."
        )
    lifecycle_check = check(
        "state-lifecycle",
        lifecycle_status,
        lifecycle_severity,
        lifecycle_message,
        lifecycle_remediation,
    )

    lock_path = run_dir / run_state.PHASE_LOCK
    lock_data, lock_error = read_json_file(lock_path)
    lock_blockers: list[str] = []
    lock_warnings: list[str] = []
    if lock_error or lock_data is None:
        lock_blockers.append(f".phase-lock is missing or invalid beside run-state: {lock_error}")
    elif lifecycle_status == "fail":
        lock_warnings.append(
            ".phase-lock lifecycle comparison skipped until run-state lifecycle is repaired."
        )
    else:
        lock_lifecycle = str(lock_data.get("lifecycle", ""))
        if lock_lifecycle != lifecycle:
            lock_blockers.append(
                f".phase-lock lifecycle {lock_lifecycle} does not match run-state lifecycle {lifecycle}."
            )
    lock_check = check(
        "state-phase-lock",
        "fail" if lock_blockers else ("warn" if lock_warnings else "pass"),
        "error" if lock_blockers else ("warning" if lock_warnings else "info"),
        ".phase-lock matches run-state lifecycle."
        if not lock_blockers and not lock_warnings
        else " ".join(lock_blockers + lock_warnings),
        "Rebuild .phase-lock from run-state by rewriting run-state through the harness transition/write API.",
    )

    summary_path = run_dir / "coordinator-summary.json"
    summary_data, summary_error = read_json_file(summary_path)
    summary_warnings: list[str] = []
    if summary_error or summary_data is None:
        summary_warnings.append(f"coordinator-summary.json is missing or invalid beside run-state: {summary_error}")
    else:
        summary_lifecycle = str(summary_data.get("lifecycle", ""))
        if summary_lifecycle != lifecycle:
            summary_warnings.append(
                f"coordinator-summary lifecycle {summary_lifecycle} does not match run-state lifecycle {lifecycle}."
            )
    summary_check = check(
        "state-coordinator-summary",
        "pass" if not summary_warnings else "warn",
        "info" if not summary_warnings else "warning",
        "coordinator-summary lifecycle matches run-state."
        if not summary_warnings
        else " ".join(summary_warnings),
        "Run next or rebuild coordinator summary from run-state; this is a derived view.",
    )

    enterprise_events = event_log.read_events(run_dir)
    event_mismatches = event_log.snapshot_mismatches(enterprise_events, state_data)
    event_check = check(
        "state-event-log",
        "pass" if not event_mismatches else "fail",
        "info" if not event_mismatches else "error",
        "Enterprise event log is consistent with run-state dispatch snapshots."
        if not event_mismatches
        else " ".join(event_mismatches),
        "Inspect docs/agent-runs/<run>/events in sequence order; repair the first mismatched event or rebuild derived snapshots from the event log.",
    )

    return [
        check("state-run-state", "pass", "info", f"Run-state loaded: {state_path}"),
        lifecycle_check,
        task_check,
        view_check,
        lock_check,
        summary_check,
        event_check,
    ]


def bootstrap_guide(repo: Path, state: Path | None = None) -> dict:
    state_path = resolve_repo_path(repo, state) if state else None
    detected_state = state_path if state_path and state_path.exists() else None
    if detected_state is None:
        candidates = sorted((repo / "docs" / "agent-runs").glob("*/run-state.json"))
        detected_state = candidates[-1] if candidates else None
    run_state_ref = detected_state.as_posix() if detected_state else "docs/agent-runs/<run>/run-state.json"
    run_state_detected = detected_state is not None
    steps = [
        {
            "id": "start",
            "command": 'python skills/e2e-dev-harness/scripts/e2e_dev_harness.py start . --feature "<feature>" --request "<request>"',
            "why": "Create docs/agent-runs/<run>/run-state.json and agent-schedule.json.",
        },
        {
            "id": "install_hooks",
            "command": "python skills/e2e-dev-harness/scripts/install_hooks.py . --runtime claude --json",
            "why": "Install runtime hooks so dispatch can spawn isolated workers instead of falling back to manual guidance.",
        },
        {
            "id": "next",
            "command": f"python skills/e2e-dev-harness/scripts/e2e_dev_harness.py next . --state {run_state_ref}",
            "why": "Create or refresh the session checkpoint and return the next dispatch command.",
        },
        {
            "id": "dispatch",
            "command": f"python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-beat . --state {run_state_ref} --max-workers 1",
            "why": "Produce runtime spawn requests for scheduled workers such as requirements-clarifier.",
        },
    ]
    return {
        "schema": "e2e-dev-harness.bootstrap-guide.v1",
        "run_state_detected": run_state_detected,
        "run_state": str(detected_state) if detected_state else "",
        "steps": steps,
        "next_single_action": steps[2 if run_state_detected else 0]["command"],
    }


def evaluate(repo: Path, strict: bool = False, state: Path | None = None) -> dict:
    repo = repo.resolve()
    checks = [
        python_check(),
        skill_layout_check(),
        repo_shape_check(repo),
        pytest_check(),
        maven_check(repo),
        gitnexus_check(repo),
        dir_graph_check(repo),
        claude_hook_check(repo),
        opencode_hook_check(repo),
    ]
    if state:
        checks.extend(state_consistency_checks(repo, state))
    state_path = resolve_repo_path(repo, state) if state else None
    state_data, _state_error = read_json_file(state_path) if state_path else ({}, "")
    timeline = run_timeline(state_path.parent) if state_path and state_path.exists() else []
    enterprise_events = event_log.read_events(state_path.parent) if state_path and state_path.exists() else []
    first_inconsistent_event = None
    if state_path and state_path.exists() and isinstance(state_data, dict):
        schedule_data, _schedule_error = read_json_file(state_path.parent / "agent-schedule.json")
        first_inconsistent_event = event_log.first_snapshot_mismatch(
            enterprise_events,
            state_data,
            schedule_data or {},
        )
    taxonomy, recommended_command = active_dispatch_recommendation(state_data or {}, state_path) if state_path else ([], "")
    extension_registry = plugin_registry.load_registry(repo)
    extension_provider_health = plugin_registry.provider_health(repo, extension_registry)
    guide = bootstrap_guide(repo, state)
    blockers = [
        item for item in checks
        if item["status"] == "fail" or (strict and item["status"] == "warn")
    ]
    check_statuses = {item["id"]: item["status"] for item in checks}
    mismatch_count = 1 if first_inconsistent_event else 0
    metrics_summary = {
        "event_count": len(enterprise_events),
        "timeline_count": len(timeline),
        "mismatch_count": mismatch_count,
        "failed_check_count": len([item for item in checks if item["status"] == "fail"]),
        "warning_check_count": len([item for item in checks if item["status"] == "warn"]),
        "active_failure_count": len(taxonomy),
    }
    replay_report = {
        "schema": "e2e-dev-harness.replay-report.v1",
        "checks": check_statuses,
        "event_count": len(enterprise_events),
        "first_inconsistent_event": first_inconsistent_event,
        "recommended_command": recommended_command,
    }
    return {
        "schema": "e2e-dev-harness.doctor.v1",
        "repo": str(repo),
        "ready": not blockers,
        "strict": strict,
        "checks": checks,
        "blocked_reasons": [item["message"] for item in blockers],
        "warnings": [item["message"] for item in checks if item["status"] == "warn"],
        "extension_registry": extension_registry,
        "extension_provider_health": extension_provider_health,
        "bootstrap_guide": guide,
        "run_timeline": timeline,
        "first_inconsistent_event": first_inconsistent_event,
        "failure_taxonomy": taxonomy,
        "recommended_command": recommended_command,
        "metrics_summary": metrics_summary,
        "replay_report": replay_report,
    }


def format_text(result: dict) -> str:
    lines = ["Harness doctor: " + ("READY" if result["ready"] else "BLOCKED")]
    for item in result["checks"]:
        marker = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}.get(item["status"], item["status"].upper())
        lines.append(f"- {marker} {item['id']}: {item['message']}")
        if item.get("remediation"):
            lines.append(f"  fix: {item['remediation']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--strict", action="store_true", help="Treat warnings as blockers.")
    parser.add_argument("--state", type=Path, help="Check consistency for docs/agent-runs/<run>/run-state.json.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = evaluate(args.repo, args.strict, args.state)
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else format_text(result))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
