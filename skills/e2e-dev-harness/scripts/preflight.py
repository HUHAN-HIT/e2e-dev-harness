"""Read-only preflight blocker aggregation for e2e-dev-harness."""

from __future__ import annotations

from pathlib import Path

import agent_scheduler
import dir_graph
import dispatcher
import install_hooks
from common import read_json_object


def resolve_repo_path(repo: Path, path: Path | None) -> Path | None:
    if not path:
        return None
    return path if path.is_absolute() else repo / path


def require_repo_path(repo: Path, path: Path | None, label: str) -> Path:
    resolved = resolve_repo_path(repo, path)
    if resolved is None:
        raise ValueError(f"{label} path is required.")
    repo_root = repo.resolve()
    target = resolved.resolve()
    try:
        target.relative_to(repo_root)
    except ValueError as error:
        raise ValueError(f"{label} path resolves outside repository: {resolved}") from error
    return target


def _runtime_hook_blockers_for_lifecycle(repo: Path, run_state_path: Path | str | None, expected_lifecycle: str) -> list[str]:
    state_file = require_repo_path(repo, Path(str(run_state_path)), "run state") if run_state_path else None
    state_data = read_json_object(state_file) if state_file and state_file.exists() else {}
    lifecycle = str(state_data.get("lifecycle", "")).upper()
    if lifecycle != expected_lifecycle:
        return []

    checked: list[dict] = []
    claude_dir = repo / ".claude"
    if claude_dir.exists():
        checked.append(install_hooks.validate_config(claude_dir / "settings.json", repo))
    opencode_dir = repo / ".opencode"
    if opencode_dir.exists():
        checked.append(install_hooks.validate_config(opencode_dir / "plugins" / "e2e-dev-harness.js", repo))
    if any(item.get("ready") for item in checked):
        return []
    if checked:
        reasons = [
            reason
            for item in checked
            for reason in item.get("blocked_reasons", [])
        ]
        detail = "; ".join(reasons) if reasons else "hook config is present but not ready"
        return [f"Runtime hook config is not ready; run install_hooks.py before dispatching workers. {detail}"]
    return [
        "Runtime hook config is missing; run install_hooks.py before dispatching workers so automatic dispatch can spawn isolated workers."
    ]


def runtime_hook_created_blockers(repo: Path, run_state_path: Path | str | None) -> list[str]:
    return _runtime_hook_blockers_for_lifecycle(repo, run_state_path, "CREATED")


def runtime_hook_service_design_blockers(repo: Path, run_state_path: Path | str | None) -> list[str]:
    return _runtime_hook_blockers_for_lifecycle(repo, run_state_path, "SERVICE_DESIGN_REQUIRED")


def runtime_hook_planned_blockers(repo: Path, run_state_path: Path | str | None) -> list[str]:
    return _runtime_hook_blockers_for_lifecycle(repo, run_state_path, "PLANNED")


def _is_clarification_task(task: dict) -> bool:
    return (
        str(task.get("agent", "")).strip() == "requirements-clarifier"
        or str(task.get("phase", "")).strip().lower() == "clarify"
    )


def _is_mechanical_repair_task(task: dict) -> bool:
    return str(task.get("kind", "")).strip() == "artifact_repair" and _is_clarification_task(task)


def clarification_dispatch_blockers(repo: Path, run_state_path: Path | str | None) -> list[str]:
    state_file = require_repo_path(repo, Path(str(run_state_path)), "run state") if run_state_path else None
    if not state_file or not state_file.exists():
        return [f"Run state not found for clarification dispatch check: {run_state_path}"]
    state_data = read_json_object(state_file)
    if not state_data:
        return [f"Run state is unreadable for clarification dispatch check: {state_file}"]
    if str(state_data.get("lifecycle", "")).upper() != "CREATED":
        return []

    schedule_path = state_file.parent / "agent-schedule.json"
    if not schedule_path.exists():
        return [
            "Clarification gate blocked: CREATED run-state requires completed requirements-clarifier dispatch evidence; "
            "agent-schedule.json is missing beside run-state."
        ]
    schedule = read_json_object(schedule_path)
    if not schedule:
        return [f"Clarification gate blocked: agent schedule is unreadable: {schedule_path}"]

    tasks = [task for task in schedule.get("tasks", []) or [] if isinstance(task, dict)]
    clarifier_tasks = [task for task in tasks if _is_clarification_task(task) and not _is_mechanical_repair_task(task)]
    repair_tasks = [task for task in tasks if _is_mechanical_repair_task(task)]
    if not clarifier_tasks:
        return [
            "Clarification gate blocked: CREATED run-state requires a scheduled requirements-clarifier task."
        ]

    clarifier_blockers = agent_scheduler.dispatch_completion_blockers_for_tasks(
        repo,
        schedule_path,
        state_file,
        clarifier_tasks,
        "Clarification gate blocked",
    ) or []
    if clarifier_blockers:
        return clarifier_blockers
    return agent_scheduler.dispatch_completion_blockers_for_tasks(
        repo,
        schedule_path,
        state_file,
        repair_tasks,
        "Clarification mechanical repair blocked",
    ) or []


def clarification_dispatch_recovery(repo: Path, run_state_path: Path | str | None, blockers: list[str]) -> dict:
    state_file = require_repo_path(repo, Path(str(run_state_path)), "run state") if run_state_path else None
    schedule_path = state_file.parent / "agent-schedule.json" if state_file else repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
    schedule = read_json_object(schedule_path) if schedule_path.exists() else {}
    tasks = [task for task in schedule.get("tasks", []) or [] if isinstance(task, dict)]
    clarifier_tasks = [task for task in tasks if _is_clarification_task(task) and not _is_mechanical_repair_task(task)]
    repair_tasks = [task for task in tasks if _is_mechanical_repair_task(task)]
    primary_incomplete = next(
        (
            item
            for item in clarifier_tasks
            if not agent_scheduler.task_has_dispatch_completion(repo, schedule_path, state_file, item)
        ),
        None,
    )
    repair_incomplete = next(
        (
            item
            for item in repair_tasks
            if not agent_scheduler.task_has_dispatch_completion(repo, schedule_path, state_file, item)
        ),
        None,
    )
    task = primary_incomplete or repair_incomplete or next(
        iter(clarifier_tasks),
        {
            "id": "T01",
            "agent": "requirements-clarifier",
            "outputs": ["docs/agent-runs/<run>/handoffs/01-requirements-clarifier.md"],
        },
    )
    state = read_json_object(state_file) if state_file and state_file.exists() else {}
    dispatch = dispatcher.dispatch_for_task(state, str(task.get("id", "")).strip()) if state else {}
    recovery = dispatcher.dispatch_recovery_packet(repo, schedule_path, state_file, task, dispatch)
    if repair_incomplete and task is repair_incomplete:
        return {
            "ready": False,
            "ready_for_implementation": False,
            "code": "clarification_mechanical_repair_incomplete",
            "blocked_reasons": blockers,
            "clarification_dispatch": {"ready": False, "blocked_reasons": blockers},
            "interaction_required": False,
            "questions_to_ask_user": [],
            "ask_user_requests": [],
            "agent_remediation_required": True,
            "agent_remediation_actions": [
                f"Dispatch mechanical clarification repair task {task.get('id', 'T01b')} before rerunning clarify."
            ],
            "next_agent_action": "dispatch_mechanical_repair",
            **recovery,
        }
    return {
        "ready": False,
        "ready_for_implementation": False,
        "code": "clarification_dispatch_incomplete",
        "blocked_reasons": blockers,
        "clarification_dispatch": {"ready": False, "blocked_reasons": blockers},
        "interaction_required": True,
        "questions_to_ask_user": [
            "Run dispatch-beat --max-workers 1, dispatch-ack the requirements-clarifier worker, and relay its returned Restated Intent/Open Questions first."
        ],
        **recovery,
    }


def service_design_dispatch_blockers(repo: Path, run_state_path: Path | str | None) -> list[str]:
    state_file = require_repo_path(repo, Path(str(run_state_path)), "run state") if run_state_path else None
    if not state_file or not state_file.exists():
        return [f"Run state not found for service-design dispatch check: {run_state_path}"]
    state_data = read_json_object(state_file)
    if not state_data:
        return [f"Run state is unreadable for service-design dispatch check: {state_file}"]
    if str(state_data.get("lifecycle", "")).upper() != "SERVICE_DESIGN_REQUIRED":
        return []

    schedule_path = state_file.parent / "agent-schedule.json"
    if not schedule_path.exists():
        return [
            "Service-design gate blocked: SERVICE_DESIGN_REQUIRED requires dispatcher-confirmed "
            "service-design worker task outputs; agent-schedule.json is missing beside run-state."
        ]
    schedule = read_json_object(schedule_path)
    if not schedule:
        return [f"Service-design gate blocked: agent schedule is unreadable: {schedule_path}"]

    service_design_tasks = agent_scheduler.tasks_with_output_fragments(schedule, ["/service-designs/"])
    if not service_design_tasks:
        return [
            "Service-design gate blocked: SERVICE_DESIGN_REQUIRED requires scheduled service-design worker "
            "tasks that output service-designs/*.md before the main coordinator may transition to PLANNED."
        ]
    return agent_scheduler.dispatch_completion_blockers_for_tasks(
        repo,
        schedule_path,
        state_file,
        service_design_tasks,
        "Service-design gate blocked",
    )


def tdd_red_dispatch_blockers(repo: Path, run_state_path: Path | str | None) -> list[str]:
    state_file = require_repo_path(repo, Path(str(run_state_path)), "run state") if run_state_path else None
    if not state_file or not state_file.exists():
        return [f"Run state not found for TDD-red dispatch check: {run_state_path}"]
    state_data = read_json_object(state_file)
    if not state_data:
        return [f"Run state is unreadable for TDD-red dispatch check: {state_file}"]
    if str(state_data.get("lifecycle", "")).upper() != "PLANNED":
        return []

    services = [str(service) for service in state_data.get("services", []) or []]
    is_multi = str(state_data.get("selected_mode", "")) == "multi" or len(services) > 1
    if not is_multi:
        return []

    schedule_path = state_file.parent / "agent-schedule.json"
    if not schedule_path.exists():
        return [
            "TDD-red gate blocked: multi-service PLANNED run-state requires completed tdd-red and "
            "r2-review dispatch evidence; agent-schedule.json is missing beside run-state."
        ]
    schedule = read_json_object(schedule_path)
    if not schedule:
        return [f"TDD-red gate blocked: agent schedule is unreadable: {schedule_path}"]

    return agent_scheduler.dispatch_completion_blockers_for_phases(
        repo,
        schedule_path,
        state_file,
        schedule,
        ["tdd-red", "r2-review"],
        "TDD-red gate blocked",
    ) or []


def preflight_checks() -> list[dict]:
    return [
        {
            "gate": "dir_graph_contract",
            "code": "BLK_DIR_GRAPH_CONTRACT",
            "return_phase": "CREATED",
            "minimal_fix": "Update .e2e/dir-graph.yaml so directory roles, protected paths, lifecycle transitions, and pipeline match the harness.",
            "fn": dir_graph.dir_graph_contract_blockers,
        },
        {
            "gate": "runtime_hook",
            "code": "BLK_RUNTIME_HOOK",
            "return_phase": "CREATED",
            "minimal_fix": "Run install_hooks.py --runtime claude before dispatch-beat/dispatch-next.",
            "fn": runtime_hook_created_blockers,
        },
        {
            "gate": "clarification",
            "code": "BLK_CLARIFY_DISPATCH",
            "return_phase": "CREATED",
            "minimal_fix": (
                "Run dispatch-beat --max-workers 1 for the requirements-clarifier worker, then relay its "
                "returned Restated Intent/Open Questions."
            ),
            "fn": clarification_dispatch_blockers,
        },
        {
            "gate": "runtime_hook",
            "code": "BLK_RUNTIME_HOOK",
            "return_phase": "SERVICE_DESIGN_REQUIRED",
            "minimal_fix": "Run install_hooks.py --runtime claude before dispatch-beat/dispatch-next.",
            "fn": runtime_hook_service_design_blockers,
        },
        {
            "gate": "service_design",
            "code": "BLK_SVC_DESIGN_DISPATCH",
            "return_phase": "SERVICE_DESIGN_REQUIRED",
            "minimal_fix": (
                "Run dispatch-beat to launch service-design workers that output "
                "service-designs/<service>.md, then validate the returned slices."
            ),
            "fn": service_design_dispatch_blockers,
        },
        {
            "gate": "runtime_hook",
            "code": "BLK_RUNTIME_HOOK",
            "return_phase": "PLANNED",
            "minimal_fix": "Run install_hooks.py --runtime claude before dispatch-beat/dispatch-next.",
            "fn": runtime_hook_planned_blockers,
        },
        {
            "gate": "tdd_red",
            "code": "BLK_TDD_RED_DISPATCH",
            "return_phase": "PLANNED",
            "minimal_fix": (
                "Run dispatch-beat/dispatch-complete for the scheduled tdd-red and r2-review "
                "workers so their worker_completed dispatch events exist before the implementation gate."
            ),
            "fn": tdd_red_dispatch_blockers,
        },
    ]


def _minimal_fix_for_blocker(check: dict, message: str) -> str:
    if check.get("code") == "BLK_CLARIFY_DISPATCH" and "mechanical repair" in message.lower():
        task_id = "T01b"
        marker = "task "
        if marker in message:
            tail = message.split(marker, 1)[1].strip()
            candidate = tail.split(" ", 1)[0].strip()
            if candidate:
                task_id = candidate
        return (
            f"Run dispatch-beat --max-workers 1 for mechanical clarification repair task {task_id}, "
            "then dispatch-complete it and rerun clarify."
        )
    return str(check["minimal_fix"])


def aggregate_preflight_blockers(repo: Path, run_state_path: Path | str | None) -> dict:
    blockers: list[dict] = []
    for check in preflight_checks():
        for message in check["fn"](repo, run_state_path) or []:
            minimal_fix = _minimal_fix_for_blocker(check, message)
            blockers.append(
                {
                    "order": len(blockers) + 1,
                    "gate": check["gate"],
                    "code": check["code"],
                    "return_phase": check["return_phase"],
                    "message": message,
                    "minimal_fix": minimal_fix,
                }
            )
    return {
        "schema": "e2e-dev-harness.preflight.v1",
        "ready": not blockers,
        "blockers": blockers,
        "next_single_action": blockers[0]["minimal_fix"] if blockers else "",
    }
