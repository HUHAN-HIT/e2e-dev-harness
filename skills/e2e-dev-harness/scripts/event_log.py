#!/usr/bin/env python3
"""Append-only enterprise event log for harness runs."""

from __future__ import annotations

import json
from pathlib import Path

from common import atomic_write_json, now_iso


SCHEMA = "e2e-dev-harness.event.v1"


def events_dir(run_dir: Path) -> Path:
    return run_dir / "events"


def snapshots_dir(run_dir: Path) -> Path:
    return run_dir / "snapshots"


def _slug(value: str) -> str:
    return (value or "event").strip().lower().replace("_", "-").replace(" ", "-")


def _read_json(path: Path | None) -> dict:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


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
    run_id: str = "",
) -> Path:
    return append_event(
        run_dir,
        "command_observed",
        {
            "run_id": run_id or str(run_dir).replace("\\", "/"),
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


def first_snapshot_mismatch(events: list[dict], state: dict, schedule: dict | None = None) -> dict | None:
    for task_id, replay in replay_dispatch_status(events).items():
        replay_status = str(replay.get("status", "")).strip()
        snapshot_status = dispatch_snapshot_status(state, task_id)
        allowed = {
            "worker_dispatched": {"awaiting_runtime_spawn", "worker_dispatched", "dispatched", "waiting_dispatch"},
            "worker_running": {"worker_running"},
            "worker_completed": {"worker_completed"},
        }.get(replay_status, {replay_status})
        if snapshot_status not in allowed:
            return {
                "task_id": task_id,
                "event": replay.get("event", ""),
                "sequence": replay.get("sequence", 0),
                "event_status": replay_status,
                "snapshot_status": snapshot_status,
                "message": (
                    f"Task {task_id} event replay status {replay_status} does not match "
                    f"run-state dispatch status {snapshot_status or '<missing>'}."
                ),
            }
    return None


def project_run_state_snapshot(events: list[dict], state: dict | None = None) -> dict:
    projected = dict(state or {})
    gates = dict(projected.get("gates", {})) if isinstance(projected.get("gates"), dict) else {}
    dispatches = dict(projected.get("dispatches", {})) if isinstance(projected.get("dispatches"), dict) else {}
    history = list(projected.get("history", [])) if isinstance(projected.get("history"), list) else []
    last_lifecycle_transition = None
    for item in events:
        event = str(item.get("event", "")).strip()
        if event == "lifecycle_transition":
            target = str(item.get("to", "")).strip()
            if target:
                projected["lifecycle"] = target
                last_lifecycle_transition = {
                    "from": item.get("from", ""),
                    "to": target,
                    "gate": item.get("gate", ""),
                    "gate_status": item.get("gate_status", item.get("status", "")),
                    "evidence": item.get("evidence", ""),
                    "updated_at": item.get("created_at", item.get("updated_at", "")),
                }
            gate = str(item.get("gate", "")).strip()
            if gate:
                gates[gate] = str(item.get("gate_status", item.get("status", "passed")) or "passed")
        elif event == "gate_passed":
            gate = str(item.get("gate", "")).strip()
            if gate:
                gates[gate] = "passed"
        elif event == "gate_blocked":
            gate = str(item.get("gate", "")).strip()
            if gate:
                gates[gate] = "blocked"
    for task_id, replay in replay_dispatch_status(events).items():
        current = dict(dispatches.get(task_id, {})) if isinstance(dispatches.get(task_id), dict) else {}
        current.update(
            {
                "current_task_id": task_id,
                "agent": replay.get("agent", current.get("agent", "")),
                "status": replay.get("status", current.get("status", "")),
                "projected_from_event": replay.get("event", ""),
                "projected_sequence": replay.get("sequence", 0),
            }
        )
        dispatches[task_id] = current
    if dispatches:
        projected["dispatches"] = dispatches
        top_dispatch = projected.get("dispatch") if isinstance(projected.get("dispatch"), dict) else {}
        current_task_id = str(top_dispatch.get("current_task_id", "")).strip()
        if current_task_id and isinstance(dispatches.get(current_task_id), dict):
            projected["dispatch"] = dict(dispatches[current_task_id])
    if gates:
        projected["gates"] = gates
    if last_lifecycle_transition:
        history.append(last_lifecycle_transition)
        projected["history"] = history
    projected["source_snapshot"] = "run-state.json"
    projected["projected_from_events"] = len(events)
    return projected


def replay_run_state(events: list[dict], base_state: dict | None = None) -> dict:
    return project_run_state_snapshot(events, base_state)


def project_schedule_snapshot(events: list[dict], schedule: dict | None = None) -> dict:
    projected = dict(schedule or {})
    replay = replay_dispatch_status(events)
    schedule_statuses: dict[str, dict] = {}
    status_by_event = {
        "schedule_task_claimed": "claimed",
        "schedule_task_reclaimed": "claimed",
        "schedule_task_renewed": "claimed",
        "schedule_task_completed": "completed",
        "worker_completed": "completed",
    }
    for item in events:
        event = str(item.get("event", "")).strip()
        task_id = str(item.get("task_id", "")).strip()
        if event in status_by_event and task_id:
            schedule_statuses[task_id] = {
                "status": status_by_event[event],
                "agent": item.get("agent", ""),
                "owner": item.get("agent", ""),
                "evidence": item.get("evidence", []),
                "event": event,
                "sequence": item.get("sequence", 0),
            }
    tasks = []
    changed = False
    for task in projected.get("tasks", []) or []:
        if not isinstance(task, dict):
            tasks.append(task)
            continue
        copy = dict(task)
        status = replay.get(str(copy.get("id", "")).strip(), {}).get("status", "")
        if status == "worker_completed" and str(copy.get("status", "")).lower() != "completed":
            copy["status"] = "completed"
            changed = True
        schedule_status = schedule_statuses.get(str(copy.get("id", "")).strip(), {})
        if schedule_status:
            if copy.get("status") != schedule_status["status"]:
                changed = True
            copy["status"] = schedule_status["status"]
            if schedule_status.get("owner"):
                copy["owner"] = schedule_status["owner"]
            if schedule_status.get("evidence"):
                copy["evidence"] = schedule_status["evidence"]
        tasks.append(copy)
    if tasks or "tasks" in projected:
        projected["tasks"] = tasks
    projected["source_snapshot"] = "agent-schedule.json"
    projected["projected_from_events"] = len(events)
    projected["projection_changed_task_statuses"] = changed
    return projected


def replay_schedule(events: list[dict], base_schedule: dict | None = None) -> dict:
    return project_schedule_snapshot(events, base_schedule)


def write_snapshot_projections(run_dir: Path, state_path: Path | None = None, schedule_path: Path | None = None) -> dict:
    events = read_events(run_dir)
    directory = snapshots_dir(run_dir)
    directory.mkdir(parents=True, exist_ok=True)
    projected_state = project_run_state_snapshot(events, _read_json(state_path))
    projected_schedule = project_schedule_snapshot(events, _read_json(schedule_path))
    state_projection = directory / "run-state.json"
    schedule_projection = directory / "agent-schedule.json"
    atomic_write_json(state_projection, projected_state)
    atomic_write_json(schedule_projection, projected_schedule)
    return {
        "schema": "e2e-dev-harness.snapshot-projection.v1",
        "run_dir": str(run_dir).replace("\\", "/"),
        "events": len(events),
        "snapshots": {
            "run_state": str(state_projection).replace("\\", "/"),
            "agent_schedule": str(schedule_projection).replace("\\", "/"),
        },
    }


def write_compat_snapshots(run_dir: Path, state_path: Path | None = None, schedule_path: Path | None = None) -> dict:
    return write_snapshot_projections(run_dir, state_path, schedule_path)


def append_state_event(
    run_dir: Path,
    event: str,
    payload: dict | None = None,
    state_path: Path | None = None,
    schedule_path: Path | None = None,
) -> Path:
    path = append_event(run_dir, event, payload)
    if state_path or schedule_path:
        write_compat_snapshots(run_dir, state_path, schedule_path)
    return path
