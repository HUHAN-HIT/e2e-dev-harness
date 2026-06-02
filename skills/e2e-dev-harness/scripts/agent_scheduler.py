#!/usr/bin/env python3
"""Claim and complete machine-readable agent schedule tasks."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_state  # noqa: E402
import handoff_gate  # noqa: E402
from common import atomic_write_json, now_iso  # noqa: E402


CLAIMED_STATUSES = {"claimed", "in-progress", "in_progress", "completed"}
# Statuses that hold a task without finishing it; a stale hold can be reclaimed.
HELD_STATUSES = {"claimed", "in-progress", "in_progress"}
DEFAULT_LEASE_SECONDS = 1800
DISPATCHER_CONFIRMED_COMPLETION = "dispatcher-confirmed"
EXCLUSIVE_ROLE_GROUPS = {"design", "planning", "test", "code", "review", "coverage"}
ROLE_TEMPLATE_MARKERS = ("## Role Boundary", "## Allowed Inputs", "## Forbidden", "## Required Outputs", "## Done When")
PHASE_ROLE_GROUPS = {
    "clarify": "design",
    "design": "design",
    "plan": "planning",
    "tdd-red": "test",
    "implement": "code",
    "r1-review": "review",
    "r2-review": "review",
    "r3-review": "review",
    "completion": "coverage",
}
LIFECYCLE_SATISFIED_PHASES = {
    "CLARIFIED": {"clarify"},
    "SERVICE_DESIGN_REQUIRED": {"clarify", "design"},
    "PLANNED": {"clarify", "design"},
    "RED_READY": {"clarify", "design", "r1-review", "plan", "tdd-red", "r2-review"},
    "IMPLEMENTED": {"clarify", "design", "r1-review", "plan", "tdd-red", "r2-review"},
    "REVIEWED": {"clarify", "design", "r1-review", "plan", "tdd-red", "r2-review", "implement", "r3-review"},
    "VERIFIED": {"clarify", "design", "r1-review", "plan", "tdd-red", "r2-review", "implement", "r3-review", "completion"},
}


def now_dt(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def parse_iso(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def task_lease_seconds(task: dict) -> int:
    try:
        value = int(task.get("lease_seconds", DEFAULT_LEASE_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_LEASE_SECONDS
    return value if value > 0 else DEFAULT_LEASE_SECONDS


def task_pulse(task: dict) -> datetime | None:
    """Most recent liveness signal: heartbeat if present, else claim time."""
    return parse_iso(task.get("heartbeat_at", "")) or parse_iso(task.get("claimed_at", ""))


def is_held(task: dict) -> bool:
    return str(task.get("status", "")).lower() in HELD_STATUSES and bool(str(task.get("owner", "")).strip())


def is_stale(task: dict, now: datetime | None = None) -> bool:
    if not is_held(task):
        return False
    pulse = task_pulse(task)
    if pulse is None:
        # Held with no timestamp at all: treat as stale so it can be recovered.
        return True
    return (now_dt(now) - pulse).total_seconds() > task_lease_seconds(task)


def resolve(repo: Path, path: Path | None) -> Path | None:
    if not path:
        return None
    return path if path.is_absolute() else repo / path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def find_task(schedule: dict, task_id: str) -> dict | None:
    for task in schedule.get("tasks", []) or []:
        if str(task.get("id", "")) == task_id:
            return task
    return None


def phases_completed(schedule: dict, phases: list[str]) -> tuple[bool, list[str]]:
    missing: list[str] = []
    tasks = schedule.get("tasks", []) or []
    for phase in phases:
        matching = [task for task in tasks if str(task.get("phase", "")) == phase]
        if phase == "tdd-red":
            service_matching = [task for task in matching if str(task.get("service", "")).strip()]
            if service_matching:
                matching = service_matching
        if not matching or any(str(task.get("status", "")).lower() != "completed" for task in matching):
            missing.append(phase)
    return not missing, missing


def completion_event_dir(repo: Path, schedule_path: Path | None, state_path: Path | None = None) -> Path:
    state_file = resolve(repo, state_path)
    schedule_file = resolve(repo, schedule_path)
    run_dir = state_file.parent if state_file else (schedule_file.parent if schedule_file else repo)
    return run_dir / "dispatch-events"


def completion_event_for_task(repo: Path, schedule_path: Path | None, state_path: Path | None, task: dict) -> dict:
    task_id = str(task.get("id", "")).strip()
    if not task_id:
        return {}
    path = completion_event_dir(repo, schedule_path, state_path) / f"{task_id}-completed.json"
    if not path.exists():
        return {}
    try:
        event = load_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    event["_path"] = str(path)
    return event


def task_has_dispatch_completion(repo: Path, schedule_path: Path | None, state_path: Path | None, task: dict) -> bool:
    task_id = str(task.get("id", "")).strip()
    agent = str(task.get("agent", "")).strip()
    if not task_id or not agent or str(task.get("status", "")).strip().lower() != "completed":
        return False
    event = completion_event_for_task(repo, schedule_path, state_path, task)
    return (
        event.get("event") == "worker_completed"
        and str(event.get("task_id", "")).strip() == task_id
        and str(event.get("agent", "")).strip() == agent
    )


def dispatch_completion_blockers_for_tasks(
    repo: Path,
    schedule_path: Path | None,
    state_path: Path | None,
    tasks: list[dict],
    label: str,
) -> list[str]:
    blocked: list[str] = []
    for task in tasks:
        task_id = str(task.get("id", "")).strip() or "<missing>"
        agent = str(task.get("agent", "")).strip() or "<missing>"
        if not task_has_dispatch_completion(repo, schedule_path, state_path, task):
            blocked.append(
                f"{label}: task {task_id} ({agent}) must be completed through dispatch-complete "
                "with a worker_completed dispatch event."
            )
    return blocked


def dispatch_completion_blockers_for_phases(
    repo: Path,
    schedule_path: Path | None,
    state_path: Path | None,
    schedule: dict,
    phases: list[str],
    label: str,
) -> list[str]:
    tasks = schedule.get("tasks", []) or []
    blocked: list[str] = []
    for phase in phases:
        matching = [task for task in tasks if str(task.get("phase", "")).strip() == phase]
        if phase == "tdd-red":
            service_matching = [task for task in matching if str(task.get("service", "")).strip()]
            if service_matching:
                matching = service_matching
        if not matching:
            blocked.append(f"{label}: missing scheduled {phase} task.")
            continue
        blocked.extend(dispatch_completion_blockers_for_tasks(repo, schedule_path, state_path, matching, label))
    return blocked


def tasks_with_output_fragments(schedule: dict, fragments: list[str]) -> list[dict]:
    normalized_fragments = [posix_path(fragment) for fragment in fragments]
    matching: list[dict] = []
    for task in schedule.get("tasks", []) or []:
        outputs = [posix_path(str(output)) for output in task.get("outputs", []) or [] if isinstance(output, str)]
        if any(fragment in output for output in outputs for fragment in normalized_fragments):
            matching.append(task)
    return matching


def lifecycle_satisfied_phases(repo: Path, state_path: Path | None) -> set[str]:
    state_file = resolve(repo, state_path)
    if not state_file or not state_file.exists():
        return set()
    try:
        state = load_json(state_file)
    except (OSError, json.JSONDecodeError):
        return set()
    lifecycle = str(state.get("lifecycle", "")).strip().upper()
    return LIFECYCLE_SATISFIED_PHASES.get(lifecycle, set())


def service_design_primary_task(task: dict) -> bool:
    if not str(task.get("service", "")).strip():
        return False
    if str(task.get("phase", "")).strip() not in {"tdd-red", "implement", "r3-review"}:
        return False
    return any(
        isinstance(item, str) and "/service-designs/" in item.replace("\\", "/") and item.endswith(".md")
        for item in task.get("inputs", []) or []
    )


def service_tasks(schedule: dict, services: list[str], phase: str = "implement") -> dict[str, dict]:
    tasks: dict[str, dict] = {}
    for task in schedule.get("tasks", []) or []:
        service = str(task.get("service", ""))
        if str(task.get("phase", "")) == phase and service:
            tasks[service] = task
    return {service: tasks.get(service, {}) for service in services}


def role_group(task: dict) -> str:
    explicit = str(task.get("role_group", "")).strip().lower()
    if explicit:
        return explicit
    return PHASE_ROLE_GROUPS.get(str(task.get("phase", "")).strip().lower(), "")


def same_agent(left: str, right: str) -> bool:
    return left.strip().lower() == right.strip().lower()


def role_conflict_blockers(schedule: dict, task: dict, agent: str) -> list[str]:
    blocked: list[str] = []
    target_group = role_group(task)
    if target_group not in EXCLUSIVE_ROLE_GROUPS:
        return blocked
    task_id = str(task.get("id", ""))
    for other in schedule.get("tasks", []) or []:
        if str(other.get("id", "")) == task_id:
            continue
        status = str(other.get("status", "")).lower()
        owner = str(other.get("owner", "")).strip()
        other_group = role_group(other)
        if (
            owner
            and same_agent(owner, agent)
            and status in CLAIMED_STATUSES
            and other_group in EXCLUSIVE_ROLE_GROUPS
            and other_group != target_group
        ):
            blocked.append(
                f"Agent {agent} cannot own both {target_group} and {other_group} role tasks "
                f"({task_id} conflicts with {other.get('id', '')})."
            )
    return blocked


def schedule_role_conflicts(schedule: dict) -> list[str]:
    by_owner: dict[str, set[str]] = {}
    for task in schedule.get("tasks", []) or []:
        owner = str(task.get("owner", "")).strip()
        status = str(task.get("status", "")).lower()
        group = role_group(task)
        if owner and status in CLAIMED_STATUSES and group in EXCLUSIVE_ROLE_GROUPS:
            by_owner.setdefault(owner.lower(), set()).add(group)
    return [
        f"Agent {owner} owns incompatible role groups: {', '.join(sorted(groups))}."
        for owner, groups in by_owner.items()
        if len(groups) > 1
    ]


def task_input_handoff_blockers(repo: Path, task: dict) -> list[str]:
    blocked: list[str] = []
    for item in task.get("inputs", []) or []:
        text = posix_path(str(item))
        if not text.endswith(".md"):
            continue
        if "/handoffs/" not in text and not text.endswith("/code-agent.md"):
            continue
        path = Path(text)
        full = path if path.is_absolute() else repo / path
        if not full.exists():
            blocked.append(f"Task {task.get('id', '')} input handoff is missing: {text}")
            continue
        result = handoff_gate.validate(repo, [path], require_files=True)
        if not result["ready"]:
            blocked.extend(
                f"Task {task.get('id', '')} input handoff is not ready: {reason}"
                for reason in result["blocked_reasons"]
            )
    return blocked


def maybe_transition_red_ready(repo: Path, state_path: Path | None, schedule: dict, evidence: list[str]) -> dict | None:
    if not state_path:
        return None
    state_file = resolve(repo, state_path)
    if not state_file or not state_file.exists():
        return None
    state = load_json(state_file)
    if str(state.get("lifecycle", "")) != "PLANNED":
        return None
    ready, _missing = phases_completed(schedule, ["tdd-red", "r2-review"])
    if not ready:
        return None
    evidence_path = Path(evidence[0]) if evidence else None
    return run_state.transition_state(
        repo,
        state_file,
        "RED_READY",
        gate="tdd_red",
        gate_status="passed",
        evidence=evidence_path,
    )


def role_template_blockers(repo: Path, schedule: dict, task: dict) -> list[str]:
    if not schedule.get("require_role_templates"):
        return []
    group = role_group(task)
    if group not in EXCLUSIVE_ROLE_GROUPS:
        return []
    template = posix_path(str(task.get("role_template", "")))
    if not template:
        return [f"Task {task.get('id', '')} must declare a role_template before claim."]
    path = Path(template)
    full = path if path.is_absolute() else repo / path
    try:
        full.resolve().relative_to(repo.resolve())
    except ValueError:
        return [f"Task {task.get('id', '')} role_template must stay inside repo: {template}"]
    if not full.exists() or not full.is_file():
        return [f"Task {task.get('id', '')} role_template is missing: {template}"]
    text = full.read_text(encoding="utf-8", errors="replace")
    missing = [marker for marker in ROLE_TEMPLATE_MARKERS if marker not in text]
    if missing:
        return [f"Task {task.get('id', '')} role_template is missing required sections: {', '.join(missing)}"]
    return []


def posix_path(value: str) -> str:
    return value.replace("\\", "/").strip()


def evidence_paths(repo: Path, evidence: list[str] | None) -> tuple[list[str], list[str]]:
    blocked: list[str] = []
    resolved: list[str] = []
    for item in evidence or []:
        path = Path(str(item))
        full = path if path.is_absolute() else repo / path
        if not full.exists() or not full.is_file():
            blocked.append(f"Task completion evidence is missing: {full}")
            continue
        try:
            stored = full.resolve().relative_to(repo.resolve())
        except ValueError:
            stored = path if not path.is_absolute() else full
        resolved.append(posix_path(str(stored)))
    if not evidence:
        blocked.append("Task completion requires at least one evidence file.")
    return resolved, blocked


def evidence_matches_outputs(task: dict, evidence: list[str]) -> bool:
    outputs = {posix_path(str(output)) for output in task.get("outputs", []) or [] if isinstance(output, str)}
    if not outputs:
        return True
    normalized_evidence = {posix_path(item) for item in evidence}
    return bool(outputs & normalized_evidence)


def evidence_content_blockers(repo: Path, evidence: list[str]) -> list[str]:
    blocked: list[str] = []
    for item in evidence:
        path = repo / item
        lower_name = path.name.lower()
        normalized = posix_path(item)
        text = path.read_text(encoding="utf-8", errors="replace")
        lowered = text.lower()
        if (
            path.suffix.lower() == ".md"
            and ("/handoffs/" in normalized or normalized.endswith("/code-agent.md") or normalized.endswith("/implementation-plan.md"))
        ):
            result = handoff_gate.validate(repo, [Path(item)], require_files=True)
            if not result["ready"]:
                blocked.extend(f"Task completion handoff evidence is not ready: {reason}" for reason in result["blocked_reasons"])
        if lower_name in {"implementation-manifest.md", "coverage-matrix.md"}:
            if any(marker in lowered for marker in ("todo", "placeholder", "template")):
                blocked.append(f"Task completion evidence is placeholder/template content: {item}")
        if "unit-test-evidence" in lower_name and path.suffix.lower() == ".json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError as error:
                blocked.append(f"Unit-test evidence must be valid JSON: {item}: {error}")
                continue
            entries = data if isinstance(data, list) else [data]
            if not entries or any(int(entry.get("exit_code", 1)) != 0 for entry in entries if isinstance(entry, dict)):
                blocked.append(f"Unit-test evidence must contain passing command results: {item}")
    return blocked


def validate_schedule(
    schedule: dict,
    services: list[str],
    require_claims: bool = False,
    require_completed: bool = False,
    now: datetime | None = None,
) -> dict:
    blocked: list[str] = []
    warnings: list[str] = []
    stale_services: list[str] = []
    if schedule.get("schema") != "e2e-dev-harness.agent-schedule.v1":
        blocked.append("Agent schedule schema must be e2e-dev-harness.agent-schedule.v1.")
    blocked.extend(schedule_role_conflicts(schedule))
    if schedule.get("require_role_templates"):
        for task in schedule.get("tasks", []) or []:
            if role_group(task) in EXCLUSIVE_ROLE_GROUPS and not str(task.get("role_template", "")).strip():
                blocked.append(f"Task {task.get('id', '')} must declare a role_template.")
    tasks = service_tasks(schedule, services)
    for service, task in tasks.items():
        if not task:
            blocked.append(f"Missing implement task for service/module: {service}")
            continue
        status = str(task.get("status", "planned")).lower()
        owner = str(task.get("owner", "")).strip()
        if require_claims and (not owner or status not in CLAIMED_STATUSES):
            blocked.append(f"Implement task for {service} must be claimed before code writes.")
        if require_completed and status != "completed":
            blocked.append(f"Implement task for {service} must be completed before completion.")
        if status != "completed" and is_stale(task, now):
            stale_services.append(service)
            message = (
                f"Claim for {service} is stale (lease expired; owner {owner or 'unknown'}). "
                "Renew with --action renew or take over with --action reclaim."
            )
            if require_claims:
                blocked.append(message)
            else:
                warnings.append(message)
    return {
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "services": services,
        "stale_services": stale_services,
        "require_claims": require_claims,
        "require_completed": require_completed,
    }


def update_state_owner(repo: Path, state_path: Path | None, task: dict, agent: str, status: str, evidence: list[str] | None = None) -> dict:
    if not state_path:
        return {"ready": True, "blocked_reasons": [], "warnings": ["No run-state supplied; schedule updated only."]}
    path = resolve(repo, state_path)
    if not path or not path.exists():
        return {"ready": False, "blocked_reasons": [f"Run state not found: {path}"], "warnings": []}
    state = load_json(path)
    service = str(task.get("service", ""))
    if service and str(task.get("phase", "")) == "implement":
        state.setdefault("owners", {})[service] = {
            "task_id": task.get("id", ""),
            "agent": agent,
            "status": status,
            "claimed_at": task.get("claimed_at", ""),
            "heartbeat_at": task.get("heartbeat_at", ""),
            "lease_seconds": task.get("lease_seconds", DEFAULT_LEASE_SECONDS),
            "completed_at": task.get("completed_at", ""),
            "allowed_scope": [service + "/"],
            "evidence": evidence or [],
        }
    state["updated_at"] = now_iso()
    run_state.write_state(repo, path, state)
    return {"ready": True, "blocked_reasons": [], "warnings": [], "run_state": str(path)}


def claim(
    repo: Path,
    schedule_path: Path,
    task_id: str,
    agent: str,
    state_path: Path | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    now: datetime | None = None,
) -> dict:
    path = resolve(repo, schedule_path)
    if not path or not path.exists():
        return {"ready": False, "blocked_reasons": [f"Agent schedule not found: {path}"], "warnings": []}
    schedule = load_json(path)
    task = find_task(schedule, task_id)
    if not task:
        return {"ready": False, "blocked_reasons": [f"Task not found in agent schedule: {task_id}"], "warnings": []}
    status = str(task.get("status", "planned")).lower()
    if status == "completed":
        return {"ready": False, "blocked_reasons": [f"Task already completed: {task_id}"], "warnings": []}
    role_blockers = role_conflict_blockers(schedule, task, agent)
    if role_blockers:
        return {"ready": False, "blocked_reasons": role_blockers, "warnings": []}
    template_blockers = role_template_blockers(repo, schedule, task)
    if template_blockers:
        return {"ready": False, "blocked_reasons": template_blockers, "warnings": []}
    _deps_ready, missing_deps = phases_completed(schedule, [str(phase) for phase in task.get("depends_on_phases", []) or []])
    satisfied = lifecycle_satisfied_phases(repo, state_path)
    missing_deps = [phase for phase in missing_deps if phase not in satisfied]
    if missing_deps:
        return {
            "ready": False,
            "blocked_reasons": [
                "Task "
                + task_id
                + " cannot be claimed until dependency phases are completed: "
                + ", ".join(missing_deps)
            ],
            "warnings": [],
        }
    handoff_blockers = [] if service_design_primary_task(task) and satisfied else task_input_handoff_blockers(repo, task)
    if handoff_blockers:
        return {"ready": False, "blocked_reasons": handoff_blockers, "warnings": []}
    warnings: list[str] = []
    prior_owner = str(task.get("owner", "")).strip()
    if prior_owner and prior_owner != agent:
        if not is_stale(task, now):
            return {
                "ready": False,
                "blocked_reasons": [
                    f"Task {task_id} has an active claim by {prior_owner}; "
                    "wait for the lease to expire, renew, or use --action reclaim --force."
                ],
                "warnings": [],
            }
        # Stale claim by another agent: take it over and record the handover.
        task["previous_owner"] = prior_owner
        task["claimed_at"] = None
        warnings.append(f"Took over stale claim from {prior_owner} for task {task_id}.")
    stamp = now_iso(now)
    task["status"] = "claimed"
    task["owner"] = agent
    task["claimed_at"] = task.get("claimed_at") or stamp
    task["heartbeat_at"] = stamp
    task["lease_seconds"] = int(lease_seconds) if int(lease_seconds) > 0 else DEFAULT_LEASE_SECONDS
    atomic_write_json(path, schedule)
    state_result = update_state_owner(repo, state_path, task, agent, "claimed")
    blocked = [] if state_result["ready"] else state_result["blocked_reasons"]
    return {
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings + state_result["warnings"],
        "schedule": str(path),
        "task": task,
        "run_state_update": state_result,
    }


def renew(
    repo: Path,
    schedule_path: Path,
    task_id: str,
    agent: str,
    state_path: Path | None = None,
    lease_seconds: int | None = None,
    now: datetime | None = None,
) -> dict:
    path = resolve(repo, schedule_path)
    if not path or not path.exists():
        return {"ready": False, "blocked_reasons": [f"Agent schedule not found: {path}"], "warnings": []}
    schedule = load_json(path)
    task = find_task(schedule, task_id)
    if not task:
        return {"ready": False, "blocked_reasons": [f"Task not found in agent schedule: {task_id}"], "warnings": []}
    if str(task.get("status", "")).lower() == "completed":
        return {"ready": False, "blocked_reasons": [f"Task already completed: {task_id}"], "warnings": []}
    owner = str(task.get("owner", "")).strip()
    if owner != agent:
        return {
            "ready": False,
            "blocked_reasons": [f"Task {task_id} is owned by {owner or 'no one'}, not {agent}; cannot renew."],
            "warnings": [],
        }
    task["heartbeat_at"] = now_iso(now)
    if lease_seconds is not None and int(lease_seconds) > 0:
        task["lease_seconds"] = int(lease_seconds)
    atomic_write_json(path, schedule)
    state_result = update_state_owner(repo, state_path, task, agent, str(task.get("status", "claimed")))
    blocked = [] if state_result["ready"] else state_result["blocked_reasons"]
    return {
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": state_result["warnings"],
        "schedule": str(path),
        "task": task,
        "run_state_update": state_result,
    }


def reclaim(
    repo: Path,
    schedule_path: Path,
    task_id: str,
    agent: str,
    state_path: Path | None = None,
    force: bool = False,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    now: datetime | None = None,
) -> dict:
    path = resolve(repo, schedule_path)
    if not path or not path.exists():
        return {"ready": False, "blocked_reasons": [f"Agent schedule not found: {path}"], "warnings": []}
    schedule = load_json(path)
    task = find_task(schedule, task_id)
    if not task:
        return {"ready": False, "blocked_reasons": [f"Task not found in agent schedule: {task_id}"], "warnings": []}
    if str(task.get("status", "")).lower() == "completed":
        return {"ready": False, "blocked_reasons": [f"Task already completed: {task_id}"], "warnings": []}
    role_blockers = role_conflict_blockers(schedule, task, agent)
    if role_blockers:
        return {"ready": False, "blocked_reasons": role_blockers, "warnings": []}
    template_blockers = role_template_blockers(repo, schedule, task)
    if template_blockers:
        return {"ready": False, "blocked_reasons": template_blockers, "warnings": []}
    prior_owner = str(task.get("owner", "")).strip()
    if prior_owner and prior_owner != agent and not force and not is_stale(task, now):
        return {
            "ready": False,
            "blocked_reasons": [
                f"Task {task_id} has an active claim by {prior_owner}; "
                "reclaim requires a stale lease or --force."
            ],
            "warnings": [],
        }
    warnings: list[str] = []
    if prior_owner and prior_owner != agent:
        task["previous_owner"] = prior_owner
        warnings.append(f"Reclaimed task {task_id} from {prior_owner}.")
    stamp = now_iso(now)
    task["status"] = "claimed"
    task["owner"] = agent
    task["claimed_at"] = stamp
    task["heartbeat_at"] = stamp
    task["lease_seconds"] = int(lease_seconds) if int(lease_seconds) > 0 else DEFAULT_LEASE_SECONDS
    atomic_write_json(path, schedule)
    state_result = update_state_owner(repo, state_path, task, agent, "claimed")
    blocked = [] if state_result["ready"] else state_result["blocked_reasons"]
    return {
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings + state_result["warnings"],
        "schedule": str(path),
        "task": task,
        "run_state_update": state_result,
    }


def complete(
    repo: Path,
    schedule_path: Path,
    task_id: str,
    agent: str,
    state_path: Path | None = None,
    evidence: list[str] | None = None,
    dispatcher_confirmed: bool = False,
    allow_local_completion: bool = False,
) -> dict:
    path = resolve(repo, schedule_path)
    if not path or not path.exists():
        return {"ready": False, "blocked_reasons": [f"Agent schedule not found: {path}"], "warnings": []}
    schedule = load_json(path)
    task = find_task(schedule, task_id)
    if not task:
        return {"ready": False, "blocked_reasons": [f"Task not found in agent schedule: {task_id}"], "warnings": []}
    completion_mode = str(schedule.get("completion_mode", "")).strip().lower()
    warnings: list[str] = []
    if completion_mode == DISPATCHER_CONFIRMED_COMPLETION and not dispatcher_confirmed:
        if not allow_local_completion:
            return {
                "ready": False,
                "blocked_reasons": [
                    f"Task {task_id} is in dispatcher-confirmed completion mode; use dispatch-complete after dispatch-ack, or rerun with --allow-local-completion for an explicit legacy/manual recovery."
                ],
                "warnings": [],
            }
        warnings.append(
            f"Local completion override used for dispatcher-confirmed task {task_id}; prefer dispatch-complete for normal coordinator-only runs."
        )
        schedule.setdefault("manual_recovery_events", []).append(
            {
                "task_id": task_id,
                "agent": agent,
                "event": "allow-local-completion",
                "warning": warnings[-1],
                "recorded_at": now_iso(),
            }
        )
    owner = str(task.get("owner", ""))
    if owner and owner != agent:
        return {"ready": False, "blocked_reasons": [f"Task {task_id} is owned by {owner}, not {agent}."], "warnings": []}
    role_blockers = role_conflict_blockers(schedule, task, agent)
    if role_blockers:
        return {"ready": False, "blocked_reasons": role_blockers, "warnings": []}
    template_blockers = role_template_blockers(repo, schedule, task)
    if template_blockers:
        return {"ready": False, "blocked_reasons": template_blockers, "warnings": []}
    resolved_evidence, evidence_blocked = evidence_paths(repo, evidence)
    if evidence_blocked:
        return {"ready": False, "blocked_reasons": evidence_blocked, "warnings": []}
    if not evidence_matches_outputs(task, resolved_evidence):
        return {
            "ready": False,
            "blocked_reasons": [f"Task {task_id} completion evidence must reference one of the task outputs."],
            "warnings": [],
        }
    content_blockers = evidence_content_blockers(repo, resolved_evidence)
    if content_blockers:
        return {"ready": False, "blocked_reasons": content_blockers, "warnings": []}
    if not owner:
        task["owner"] = agent
        task["claimed_at"] = task.get("claimed_at") or now_iso()
    task["status"] = "completed"
    task["completed_at"] = now_iso()
    task["evidence"] = resolved_evidence
    atomic_write_json(path, schedule)
    state_result = update_state_owner(repo, state_path, task, agent, "completed", resolved_evidence)
    transition = None if dispatcher_confirmed else maybe_transition_red_ready(repo, state_path, schedule, resolved_evidence)
    blocked = [] if state_result["ready"] else state_result["blocked_reasons"]
    if transition and not transition["ready"]:
        blocked.extend("Run state transition: " + reason for reason in transition["blocked_reasons"])
    return {
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings + state_result["warnings"],
        "schedule": str(path),
        "task": task,
        "run_state_update": state_result,
        "run_state_transition": transition,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--schedule", required=True, type=Path)
    parser.add_argument("--task-id")
    parser.add_argument("--agent", default="")
    parser.add_argument("--state", type=Path)
    parser.add_argument("--action", choices=["claim", "complete", "validate", "renew", "reclaim"], required=True)
    parser.add_argument("--service", action="append")
    parser.add_argument("--require-claims", action="store_true")
    parser.add_argument("--require-completed", action="store_true")
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--allow-local-completion", action="store_true")
    parser.add_argument("--lease-seconds", type=int, default=DEFAULT_LEASE_SECONDS)
    parser.add_argument("--force", action="store_true", help="Reclaim an active (non-stale) claim.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if args.action == "claim":
        result = claim(repo, args.schedule, args.task_id or "", args.agent or "agent", args.state, args.lease_seconds)
    elif args.action == "renew":
        result = renew(repo, args.schedule, args.task_id or "", args.agent or "agent", args.state, args.lease_seconds)
    elif args.action == "reclaim":
        result = reclaim(repo, args.schedule, args.task_id or "", args.agent or "agent", args.state, args.force, args.lease_seconds)
    elif args.action == "complete":
        result = complete(
            repo,
            args.schedule,
            args.task_id or "",
            args.agent or "agent",
            args.state,
            args.evidence,
            allow_local_completion=args.allow_local_completion,
        )
    else:
        path = resolve(repo, args.schedule)
        schedule = load_json(path) if path and path.exists() else {}
        result = validate_schedule(schedule, args.service or [], args.require_claims, args.require_completed)
        if path:
            result["schedule"] = str(path)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Agent schedule: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
