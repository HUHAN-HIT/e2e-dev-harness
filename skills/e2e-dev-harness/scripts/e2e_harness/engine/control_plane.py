"""Single authoritative control-plane state for harness runs."""

from __future__ import annotations

from pathlib import Path

import agent_roles
from common import atomic_write_json, now_iso, posix, read_json_object
from e2e_harness.domain.control_plane_models import default_control_plane


CONTROL_PLANE_FILE = "control-plane.json"


def control_plane_path(run_dir: Path) -> Path:
    return run_dir / CONTROL_PLANE_FILE


def _resolve(repo: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo / path


def _projection_entry(source: str) -> dict:
    return {
        "mode": "compat",
        "source": source,
        "authoritative": False,
    }


def _role_template_key(agent: str) -> str:
    return agent_roles.resolve_role_key(agent)


def _normalize_task(task: dict) -> dict:
    copy = dict(task)
    agent = str(copy.get("agent", "")).strip()
    phase = str(copy.get("phase", "")).strip()
    role_key = str(copy.get("role_template_key", "")).strip() or _role_template_key(agent)
    if role_key:
        copy.setdefault("role_template_key", role_key)
    copy.setdefault("role_group", agent_roles.phase_role_group(phase) or "coordination")
    copy.setdefault("runtime_subagent_type", agent_roles.phase_runtime_subagent_type(phase) or agent)
    copy.setdefault("parallel_group", phase or "coordination")
    copy.setdefault("depends_on_phases", agent_roles.depends_on_for_phase(phase))
    copy.setdefault("requires_runtime_dispatch", True)
    copy.setdefault("dispatch_contract", "fresh-subagent")
    copy.setdefault("status", "planned")
    copy.setdefault("inputs", [])
    copy.setdefault("outputs", [])
    return copy


def task_contract(
    task_id: str,
    agent: str,
    phase: str,
    kind: str = "",
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    repair_targets: list[str] | None = None,
    **extra,
) -> dict:
    role_key = str(extra.get("role_template_key", "")).strip() or _role_template_key(agent)
    service = str(extra.get("service", "") or "")
    parallel_group = str(extra.get("parallel_group", "") or "")
    if not parallel_group:
        parallel_group = f"service:{service}" if service and phase in {"tdd-red", "implement", "r3-review"} else phase
    task = {
        "id": task_id,
        "agent": agent,
        "phase": phase,
        "role_group": str(extra.get("role_group", "") or agent_roles.phase_role_group(phase) or "coordination"),
        "role_template": str(extra.get("role_template", "") or ""),
        "role_template_key": role_key,
        "service": service,
        "parallel_group": parallel_group,
        "depends_on_phases": list(extra.get("depends_on_phases", agent_roles.depends_on_for_phase(phase)) or []),
        "inputs": list(inputs or extra.get("inputs", []) or []),
        "outputs": list(outputs or extra.get("outputs", []) or []),
        "status": str(extra.get("status", "planned") or "planned"),
        "requires_runtime_dispatch": bool(extra.get("requires_runtime_dispatch", True)),
        "dispatch_contract": str(extra.get("dispatch_contract", "fresh-subagent") or "fresh-subagent"),
        "runtime_subagent_type": str(
            extra.get("runtime_subagent_type", "") or agent_roles.phase_runtime_subagent_type(phase) or agent
        ),
    }
    if kind:
        task["kind"] = kind
    if kind == "artifact_repair":
        task["repair_targets"] = list(repair_targets or extra.get("repair_targets", []) or [])
        if "repair_code" in extra:
            task["repair_code"] = extra["repair_code"]
        if "repair_section" in extra:
            task["repair_section"] = extra["repair_section"]
    return task


def load(repo: Path, run_dir: Path) -> dict:
    path = control_plane_path(_resolve(repo, run_dir))
    return read_json_object(path)


def _schedule_projection(data: dict) -> dict:
    schedule = data.get("schedule") if isinstance(data.get("schedule"), dict) else {}
    return {
        "schema": "e2e-dev-harness.agent-schedule.v1",
        "source": CONTROL_PLANE_FILE,
        "mode": schedule.get("mode", ""),
        "completion_mode": schedule.get("completion_mode", "dispatcher-confirmed"),
        "max_workers": schedule.get("max_workers", ""),
        "tasks": list(data.get("tasks", []) or []),
    }


def _run_state_projection(data: dict) -> dict:
    return {
        "schema": "e2e-dev-harness.run-state.v1",
        "source": CONTROL_PLANE_FILE,
        "run_id": data.get("run_id", ""),
        "lifecycle": data.get("lifecycle", "CREATED"),
        "gates": data.get("gates", {}),
        "dispatches": data.get("dispatches", {}),
        "dispatch": data.get("dispatch", {}),
        "history": data.get("history", []),
        "artifact_registry": data.get("artifact_registry", ""),
    }


def _phase_lock_projection(data: dict) -> dict:
    projection = dict(data.get("phase_lock", {})) if isinstance(data.get("phase_lock"), dict) else {}
    projection.setdefault("schema", "e2e-dev-harness.phase-lock.v1")
    projection["source"] = CONTROL_PLANE_FILE
    projection["lifecycle"] = data.get("lifecycle", projection.get("lifecycle", "CREATED"))
    return projection


def _coordinator_projection(data: dict) -> dict:
    coordinator = data.get("coordinator") if isinstance(data.get("coordinator"), dict) else {}
    summary = dict(coordinator.get("summary", {})) if isinstance(coordinator.get("summary"), dict) else {}
    summary["source"] = CONTROL_PLANE_FILE
    summary.setdefault("run_id", data.get("run_id", ""))
    summary.setdefault("lifecycle", data.get("lifecycle", "CREATED"))
    return summary


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


def _transaction_id(code: str, target: str) -> str:
    cleaned = "".join(char if char.isalnum() else "-" for char in f"{code}-{target}".lower())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "repair"


def _active_transaction(transaction: dict) -> bool:
    return str(transaction.get("status", "")).strip() in {"opened", "dispatched", "worker_running", "evidence_validated"}


def create(repo: Path, run_dir: Path, run_id: str) -> dict:
    path = control_plane_path(run_dir if run_dir.is_absolute() else repo / run_dir)
    data = default_control_plane(run_id)
    atomic_write_json(path, data)
    return {
        "ready": True,
        "control_plane_path": posix(path),
        "run_id": run_id,
    }


def import_legacy(repo: Path, run_dir: Path) -> dict:
    resolved_run_dir = _resolve(repo, run_dir)
    run_state = read_json_object(resolved_run_dir / "run-state.json")
    schedule = read_json_object(resolved_run_dir / "agent-schedule.json")
    phase_lock = read_json_object(resolved_run_dir / ".phase-lock")
    coordinator = read_json_object(resolved_run_dir / "coordinator-summary.json")

    run_id = str(run_state.get("run_id", "") or posix(run_dir))
    data = default_control_plane(run_id)
    lifecycle = str(run_state.get("lifecycle", "") or "CREATED")
    data["lifecycle"] = lifecycle
    data["gates"] = dict(run_state.get("gates", {})) if isinstance(run_state.get("gates"), dict) else {}
    data["dispatches"] = dict(run_state.get("dispatches", {})) if isinstance(run_state.get("dispatches"), dict) else {}
    data["history"] = list(run_state.get("history", [])) if isinstance(run_state.get("history"), list) else []

    tasks = schedule.get("tasks", []) if isinstance(schedule.get("tasks"), list) else []
    data["tasks"] = [_normalize_task(task) for task in tasks if isinstance(task, dict)]
    data["schedule"] = {
        "mode": str(schedule.get("mode", "")),
        "completion_mode": str(schedule.get("completion_mode", "")),
        "max_workers": schedule.get("max_workers", ""),
    }

    diagnostics: list[dict] = []
    if phase_lock:
        lock_lifecycle = str(phase_lock.get("lifecycle", "")).strip()
        if not lock_lifecycle or lock_lifecycle == lifecycle:
            data["phase_lock"].update(phase_lock)
        else:
            diagnostics.append(
                {
                    "code": "phase_lock_lifecycle_mismatch",
                    "run_state_lifecycle": lifecycle,
                    "phase_lock_lifecycle": lock_lifecycle,
                    "severity": "blocking",
                }
            )
    data["phase_lock"]["lifecycle"] = lifecycle

    data["coordinator"] = {
        "projection_source": "coordinator-summary.json",
        "summary": coordinator,
    }
    data["projections"] = {
        "run-state.json": _projection_entry("run-state.json"),
        "agent-schedule.json": _projection_entry("agent-schedule.json"),
        ".phase-lock": _projection_entry(".phase-lock"),
        "coordinator-summary.json": _projection_entry("coordinator-summary.json"),
    }
    if diagnostics:
        data["diagnostics"] = diagnostics

    path = control_plane_path(resolved_run_dir)
    atomic_write_json(path, data)
    blocking = [item for item in diagnostics if item.get("severity") == "blocking"]
    return {
        "ready": not blocking,
        "control_plane_path": posix(path),
        "diagnostics": diagnostics,
    }


def write_legacy_projections(repo: Path, run_dir: Path) -> dict:
    resolved_run_dir = _resolve(repo, run_dir)
    path = control_plane_path(resolved_run_dir)
    data = read_json_object(path)
    if not data:
        return {
            "ready": False,
            "blocked_reasons": [f"Missing {CONTROL_PLANE_FILE} at {posix(path)}."],
        }

    projections = {
        "run-state.json": _run_state_projection(data),
        "agent-schedule.json": _schedule_projection(data),
        ".phase-lock": _phase_lock_projection(data),
        "coordinator-summary.json": _coordinator_projection(data),
    }
    for name, projection in projections.items():
        atomic_write_json(resolved_run_dir / name, projection)

    data["projections"] = {
        name: {
            "mode": "compat",
            "source": CONTROL_PLANE_FILE,
            "path": posix(resolved_run_dir / name),
            "authoritative": False,
        }
        for name in projections
    }
    atomic_write_json(path, data)
    return {
        "ready": True,
        "control_plane_path": posix(path),
        "projections": data["projections"],
    }


def repair(repo: Path, run_dir: Path, scope: str) -> dict:
    resolved_run_dir = _resolve(repo, run_dir)
    selected = str(scope or "").strip()
    if selected not in {"task-contracts", "projections", "legacy-import"}:
        return {
            "ready": False,
            "blocked_reasons": [f"Unsupported control-plane repair scope: {selected or '<missing>'}."],
            "allowed_scopes": ["task-contracts", "projections", "legacy-import"],
        }

    if selected == "legacy-import":
        imported = import_legacy(repo, resolved_run_dir)
        if not imported.get("ready"):
            imported["scopes"] = [selected]
            return imported
        projection = write_legacy_projections(repo, resolved_run_dir)
        return {
            **projection,
            "ready": bool(projection.get("ready")),
            "scopes": [selected],
            "imported": imported,
        }

    if selected == "projections":
        projection = write_legacy_projections(repo, resolved_run_dir)
        return {**projection, "scopes": [selected]}

    path = control_plane_path(resolved_run_dir)
    if not path.exists():
        imported = import_legacy(repo, resolved_run_dir)
        if not imported.get("ready"):
            imported["scopes"] = [selected]
            return imported

    data = read_json_object(path)
    if not data:
        return {
            "ready": False,
            "blocked_reasons": [f"Missing {CONTROL_PLANE_FILE} at {posix(path)}."],
            "scopes": [selected],
        }
    tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
    normalized = [_normalize_task(task) for task in tasks if isinstance(task, dict)]
    changed = normalized != tasks
    data["tasks"] = normalized
    atomic_write_json(path, data)
    projection = write_legacy_projections(repo, resolved_run_dir)
    return {
        **projection,
        "ready": bool(projection.get("ready")),
        "scopes": [selected],
        "tasks_repaired": len(normalized),
        "changed": changed,
    }


def open_repair_transaction(
    repo: Path,
    run_dir: Path,
    code: str,
    target: str,
    section: str = "Impact Summary",
    objective: str = "Apply the scheduled mechanical clarification repair.",
    constraints: list[str] | None = None,
) -> dict:
    resolved_run_dir = _resolve(repo, run_dir)
    path = control_plane_path(resolved_run_dir)
    if not path.exists():
        imported = import_legacy(repo, resolved_run_dir)
        if not imported.get("ready"):
            return imported
    data = read_json_object(path)
    if not data:
        data = default_control_plane(posix(run_dir))

    repair_code = str(code or "mechanical_repair").strip()
    repair_target = posix(str(target or "").strip())
    transactions = data.get("repair_transactions") if isinstance(data.get("repair_transactions"), dict) else {}
    for transaction in transactions.values():
        if not isinstance(transaction, dict) or not _active_transaction(transaction):
            continue
        if transaction.get("repair_code") == repair_code and transaction.get("target") == repair_target:
            return {
                "ready": True,
                "status": "already_open",
                "transaction_id": transaction.get("id", ""),
                "task_id": transaction.get("task_id", ""),
            }

    tasks = [task for task in data.get("tasks", []) or [] if isinstance(task, dict)]
    task_id = _next_repair_task_id(tasks)
    transaction_id = _transaction_id(repair_code, repair_target)
    base_task = next(
        (
            item
            for item in tasks
            if str(item.get("agent", "")).strip() == "requirements-clarifier"
            and str(item.get("role_template", "")).strip()
        ),
        {},
    )
    role_template = str(base_task.get("role_template", "")).strip()
    if not role_template:
        default_role_template = resolved_run_dir / "agent-roles" / "requirements-clarifier.md"
        if default_role_template.exists():
            try:
                role_template = posix(default_role_template.resolve().relative_to(repo.resolve()))
            except ValueError:
                role_template = posix(default_role_template)
    task = task_contract(
        task_id=task_id,
        agent="requirements-clarifier",
        phase="clarify",
        kind="artifact_repair",
        inputs=[repair_target],
        outputs=[repair_target],
        repair_targets=[repair_target],
        parallel_group="clarification-repair",
        repair_code=repair_code,
        repair_section=section,
        objective=objective,
        constraints=constraints or [],
        role_template=role_template,
        role_template_key=base_task.get("role_template_key", ""),
    )
    task["repair_transaction_id"] = transaction_id
    task["completion_checks"] = [
        f"{section} satisfies clarification gate policy.",
        "Only scheduled artifact repair targets were edited.",
        "No user-confirmed requirement decisions were changed.",
    ]
    tasks.append(task)
    transactions[transaction_id] = {
        "id": transaction_id,
        "repair_code": repair_code,
        "target": repair_target,
        "status": "opened",
        "task_id": task_id,
        "opened_at": now_iso(),
    }
    data["tasks"] = tasks
    data["repair_transactions"] = transactions
    atomic_write_json(path, data)
    projection = write_legacy_projections(repo, resolved_run_dir)
    return {
        "ready": bool(projection.get("ready")),
        "status": "opened",
        "transaction_id": transaction_id,
        "task_id": task_id,
        "task": task,
    }


def dispatch_acknowledged(repo: Path, run_dir: Path, dispatch: dict) -> dict:
    resolved_run_dir = _resolve(repo, run_dir)
    path = control_plane_path(resolved_run_dir)
    data = read_json_object(path)
    if not data:
        return {"ready": False, "blocked_reasons": [f"Missing {CONTROL_PLANE_FILE} at {posix(path)}."]}
    task_id = str(dispatch.get("current_task_id", "") or dispatch.get("task_id", "")).strip()
    if not task_id:
        return {"ready": False, "blocked_reasons": ["Dispatch task id is required."]}
    dispatches = data.get("dispatches") if isinstance(data.get("dispatches"), dict) else {}
    dispatches[task_id] = dict(dispatch)
    data["dispatches"] = dispatches
    data["dispatch"] = dict(dispatch)
    atomic_write_json(path, data)
    projection = write_legacy_projections(repo, resolved_run_dir)
    return {"ready": bool(projection.get("ready")), "dispatch": dispatches[task_id]}


def dispatch_completed(repo: Path, run_dir: Path, task_id: str, agent: str, evidence: list[str] | None = None) -> dict:
    resolved_run_dir = _resolve(repo, run_dir)
    path = control_plane_path(resolved_run_dir)
    data = read_json_object(path)
    if not data:
        return {"ready": False, "blocked_reasons": [f"Missing {CONTROL_PLANE_FILE} at {posix(path)}."]}
    task_key = str(task_id).strip()
    dispatches = data.get("dispatches") if isinstance(data.get("dispatches"), dict) else {}
    current = dict(dispatches.get(task_key, {})) if isinstance(dispatches.get(task_key), dict) else {}
    current.update(
        {
            "current_task_id": task_key,
            "current_agent": agent,
            "agent": agent,
            "status": "worker_completed",
            "evidence": list(evidence or []),
        }
    )
    dispatches[task_key] = current
    data["dispatches"] = dispatches
    data["dispatch"] = current
    for task in data.get("tasks", []) or []:
        if isinstance(task, dict) and str(task.get("id", "")).strip() == task_key:
            task["status"] = "completed"
            if evidence:
                task["evidence"] = list(evidence)
    transactions = data.get("repair_transactions") if isinstance(data.get("repair_transactions"), dict) else {}
    for transaction in transactions.values():
        if isinstance(transaction, dict) and str(transaction.get("task_id", "")).strip() == task_key:
            transaction["status"] = "closed"
            transaction["closed_at"] = now_iso()
    data["repair_transactions"] = transactions
    atomic_write_json(path, data)
    projection = write_legacy_projections(repo, resolved_run_dir)
    return {"ready": bool(projection.get("ready")), "dispatch": current}
