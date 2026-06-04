"""Agent-task command facade."""

from __future__ import annotations

import json
from pathlib import Path

import agent_scheduler
from e2e_harness.cli.status import write_status
from e2e_harness.engine import state_store


SCHEMA = "e2e-dev-harness.agent-task.v1"


def _as_repo(path: Path) -> Path:
    return Path(path).resolve()


def _with_schema(result: dict) -> dict:
    result.setdefault("schema", SCHEMA)
    return result


def run_claim(
    repo: Path,
    schedule: Path,
    task_id: str,
    agent: str = "agent",
    state: Path | None = None,
    lease_seconds: int = agent_scheduler.DEFAULT_LEASE_SECONDS,
    status_file: Path | None = None,
) -> dict:
    result = state_store.claim_task(_as_repo(repo), schedule, task_id or "", agent or "agent", state, lease_seconds)
    _with_schema(result)
    write_status(status_file, result)
    return result


def run_renew(
    repo: Path,
    schedule: Path,
    task_id: str,
    agent: str = "agent",
    state: Path | None = None,
    lease_seconds: int = agent_scheduler.DEFAULT_LEASE_SECONDS,
    status_file: Path | None = None,
) -> dict:
    result = state_store.renew_task(_as_repo(repo), schedule, task_id or "", agent or "agent", state, lease_seconds)
    _with_schema(result)
    write_status(status_file, result)
    return result


def run_reclaim(
    repo: Path,
    schedule: Path,
    task_id: str,
    agent: str = "agent",
    state: Path | None = None,
    force: bool = False,
    lease_seconds: int = agent_scheduler.DEFAULT_LEASE_SECONDS,
    status_file: Path | None = None,
) -> dict:
    result = state_store.reclaim_task(
        _as_repo(repo),
        schedule,
        task_id or "",
        agent or "agent",
        state,
        force=force,
        lease_seconds=lease_seconds,
    )
    _with_schema(result)
    write_status(status_file, result)
    return result


def run_complete(
    repo: Path,
    schedule: Path,
    task_id: str,
    agent: str = "agent",
    state: Path | None = None,
    evidence: list[str] | None = None,
    allow_local_completion: bool = False,
    status_file: Path | None = None,
) -> dict:
    result = state_store.complete_task(
        _as_repo(repo),
        schedule,
        task_id or "",
        agent or "agent",
        state,
        evidence or [],
        allow_local_completion=allow_local_completion,
    )
    _with_schema(result)
    write_status(status_file, result)
    return result


def run_validate(
    repo: Path,
    schedule: Path,
    services: list[str] | None = None,
    require_claims: bool = False,
    require_completed: bool = False,
    status_file: Path | None = None,
) -> dict:
    repo = _as_repo(repo)
    schedule_path = schedule if schedule.is_absolute() else repo / schedule
    schedule_data = json.loads(schedule_path.read_text(encoding="utf-8")) if schedule_path.exists() else {}
    result = agent_scheduler.validate_schedule(
        schedule_data,
        services or [],
        require_claims,
        require_completed,
    )
    result["schedule"] = str(schedule_path)
    _with_schema(result)
    write_status(status_file, result)
    return result


def run_from_args(args) -> tuple[int, dict]:
    action = getattr(args, "action")
    lease_seconds = getattr(args, "lease_seconds", agent_scheduler.DEFAULT_LEASE_SECONDS)
    if action == "claim":
        result = run_claim(
            getattr(args, "repo"),
            getattr(args, "schedule"),
            getattr(args, "task_id", "") or "",
            getattr(args, "agent", "") or "agent",
            getattr(args, "state", None),
            lease_seconds=lease_seconds,
            status_file=getattr(args, "status_file", None),
        )
    elif action == "renew":
        result = run_renew(
            getattr(args, "repo"),
            getattr(args, "schedule"),
            getattr(args, "task_id", "") or "",
            getattr(args, "agent", "") or "agent",
            getattr(args, "state", None),
            lease_seconds=lease_seconds,
            status_file=getattr(args, "status_file", None),
        )
    elif action == "reclaim":
        result = run_reclaim(
            getattr(args, "repo"),
            getattr(args, "schedule"),
            getattr(args, "task_id", "") or "",
            getattr(args, "agent", "") or "agent",
            getattr(args, "state", None),
            force=getattr(args, "force", False),
            lease_seconds=lease_seconds,
            status_file=getattr(args, "status_file", None),
        )
    elif action == "complete":
        result = run_complete(
            getattr(args, "repo"),
            getattr(args, "schedule"),
            getattr(args, "task_id", "") or "",
            getattr(args, "agent", "") or "agent",
            getattr(args, "state", None),
            evidence=getattr(args, "evidence", None) or [],
            allow_local_completion=getattr(args, "allow_local_completion", False),
            status_file=getattr(args, "status_file", None),
        )
    else:
        result = run_validate(
            getattr(args, "repo"),
            getattr(args, "schedule"),
            services=getattr(args, "service", None) or [],
            require_claims=getattr(args, "require_claims", False),
            require_completed=getattr(args, "require_completed", False),
            status_file=getattr(args, "status_file", None),
        )
    return (0 if result["ready"] else 2), result
