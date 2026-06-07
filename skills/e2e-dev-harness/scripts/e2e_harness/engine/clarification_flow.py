"""Clarification-stage transaction controller."""

from __future__ import annotations

from pathlib import Path

import agent_scheduler
import clarification_gate
import dispatcher
import preflight as preflight_checks
import run_state as run_state_module
from common import posix, read_json_object
from e2e_harness.cli.commands import handoff as handoff_command
from e2e_harness.cli.status import write_status
from e2e_harness.engine import control_plane, state_store


def _as_repo(path: Path) -> Path:
    return Path(path).resolve()


def _resolve_repo_path(repo: Path, path: Path | None) -> Path | None:
    if path is None:
        return None
    return path if path.is_absolute() else repo / path


def _repo_relative(repo: Path, path: Path) -> str:
    target = path if path.is_absolute() else repo / path
    try:
        return posix(target.resolve().relative_to(repo.resolve()))
    except ValueError:
        return posix(target)


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


def _next_repair_task_id(tasks: list[dict]) -> str:
    existing = {str(task.get("id", "")).strip() for task in tasks}
    for suffix in ("b", "c", "d", "e", "f", "g", "h"):
        candidate = f"T01{suffix}"
        if candidate not in existing:
            return candidate
    index = 2
    while True:
        candidate = f"T01-repair-{index}"
        if candidate not in existing:
            return candidate
        index += 1


def _task_targets(task: dict) -> set[str]:
    targets: set[str] = set()
    for key in ("repair_targets", "outputs", "inputs"):
        for item in task.get(key, []) or []:
            text = str(item).strip()
            if text:
                targets.add(posix(text))
    return targets


def _matching_repair_task(tasks: list[dict], target: str, code: str) -> dict | None:
    normalized_target = posix(target)
    for task in tasks:
        if str(task.get("kind", "")).strip() != "artifact_repair":
            continue
        if str(task.get("repair_code", "")).strip() and str(task.get("repair_code", "")).strip() != code:
            continue
        if normalized_target in _task_targets(task):
            return task
    return None


def _mechanical_repair_next_required(schedule_path: Path, task_id: str) -> dict:
    return {
        "phase": "clarification_repair",
        "command": (
            f"Run dispatch-beat --schedule {posix(schedule_path)} --max-workers 1, use the generated "
            f"{task_id} spawn request/prompt for the isolated requirements-clarifier worker, then dispatch-complete "
            f"{task_id} after it updates the scheduled artifact. Do not call Agent directly before dispatch-beat."
        ),
        "code_writes_allowed": False,
    }


def _design_outline_next_required() -> dict:
    return {
        "phase": "clarification_repair",
        "gate": "design_outline",
        "command": "Run a requirements-clarifier design-outline repair worker before plan/archive or R1 review.",
        "code_writes_allowed": False,
    }


def _plan_next_required() -> dict:
    return {
        "phase": "plan",
        "gate": "design_outline",
        "command": "Run e2e_dev_harness.py next, then e2e_dev_harness.py plan --create-archive before any code write.",
        "code_writes_allowed": False,
    }


def _readiness_next_required(result: dict) -> dict:
    if not result.get("design_outline_ready", False):
        return _design_outline_next_required()
    repair = result.get("mechanical_repair_dispatch")
    if isinstance(repair, dict) and repair.get("next_required"):
        next_required = dict(repair["next_required"])
        next_required.setdefault("gate", "mechanical_repair")
        return next_required
    return _plan_next_required()


def _ensure_artifact_repair_tasks(
    repo: Path,
    run_state: Path | None,
    target: Path,
    repair_specs: list[dict],
) -> dict:
    if not run_state or not repair_specs:
        return {}
    state_path = _resolve_repo_path(repo, run_state)
    if not state_path or not state_path.exists():
        return {}
    schedule_path = state_path.parent / "agent-schedule.json"
    if not schedule_path.exists():
        return {}
    schedule = read_json_object(schedule_path)
    tasks = [task for task in schedule.get("tasks", []) or [] if isinstance(task, dict)]
    target_ref = _repo_relative(repo, target)
    added: list[dict] = []
    pending: list[dict] = []
    transactions: list[dict] = []
    for spec in repair_specs:
        code = str(spec.get("code", "")).strip() or "mechanical_repair"
        existing = _matching_repair_task(tasks, target_ref, code)
        if existing:
            pending.append(existing)
            transactions.append(
                {
                    "status": "already_open",
                    "task_id": str(existing.get("id", "")),
                    "transaction_id": str(existing.get("repair_transaction_id", "")),
                }
            )
            continue
        opened = control_plane.open_repair_transaction(
            repo,
            schedule_path.parent,
            code=code,
            target=target_ref,
            section=str(spec.get("section", "Impact Summary")),
            objective=str(spec.get("objective", "Apply the scheduled mechanical clarification repair.")),
            constraints=spec.get("constraints", []) or [],
        )
        if not opened.get("ready"):
            continue
        transactions.append(opened)
        schedule = read_json_object(schedule_path)
        tasks = [task for task in schedule.get("tasks", []) or [] if isinstance(task, dict)]
        task_id = str(opened.get("task_id", ""))
        task = next((item for item in tasks if str(item.get("id", "")) == task_id), opened.get("task", {}))
        if opened.get("status") == "opened":
            added.append(task)
        pending.append(task)
    primary = pending[0] if pending else {}
    task_id = str(primary.get("id", "")).strip()
    return {
        "ready": bool(pending),
        "schedule": posix(schedule_path),
        "repair_transactions": transactions,
        "active_repair_transaction": transactions[0] if transactions else {},
        "added_tasks": [{"id": str(task.get("id", "")), "repair_targets": task.get("repair_targets", [])} for task in added],
        "pending_tasks": [
            {"id": str(task.get("id", "")), "repair_targets": task.get("repair_targets", [])}
            for task in pending
            if str(task.get("status", "")).strip().lower() != "completed"
        ],
        "next_required": _mechanical_repair_next_required(schedule_path, task_id) if task_id else {},
    }


def _ensure_mechanical_repair_tasks(repo: Path, run_state: Path | None, design_path: Path, result: dict) -> dict:
    all_specs = [item for item in result.get("mechanical_remediation_tasks", []) or [] if isinstance(item, dict)]
    inline_specs = [s for s in all_specs if s.get("inline_allowed")]
    dispatch_specs = [s for s in all_specs if not s.get("inline_allowed")]
    dispatch = _ensure_artifact_repair_tasks(repo, run_state, design_path, dispatch_specs)
    if inline_specs:
        dispatch = dict(dispatch)
        dispatch["inline_tasks"] = [
            {
                "code": s.get("code"),
                "section": s.get("section"),
                "target": str(design_path),
                "objective": s.get("objective"),
                "repair_class": "format",
            }
            for s in inline_specs
        ]
    return dispatch


def _ensure_handoff_repair_task(repo: Path, run_state: Path | None, target: Path, seal_result: dict) -> dict:
    codes = seal_result.get("blocker_codes", []) or ["ready_handoff_artifact_repair"]
    code = str(codes[0] or "ready_handoff_artifact_repair")
    return _ensure_artifact_repair_tasks(
        repo,
        run_state,
        target,
        [
            {
                "code": code,
                "section": "Ready Handoff",
                "objective": "Repair the ready handoff artifact without coordinator-authored markdown rewrites.",
                "constraints": [
                    "Do not change user-confirmed requirement decisions.",
                    "Update only the scheduled handoff artifact and its canonical ready marker.",
                ],
            }
        ],
    )


def _seal_clarifier_handoffs(repo: Path, run_state: Path | None, schedule_path: Path, state_path: Path, task: dict) -> dict:
    agent = str(task.get("agent", "")).strip() or "requirements-clarifier"
    for item in task.get("outputs", []) or []:
        text = str(item).strip()
        if not text:
            continue
        normalized = text.replace("\\", "/")
        if "/handoffs/" not in normalized or not normalized.endswith(".md"):
            continue
        resolved = Path(text)
        resolved = resolved if resolved.is_absolute() else repo / resolved
        if not resolved.is_file():
            continue
        seal = handoff_command.run_marker_only_seal(repo, resolved, agent)
        if not seal.get("ready"):
            seal["coordinator_action"] = dispatcher.coordinator_worker_only_action(
                repo,
                schedule_path,
                state_path,
                task,
                required_action="artifact_repair",
                evidence=[text],
            )
            seal["next_required"] = seal["coordinator_action"]["next_required"]
            repair_dispatch = _ensure_handoff_repair_task(repo, run_state, resolved, seal)
            if repair_dispatch:
                seal["mechanical_repair_dispatch"] = repair_dispatch
            return seal
    return {}


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
    seal_blocker = _seal_clarifier_handoffs(repo, run_state, schedule_path, state_path, task)
    if seal_blocker:
        return seal_blocker
    return dispatcher.dispatch_complete(repo, schedule_path, state_path, task_id, agent, evidence)


def _with_stage(result: dict, stage: str) -> dict:
    result.setdefault("clarification_transaction", {})["stage"] = stage
    return result


def _record_clarification_gate_snapshot(repo: Path, run_state: Path | None, result: dict) -> None:
    state_path = _resolve_repo_path(repo, run_state)
    if not state_path or not state_path.exists():
        return
    state = read_json_object(state_path)
    transition = result.get("run_state_transition") if isinstance(result.get("run_state_transition"), dict) else {}
    if transition.get("lifecycle"):
        state["lifecycle"] = transition["lifecycle"]
    state.setdefault("gate_snapshots", {})["clarification"] = {
        "schema": "e2e-dev-harness.clarification-readiness-snapshot.v1",
        "ready_for_implementation": result.get("ready_for_implementation", False),
        "user_clarification_ready": result.get("user_clarification_ready", False),
        "design_outline_ready": result.get("design_outline_ready", False),
        "implementation_evidence_ready": result.get("implementation_evidence_ready", False),
        "mechanical_repair_ready": result.get("mechanical_repair_ready", False),
        "readiness": result.get("readiness", {}),
        "next_required": result.get("next_required", {}),
    }
    run_state_module.write_state(repo, state_path, state)


def _primary_clarification_dispatch_blockers(repo: Path, run_state: Path | None) -> list[str]:
    blockers = preflight_checks.clarification_dispatch_blockers(repo, run_state)
    return [reason for reason in blockers if "mechanical repair" not in str(reason).lower()]


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
        dispatch_blockers = _primary_clarification_dispatch_blockers(repo, run_state)
        if dispatch_blockers:
            result = preflight_checks.clarification_dispatch_recovery(repo, run_state, dispatch_blockers)
            _with_stage(result, "primary_completion")
            if auto_complete:
                result["clarification_dispatch_auto_complete"] = auto_complete
            write_status(status_file, result)
            return 2, result

    tier = "standard"
    if run_state:
        _state_path = _resolve_repo_path(repo, run_state)
        if _state_path and _state_path.exists():
            tier = run_state_module.workflow_tier(read_json_object(_state_path))

    result = clarification_gate.validate(
        design_path,
        require_intent=require_intent,
        require_user_confirmation=require_user_confirmation,
        tier=tier,
    )
    _with_stage(result, "validation")
    repair_dispatch = _ensure_mechanical_repair_tasks(repo, run_state, design_path, result)
    if repair_dispatch and repair_dispatch.get("pending_tasks") and not result.get("interaction_required"):
        result["mechanical_repair_dispatch"] = repair_dispatch
        result["agent_remediation_required"] = True
        result["next_agent_action"] = "dispatch_mechanical_repair"
        contract = result.get("interaction_contract")
        if isinstance(contract, dict):
            contract["agent_remediation_required"] = True
            contract["next_agent_action"] = "dispatch_mechanical_repair"
            contract["mechanical_repair_dispatch"] = repair_dispatch

    if run_state and result.get("user_clarification_ready"):
        dispatch_blockers = _primary_clarification_dispatch_blockers(repo, run_state)
        if dispatch_blockers:
            _with_stage(result, "repair_barrier")
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

    if run_state and result.get("user_clarification_ready"):
        _with_stage(result, "transition")
        result["run_state_transition"] = state_store.transition_lifecycle(
            repo,
            run_state,
            "CLARIFIED",
            gate="clarification",
            gate_status="passed",
            evidence=design_path,
        )
        result["blocked_next_without_plan"] = result.get("design_outline_ready", False)
        result["next_required"] = _readiness_next_required(result)
        _record_clarification_gate_snapshot(repo, run_state, result)
    if auto_complete:
        result["clarification_dispatch_auto_complete"] = auto_complete
    write_status(status_file, result)
    return (0 if (run_state and result.get("user_clarification_ready")) or result["ready_for_implementation"] else 2), result
