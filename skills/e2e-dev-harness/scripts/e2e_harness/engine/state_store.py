"""Event-first state-store wrappers for compatibility snapshots."""

from __future__ import annotations

from pathlib import Path

import agent_scheduler
import dispatcher
import event_log
import run_state


def _resolve(repo: Path, path: Path | None) -> Path | None:
    if not path:
        return None
    return path if path.is_absolute() else repo / path


def _run_dir(repo: Path, state_path: Path | None = None, schedule_path: Path | None = None) -> Path:
    state_file = _resolve(repo, state_path)
    schedule_file = _resolve(repo, schedule_path)
    if state_file:
        return state_file.parent
    if schedule_file:
        return schedule_file.parent
    return repo


def _project(repo: Path, state_path: Path | None = None, schedule_path: Path | None = None) -> dict:
    run_dir = _run_dir(repo, state_path, schedule_path)
    return event_log.write_snapshot_projections(run_dir, _resolve(repo, state_path), _resolve(repo, schedule_path))


def transition_lifecycle(
    repo: Path,
    state_path: Path,
    target_lifecycle: str,
    gate: str | None = None,
    gate_status: str | None = None,
    evidence: Path | None = None,
    allow_regression: bool = False,
) -> dict:
    result = run_state.transition_state(
        repo,
        state_path,
        target_lifecycle,
        gate=gate,
        gate_status=gate_status,
        evidence=evidence,
        allow_regression=allow_regression,
    )
    if result.get("ready"):
        history_event = result.get("history_event", {}) if isinstance(result.get("history_event"), dict) else {}
        event_log.append_state_event(
            _run_dir(repo, state_path),
            "lifecycle_transition",
            {
                "from": history_event.get("from", ""),
                "to": target_lifecycle,
                "gate": gate or "",
                "gate_status": gate_status or "",
                "evidence": str(evidence or "").replace("\\", "/"),
            },
            state_path=_resolve(repo, state_path),
        )
    return result


def claim_task(
    repo: Path,
    schedule_path: Path,
    task_id: str,
    agent: str,
    state_path: Path | None = None,
    lease_seconds: int = agent_scheduler.DEFAULT_LEASE_SECONDS,
) -> dict:
    result = agent_scheduler.claim(repo, schedule_path, task_id, agent, state_path, lease_seconds=lease_seconds)
    if result.get("ready"):
        event_log.append_state_event(
            _run_dir(repo, state_path, schedule_path),
            "schedule_task_claimed",
            {"task_id": task_id, "agent": agent, "status": "claimed"},
            state_path=_resolve(repo, state_path),
            schedule_path=_resolve(repo, schedule_path),
        )
    return result


def renew_task(
    repo: Path,
    schedule_path: Path,
    task_id: str,
    agent: str,
    state_path: Path | None = None,
    lease_seconds: int | None = None,
) -> dict:
    result = agent_scheduler.renew(repo, schedule_path, task_id, agent, state_path, lease_seconds=lease_seconds)
    if result.get("ready"):
        event_log.append_state_event(
            _run_dir(repo, state_path, schedule_path),
            "schedule_task_renewed",
            {"task_id": task_id, "agent": agent, "status": result.get("task", {}).get("status", "claimed")},
            state_path=_resolve(repo, state_path),
            schedule_path=_resolve(repo, schedule_path),
        )
    return result


def reclaim_task(
    repo: Path,
    schedule_path: Path,
    task_id: str,
    agent: str,
    state_path: Path | None = None,
    force: bool = False,
    lease_seconds: int = agent_scheduler.DEFAULT_LEASE_SECONDS,
) -> dict:
    result = agent_scheduler.reclaim(repo, schedule_path, task_id, agent, state_path, force=force, lease_seconds=lease_seconds)
    if result.get("ready"):
        event_log.append_state_event(
            _run_dir(repo, state_path, schedule_path),
            "schedule_task_reclaimed",
            {"task_id": task_id, "agent": agent, "status": "claimed"},
            state_path=_resolve(repo, state_path),
            schedule_path=_resolve(repo, schedule_path),
        )
    return result


def complete_task(
    repo: Path,
    schedule_path: Path,
    task_id: str,
    agent: str,
    state_path: Path | None = None,
    evidence: list[str] | None = None,
    dispatcher_confirmed: bool = True,
    allow_local_completion: bool = False,
    manual_recovery: bool = False,
    recovery_approved: bool = False,
) -> dict:
    result = agent_scheduler.complete(
        repo,
        schedule_path,
        task_id,
        agent,
        state_path,
        evidence or [],
        dispatcher_confirmed=dispatcher_confirmed,
        allow_local_completion=allow_local_completion,
        manual_recovery=manual_recovery,
        recovery_approved=recovery_approved,
    )
    if result.get("ready"):
        event_log.append_state_event(
            _run_dir(repo, state_path, schedule_path),
            "schedule_task_completed",
            {"task_id": task_id, "agent": agent, "status": "completed", "evidence": evidence or []},
            state_path=_resolve(repo, state_path),
            schedule_path=_resolve(repo, schedule_path),
        )
    return result


def dispatch_next(repo: Path, schedule_path: Path, state_path: Path | None = None, runtime: str = "claude-code") -> dict:
    result = dispatcher.dispatch_next(repo, schedule_path, state_path, runtime=runtime)
    if result.get("ready"):
        _project(repo, state_path, schedule_path)
    return result


def dispatch_ack(
    repo: Path,
    state_path: Path | None,
    task_id: str,
    agent: str,
    worker_handle: str,
    worker_session: str = "",
) -> dict:
    result = dispatcher.dispatch_ack(repo, state_path, task_id, agent, worker_handle, worker_session)
    if result.get("ready"):
        event_log.write_snapshot_projections(_run_dir(repo, state_path), _resolve(repo, state_path), None)
    return result


def dispatch_complete(
    repo: Path,
    schedule_path: Path,
    state_path: Path | None,
    task_id: str,
    agent: str,
    evidence: list[str] | None = None,
    manual_recovery: bool = False,
    recovery_approval: Path | None = None,
) -> dict:
    result = dispatcher.dispatch_complete(
        repo,
        schedule_path,
        state_path,
        task_id,
        agent,
        evidence or [],
        manual_recovery=manual_recovery,
        recovery_approval=recovery_approval,
    )
    if result.get("ready"):
        _project(repo, state_path, schedule_path)
    return result
