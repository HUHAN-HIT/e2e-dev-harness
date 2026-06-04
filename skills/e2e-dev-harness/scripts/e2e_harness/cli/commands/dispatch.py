"""Dispatch command facades."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import coordinator_flow
from e2e_harness.cli.status import write_status
from e2e_harness.engine import dispatch_engine


def _as_repo(path: Path) -> Path:
    return Path(path).resolve()


def _dispatch_args(
    repo: Path,
    schedule: Path,
    state: Path,
    runtime: str = "claude-code",
    coordinator_agent: str = "coordinator-agent",
    developer_session: str = "coordinator-session",
    max_workers: int = 1,
    max_files: int = 12,
    max_chars: int = 120_000,
    status_file: Path | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        repo=repo,
        schedule=schedule,
        state=state,
        runtime=runtime,
        coordinator_agent=coordinator_agent,
        developer_session=developer_session,
        max_workers=max_workers,
        max_files=max_files,
        max_chars=max_chars,
        status_file=status_file,
    )


def run_next(
    repo: Path,
    schedule: Path,
    state: Path,
    runtime: str = "claude-code",
    coordinator_agent: str = "coordinator-agent",
    developer_session: str = "coordinator-session",
    max_files: int = 12,
    max_chars: int = 120_000,
    status_file: Path | None = None,
) -> tuple[int, dict]:
    args = _dispatch_args(
        _as_repo(repo),
        schedule,
        state,
        runtime=runtime,
        coordinator_agent=coordinator_agent,
        developer_session=developer_session,
        max_files=max_files,
        max_chars=max_chars,
        status_file=status_file,
    )
    return coordinator_flow.dispatch_next(args)


def run_beat(
    repo: Path,
    schedule: Path,
    state: Path,
    runtime: str = "claude-code",
    coordinator_agent: str = "coordinator-agent",
    developer_session: str = "coordinator-session",
    max_workers: int = 1,
    max_files: int = 12,
    max_chars: int = 120_000,
    status_file: Path | None = None,
) -> tuple[int, dict]:
    args = _dispatch_args(
        _as_repo(repo),
        schedule,
        state,
        runtime=runtime,
        coordinator_agent=coordinator_agent,
        developer_session=developer_session,
        max_workers=max_workers,
        max_files=max_files,
        max_chars=max_chars,
        status_file=status_file,
    )
    return coordinator_flow.dispatch_beat(args)


def run_complete(
    repo: Path,
    schedule: Path,
    state: Path | None,
    task_id: str,
    agent: str,
    evidence: list[str] | None = None,
    manual_recovery: bool = False,
    recovery_approval: Path | None = None,
    status_file: Path | None = None,
) -> dict:
    result = dispatch_engine.complete(
        _as_repo(repo),
        schedule,
        state,
        task_id,
        agent or "agent",
        evidence or [],
        manual_recovery=manual_recovery,
        recovery_approval=recovery_approval,
    )
    write_status(status_file, result)
    return result


def run_ack(
    repo: Path,
    state: Path | None,
    task_id: str,
    agent: str,
    worker_handle: str,
    worker_session: str = "",
    status_file: Path | None = None,
) -> dict:
    result = dispatch_engine.ack(
        _as_repo(repo),
        state,
        task_id,
        agent,
        worker_handle,
        worker_session or "",
    )
    write_status(status_file, result)
    return result


def run_status(
    repo: Path,
    schedule: Path,
    state: Path | None = None,
    write_recovery_request: Path | None = None,
    task_id: str = "",
    agent: str = "",
    evidence: list[str] | None = None,
    status_file: Path | None = None,
) -> dict:
    result = dispatch_engine.status(
        _as_repo(repo),
        schedule,
        state,
        write_recovery_request_path=write_recovery_request,
        recovery_task_id=task_id or "",
        recovery_agent=agent or "",
        recovery_evidence=evidence or [],
    )
    write_status(status_file, result)
    return result


def run_next_from_args(args) -> tuple[int, dict]:
    return run_next(
        getattr(args, "repo"),
        getattr(args, "schedule"),
        getattr(args, "state"),
        runtime=getattr(args, "runtime", "claude-code"),
        coordinator_agent=getattr(args, "coordinator_agent", "coordinator-agent"),
        developer_session=getattr(args, "developer_session", "coordinator-session"),
        max_files=getattr(args, "max_files", 12),
        max_chars=getattr(args, "max_chars", 120_000),
        status_file=getattr(args, "status_file", None),
    )


def run_beat_from_args(args) -> tuple[int, dict]:
    return run_beat(
        getattr(args, "repo"),
        getattr(args, "schedule"),
        getattr(args, "state"),
        runtime=getattr(args, "runtime", "claude-code"),
        coordinator_agent=getattr(args, "coordinator_agent", "coordinator-agent"),
        developer_session=getattr(args, "developer_session", "coordinator-session"),
        max_workers=getattr(args, "max_workers", 1),
        max_files=getattr(args, "max_files", 12),
        max_chars=getattr(args, "max_chars", 120_000),
        status_file=getattr(args, "status_file", None),
    )


def run_complete_from_args(args) -> tuple[int, dict]:
    result = run_complete(
        getattr(args, "repo"),
        getattr(args, "schedule"),
        getattr(args, "state", None),
        getattr(args, "task_id"),
        getattr(args, "agent", "") or "agent",
        evidence=getattr(args, "evidence", None) or [],
        manual_recovery=getattr(args, "manual_recovery", False),
        recovery_approval=getattr(args, "recovery_approval", None),
        status_file=getattr(args, "status_file", None),
    )
    return (0 if result["ready"] else 2), result


def run_ack_from_args(args) -> tuple[int, dict]:
    result = run_ack(
        getattr(args, "repo"),
        getattr(args, "state", None),
        getattr(args, "task_id"),
        getattr(args, "agent"),
        getattr(args, "worker_handle"),
        getattr(args, "worker_session", "") or "",
        status_file=getattr(args, "status_file", None),
    )
    return (0 if result["ready"] else 2), result


def run_status_from_args(args) -> tuple[int, dict]:
    result = run_status(
        getattr(args, "repo"),
        getattr(args, "schedule"),
        getattr(args, "state", None),
        write_recovery_request=getattr(args, "write_recovery_request", None),
        task_id=getattr(args, "task_id", "") or "",
        agent=getattr(args, "agent", "") or "",
        evidence=getattr(args, "evidence", None) or [],
        status_file=getattr(args, "status_file", None),
    )
    return (0 if result["ready"] else 2), result
