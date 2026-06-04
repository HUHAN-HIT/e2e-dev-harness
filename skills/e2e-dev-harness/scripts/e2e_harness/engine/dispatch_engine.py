"""Dispatch engine facade."""

from __future__ import annotations

from pathlib import Path

import dispatcher


def runtime_capabilities(runtime: str | None = "claude-code") -> dict:
    result = dispatcher.runtime_capabilities(runtime)
    result.update({"ready": True, "blocked_reasons": [], "warnings": []})
    return result


def status(
    repo: Path,
    schedule: Path,
    state: Path | None = None,
    write_recovery_request_path: Path | None = None,
    recovery_task_id: str = "",
    recovery_agent: str = "",
    recovery_evidence: list[str] | None = None,
) -> dict:
    return dispatcher.dispatch_status(
        repo,
        schedule,
        state,
        write_recovery_request_path=write_recovery_request_path,
        recovery_task_id=recovery_task_id,
        recovery_agent=recovery_agent,
        recovery_evidence=recovery_evidence or [],
    )


def ack(repo: Path, state: Path | None, task_id: str, agent: str, worker_handle: str, worker_session: str = "") -> dict:
    return dispatcher.dispatch_ack(repo, state, task_id, agent, worker_handle, worker_session)


def complete(
    repo: Path,
    schedule: Path,
    state: Path | None,
    task_id: str,
    agent: str,
    evidence: list[str] | None = None,
    manual_recovery: bool = False,
    recovery_approval: Path | None = None,
) -> dict:
    return dispatcher.dispatch_complete(
        repo,
        schedule,
        state,
        task_id,
        agent,
        evidence or [],
        manual_recovery=manual_recovery,
        recovery_approval=recovery_approval,
    )
