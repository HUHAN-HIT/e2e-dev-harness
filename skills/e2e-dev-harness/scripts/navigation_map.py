#!/usr/bin/env python3
"""Read-only Development Navigation Map projection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

SCHEMA = "e2e-dev-harness.navigation-map.v1"
MAX_LIST = 8

# control-plane.json is the single source of truth; legacy files are derived projections.
DEFAULT_AUTHORITY = {
    "primary": "control-plane.json",
    "derived": ["run-state.json", "agent-schedule.json", ".phase-lock", "coordinator-summary.json"],
}


def _strings(values: Any, limit: int = MAX_LIST) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        if isinstance(value, dict):
            text = str(value.get("minimal_fix") or value.get("message") or value.get("code") or "").strip()
        else:
            text = str(value).strip()
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _rel(repo: Path, value: Any) -> str:
    if not value:
        return ""
    path = value if isinstance(value, Path) else Path(str(value))
    try:
        resolved = path if path.is_absolute() else repo / path
        return resolved.resolve().relative_to(repo.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def _active_dispatches(state: dict) -> list[dict]:
    dispatches = state.get("dispatches", {}) if isinstance(state.get("dispatches"), dict) else {}
    active: list[dict] = []
    for task_id, dispatch in dispatches.items():
        if not isinstance(dispatch, dict):
            continue
        status = str(dispatch.get("status", "")).strip()
        if status.lower() in {"", "completed", "worker_completed", "cancelled"}:
            continue
        item = {
            "task_id": str(task_id),
            "status": status,
            "runtime": str(dispatch.get("runtime", "")),
            "agent": str(dispatch.get("current_agent", dispatch.get("agent", ""))),
            "worker_handle": str(dispatch.get("worker_handle", "")),
            "context_pack": str(dispatch.get("context_pack", "")),
            "invocation_path": str(dispatch.get("invocation_path", "")),
        }
        active.append({key: value for key, value in item.items() if value})
        if len(active) >= MAX_LIST:
            break
    return active


def _single_action(action: dict, preflight: dict, execution_packet: dict) -> dict:
    preflight_action = str(preflight.get("next_single_action", "")).strip()
    if preflight_action:
        return {
            "command": preflight_action,
            "source": "preflight",
            "reason": "Preflight selected the next single safe action.",
        }
    command = str(
        action.get("dispatch_command")
        or action.get("command")
        or execution_packet.get("exact_next_command")
        or execution_packet.get("primary_command")
        or ""
    ).strip()
    return {
        "command": command,
        "source": "next_action" if command else "none",
        "reason": str(execution_packet.get("objective", "")).strip(),
    }


def _artifacts(
    repo: Path,
    state_path: Path,
    checkpoint: dict,
    coordinator_summary_path: str = "",
) -> dict:
    artifacts = {
        "run_state": _rel(repo, state_path),
        "run_dir": _rel(repo, state_path.parent),
    }
    checkpoint_path = str(checkpoint.get("checkpoint", "")).strip() if isinstance(checkpoint, dict) else ""
    if checkpoint_path:
        artifacts["checkpoint"] = checkpoint_path
    if coordinator_summary_path:
        artifacts["coordinator_summary"] = coordinator_summary_path
    return artifacts


def _diagnostic_checks(diagnostics: dict) -> list[dict]:
    checks = diagnostics.get("checks", [])
    if not isinstance(checks, list):
        return []
    result: list[dict] = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        compact = {
            key: item[key]
            for key in ("name", "status", "severity")
            if item.get(key)
        }
        if compact:
            result.append(compact)
        if len(result) >= MAX_LIST:
            break
    return result


def build(
    *,
    repo: Path,
    state_path: Path,
    state: dict,
    lifecycle: str,
    workflow_stage: str,
    ready: bool,
    blocked_reasons: list[str],
    warnings: list[str],
    action: dict,
    preflight: dict,
    execution_packet: dict,
    checkpoint: dict,
    coordinator_summary_path: str = "",
    diagnostics: dict | None = None,
) -> dict:
    diagnostics = diagnostics or {}
    authority = (
        diagnostics.get("authority")
        if isinstance(diagnostics.get("authority"), dict)
        else dict(DEFAULT_AUTHORITY)
    )
    phase = str(action.get("phase") or execution_packet.get("phase") or "").strip()
    preflight_blockers = _strings(preflight.get("blockers", []))
    return {
        "schema": SCHEMA,
        "you_are_here": {
            "lifecycle": lifecycle or "<missing>",
            "workflow_stage": workflow_stage or "UNKNOWN",
            "phase": phase,
        },
        "status": {
            "ready": bool(ready),
            "health": "ready" if ready else "blocked",
            "blocked_by": _strings(list(blocked_reasons) + preflight_blockers),
            "warnings": _strings(warnings),
        },
        "next_single_action": _single_action(action, preflight, execution_packet),
        "active_work": _active_dispatches(state),
        "allowed_now": _strings(action.get("allowed_writes", execution_packet.get("allowed_now", []))),
        "forbidden_now": _strings(
            list(action.get("forbidden_local_actions", []))
            + list(action.get("blocked_writes", []))
            + list(execution_packet.get("forbidden_now", []))
        ),
        "state_confidence": str(diagnostics.get("state_confidence", "unknown")).strip() or "unknown",
        "diagnostics": {
            "primary_blocker_code": str(diagnostics.get("primary_blocker_code", "")).strip(),
            "checks": _diagnostic_checks(diagnostics),
        },
        "must_read_paths": _strings(diagnostics.get("must_read_paths", [])),
        "authority": authority,
        "required_evidence": _strings(execution_packet.get("required_evidence", [])),
        "completion_checks": _strings(execution_packet.get("completion_checks", execution_packet.get("completion_requires", []))),
        "artifacts": _artifacts(repo, state_path, checkpoint, coordinator_summary_path),
    }
