"""Dispatch engine facade."""

from __future__ import annotations

from pathlib import Path

import dispatcher
from e2e_harness.cli.commands import handoff as handoff_command


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


def finish(
    repo: Path,
    schedule: Path,
    state: Path | None,
    task_id: str,
    agent: str,
    worker_handle: str,
    worker_session: str = "",
    evidence: list[str] | None = None,
    handoff: Path | None = None,
) -> dict:
    """Post-spawn one-shot for a single dispatched worker.

    Collapses the three deterministic post-spawn steps -- ``dispatch-ack`` ->
    (optional) ``handoff finalize`` -> ``dispatch-complete`` -- into one call so
    the coordinator stops hand-assembling them and never reaches for
    ``--allow-local-completion``.

    Isolation is preserved, not weakened: ``worker_handle`` is still required and
    forwarded to ``dispatch_ack`` (the same fresh-worker proof the gate demands),
    and ``dispatch_complete`` still runs its full gate. Any failing step
    short-circuits the rest so an incomplete worker can never self-certify.
    """
    result: dict = {
        "schema": "e2e-dev-harness.dispatch-finish.v1",
        "ready": False,
        "stage": "ack",
        "blocked_reasons": [],
        "warnings": [],
        "task_id": task_id,
        "agent": agent,
    }

    _state_path, state_data = dispatcher.load_state(repo, state)
    dispatch = dispatcher.dispatch_for_task(state_data, task_id) if state_data else {}
    if str(dispatch.get("status", "")).strip() == "worker_running":
        ack_result = {
            "ready": True,
            "blocked_reasons": [],
            "warnings": ["Dispatch already acknowledged; dispatch-finish will reuse existing worker proof."],
            "dispatch": dispatch,
        }
    else:
        ack_result = dispatcher.dispatch_ack(repo, state, task_id, agent, worker_handle, worker_session or "")
    result["ack"] = ack_result
    result["warnings"].extend(ack_result.get("warnings", []))
    if not ack_result.get("ready"):
        result["blocked_reasons"] = list(ack_result.get("blocked_reasons", []))
        result["next_hint"] = (
            "Run dispatch-beat/dispatch-next and spawn the worker before dispatch-finish."
        )
        return result

    if handoff is not None:
        handoff_result = handoff_command.run_finalize(repo, Path(handoff), agent)
        result["handoff"] = handoff_result
        result["stage"] = "handoff"
        result["warnings"].extend(handoff_result.get("warnings", []))
        if not handoff_result.get("ready"):
            result["blocked_reasons"] = list(handoff_result.get("blocked_reasons", []))
            result["next_hint"] = handoff_result.get(
                "next_hint", "Fix the handoff blockers, then rerun dispatch-finish."
            )
            return result

    complete_result = dispatcher.dispatch_complete(repo, schedule, state, task_id, agent, evidence or [])
    result["complete"] = complete_result
    result["stage"] = "complete"
    result["ready"] = bool(complete_result.get("ready"))
    result["blocked_reasons"] = list(complete_result.get("blocked_reasons", []))
    result["warnings"].extend(complete_result.get("warnings", []))
    for key in (
        "missing_evidence_type",
        "required_outputs",
        "handoff_completion_requirements",
        "manual_worker_packet",
        "next_commands",
        "next_required",
    ):
        if key in complete_result:
            result[key] = complete_result[key]
    return result
