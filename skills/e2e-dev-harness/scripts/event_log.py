#!/usr/bin/env python3
"""Append-only enterprise event log for harness runs."""

from __future__ import annotations

import json
from pathlib import Path

from common import atomic_write_json, now_iso


SCHEMA = "e2e-dev-harness.event.v1"


def events_dir(run_dir: Path) -> Path:
    return run_dir / "events"


def _slug(value: str) -> str:
    return (value or "event").strip().lower().replace("_", "-").replace(" ", "-")


def read_events(run_dir: Path) -> list[dict]:
    directory = events_dir(run_dir)
    if not directory.exists():
        return []
    events: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            data.setdefault("path", path.name)
            events.append(data)
    return events


def append_event(run_dir: Path, event: str, payload: dict | None = None) -> Path:
    directory = events_dir(run_dir)
    directory.mkdir(parents=True, exist_ok=True)
    sequence = len(list(directory.glob("*.json"))) + 1
    path = directory / f"{sequence:06d}-{_slug(event)}.json"
    data = {
        "schema": SCHEMA,
        "sequence": sequence,
        "event": event,
        "created_at": now_iso(),
    }
    for key, value in (payload or {}).items():
        if key not in data:
            data[key] = value
    atomic_write_json(path, data)
    return path


def append_command_event(
    run_dir: Path,
    command: str,
    lifecycle: str,
    status: str,
    blocked_reason_codes: list[str] | None = None,
    next_command: str = "",
    trace_id: str = "",
) -> Path:
    return append_event(
        run_dir,
        "command_observed",
        {
            "run_id": str(run_dir).replace("\\", "/"),
            "trace_id": trace_id,
            "command": command,
            "lifecycle": lifecycle,
            "status": status,
            "blocked_reason_codes": blocked_reason_codes or [],
            "next_command": next_command,
        },
    )


def replay_dispatch_status(events: list[dict]) -> dict[str, dict]:
    dispatches: dict[str, dict] = {}
    status_by_event = {
        "worker_dispatched": "worker_dispatched",
        "worker_acknowledged": "worker_running",
        "worker_completed": "worker_completed",
    }
    for item in events:
        task_id = str(item.get("task_id", "")).strip()
        if not task_id:
            continue
        event = str(item.get("event", "")).strip()
        if event not in status_by_event:
            continue
        dispatches[task_id] = {
            "task_id": task_id,
            "agent": item.get("agent", ""),
            "status": status_by_event[event],
            "event": event,
            "sequence": item.get("sequence", 0),
        }
    return dispatches


def dispatch_snapshot_status(state: dict, task_id: str) -> str:
    dispatches = state.get("dispatches") if isinstance(state.get("dispatches"), dict) else {}
    dispatch = dispatches.get(task_id) if isinstance(dispatches.get(task_id), dict) else {}
    top_dispatch = state.get("dispatch") if isinstance(state.get("dispatch"), dict) else {}
    if not dispatch and str(top_dispatch.get("current_task_id", "")).strip() == task_id:
        dispatch = top_dispatch
    return str(dispatch.get("status", "")).strip()


def snapshot_mismatches(events: list[dict], state: dict) -> list[str]:
    allowed = {
        "worker_dispatched": {"awaiting_runtime_spawn", "worker_dispatched", "dispatched", "waiting_dispatch"},
        "worker_running": {"worker_running"},
        "worker_completed": {"worker_completed"},
    }
    mismatches: list[str] = []
    for task_id, replay in replay_dispatch_status(events).items():
        replay_status = str(replay.get("status", "")).strip()
        snapshot_status = dispatch_snapshot_status(state, task_id)
        if snapshot_status not in allowed.get(replay_status, {replay_status}):
            mismatches.append(
                f"Task {task_id} event replay status {replay_status} does not match run-state dispatch status {snapshot_status or '<missing>'}."
            )
    return mismatches
