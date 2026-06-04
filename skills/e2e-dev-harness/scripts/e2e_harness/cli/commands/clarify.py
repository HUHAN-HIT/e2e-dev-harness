"""Clarification command facade."""

from __future__ import annotations

from pathlib import Path

import agent_scheduler
import clarification_gate
import dispatcher
import preflight as preflight_checks
from common import read_json_object
from e2e_harness.cli.status import write_status
from e2e_harness.engine import state_store


def _as_repo(path: Path) -> Path:
    return Path(path).resolve()


def _resolve_repo_path(repo: Path, path: Path | None) -> Path | None:
    if path is None:
        return None
    return path if path.is_absolute() else repo / path


def _existing_task_outputs(repo: Path, task: dict) -> list[str]:
    outputs: list[str] = []
    for item in task.get("outputs", []) or []:
        text = str(item).strip()
        if not text:
            continue
        path = Path(text)
        resolved = path if path.is_absolute() else repo / path
        if resolved.exists():
            outputs.append(text)
    return outputs


def _auto_complete_single_requirements_clarifier(repo: Path, run_state: Path | None) -> dict:
    state_path = _resolve_repo_path(repo, run_state)
    if not state_path or not state_path.exists():
        return {}
    state = read_json_object(state_path)
    if str(state.get("lifecycle", "")).strip().upper() != "CREATED":
        return {}
    schedule_path = state_path.parent / "agent-schedule.json"
    if not schedule_path.exists():
        return {}
    schedule = read_json_object(schedule_path)
    tasks = [task for task in schedule.get("tasks", []) or [] if isinstance(task, dict)]
    clarifier_tasks = [
        task
        for task in tasks
        if str(task.get("agent", "")).strip() == "requirements-clarifier"
        or str(task.get("phase", "")).strip().lower() == "clarify"
    ]
    if len(clarifier_tasks) != 1:
        return {}
    task = clarifier_tasks[0]
    if agent_scheduler.task_has_dispatch_completion(repo, schedule_path, state_path, task):
        return {}
    task_id = str(task.get("id", "")).strip()
    agent = str(task.get("agent", "")).strip() or "requirements-clarifier"
    dispatch = dispatcher.dispatch_for_task(state, task_id)
    if str(dispatch.get("status", "")).strip() != "worker_running":
        return {}
    evidence = _existing_task_outputs(repo, task)
    if not task_id or not evidence:
        return {}
    return dispatcher.dispatch_complete(repo, schedule_path, state_path, task_id, agent, evidence)


def run(
    repo: Path,
    design_doc: Path,
    run_state: Path | None = None,
    require_intent: bool = True,
    require_user_confirmation: bool = True,
    status_file: Path | None = None,
) -> tuple[int, dict]:
    repo = _as_repo(repo)
    design_path = _resolve_repo_path(repo, design_doc)
    if not design_path or not design_path.exists():
        return 2, {"ready_for_implementation": False, "error": f"Design doc not found: {design_path}"}
    auto_complete = _auto_complete_single_requirements_clarifier(repo, run_state) if run_state else {}
    if run_state:
        dispatch_blockers = preflight_checks.clarification_dispatch_blockers(repo, run_state)
        if dispatch_blockers:
            result = preflight_checks.clarification_dispatch_recovery(repo, run_state, dispatch_blockers)
            if auto_complete:
                result["clarification_dispatch_auto_complete"] = auto_complete
            write_status(status_file, result)
            return 2, result
    result = clarification_gate.validate(
        design_path,
        require_intent=require_intent,
        require_user_confirmation=require_user_confirmation,
    )
    if run_state and result.get("ready_for_implementation"):
        dispatch_blockers = preflight_checks.clarification_dispatch_blockers(repo, run_state)
        if dispatch_blockers:
            result["ready_for_implementation"] = False
            result.setdefault("blocked_reasons", []).extend(dispatch_blockers)
            result["clarification_dispatch"] = {"ready": False, "blocked_reasons": dispatch_blockers}
            if auto_complete:
                result["clarification_dispatch_auto_complete"] = auto_complete
            result["interaction_required"] = True
            result["questions_to_ask_user"] = [
                "Run dispatch-beat --max-workers 1 for requirements-clarifier and relay its returned Restated Intent/Open Questions first."
            ]
            write_status(status_file, result)
            return 2, result
    if run_state and result.get("ready_for_implementation"):
        result["run_state_transition"] = state_store.transition_lifecycle(
            repo,
            run_state,
            "CLARIFIED",
            gate="clarification",
            gate_status="passed",
            evidence=design_path,
        )
        result["blocked_next_without_plan"] = True
        result["next_required"] = {
            "phase": "plan",
            "command": "Run e2e_dev_harness.py next, then e2e_dev_harness.py plan --create-archive before any code write.",
            "code_writes_allowed": False,
        }
    if auto_complete:
        result["clarification_dispatch_auto_complete"] = auto_complete
    write_status(status_file, result)
    return (0 if result["ready_for_implementation"] else 2), result


def run_from_args(args) -> tuple[int, dict]:
    return run(
        getattr(args, "repo"),
        getattr(args, "design_doc"),
        run_state=getattr(args, "run_state", None),
        require_intent=getattr(args, "require_intent", True),
        require_user_confirmation=getattr(args, "require_user_confirmation", True),
        status_file=getattr(args, "status_file", None),
    )
