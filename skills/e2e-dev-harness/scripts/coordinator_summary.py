#!/usr/bin/env python3
"""Write compact coordinator summaries at lifecycle boundaries."""

from __future__ import annotations

import json
from pathlib import Path

from common import atomic_write_json, now_iso

SCHEMA = "e2e-dev-harness.coordinator-summary.v1"
FILENAME = "coordinator-summary.json"
MAX_SUMMARY_CHARS = 20_000


def summary_path(state_path: Path) -> Path:
    return state_path.parent / FILENAME


def _limited(values, limit: int = 20) -> list:
    return values[:limit] if isinstance(values, list) else []


def _compact_next(next_action: dict | None) -> dict:
    next_action = next_action or {}
    keys = [
        "phase",
        "command",
        "coordinator_mode",
        "orchestration_action",
        "dispatch_runtime",
        "dispatch_command",
        "expected_worker",
    ]
    return {key: next_action[key] for key in keys if key in next_action}


def _compact_execution_packet(packet: dict | None) -> dict:
    packet = packet or {}
    keys = [
        "schema",
        "lifecycle",
        "phase",
        "objective",
        "primary_command",
        "required_actions",
        "required_evidence",
        "forbidden_actions",
        "completion_checks",
        "next_gate",
    ]
    compact = {key: packet[key] for key in keys if key in packet}
    if "evidence_paths" in packet and isinstance(packet["evidence_paths"], dict):
        compact["evidence_paths"] = {
            key: packet["evidence_paths"][key]
            for key in ("run_state", "agent_schedule", "red_test_evidence", "green_test_evidence", "coverage_matrix")
            if key in packet["evidence_paths"]
        }
    return compact


def _active_dispatches(state: dict) -> dict:
    dispatches = state.get("dispatches", {}) if isinstance(state.get("dispatches"), dict) else {}
    return {
        task_id: {
            key: dispatch.get(key, "")
            for key in ("status", "runtime", "current_task_id", "current_agent", "worker_handle", "context_pack", "invocation_path")
            if dispatch.get(key)
        }
        for task_id, dispatch in dispatches.items()
        if isinstance(dispatch, dict) and str(dispatch.get("status", "")).lower() not in {"completed", "cancelled"}
    }


def _manual_recovery_events(state_path: Path) -> list:
    schedule = state_path.parent / "agent-schedule.json"
    if not schedule.exists():
        return []
    try:
        data = json.loads(schedule.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    return _limited(data.get("manual_recovery_events", []))


def _artifact_pointers(state_path: Path, result: dict | None = None, full_result_path: str = "") -> dict:
    result = result or {}
    pointers: dict[str, object] = {"run_state": str(state_path)}
    if full_result_path:
        pointers["full_result"] = full_result_path
    for key in ("phase_lock", "agent_schedule", "agent_schedule_written", "context_pack", "invocation_path", "run_summary_json", "run_summary_md"):
        if result.get(key):
            pointers[key] = result[key]
    handoffs = result.get("handoff_artifacts")
    if isinstance(handoffs, dict):
        pointers["handoff_artifacts"] = handoffs
    return pointers


def write(
    repo: Path,
    state_path: Path,
    state: dict,
    result: dict | None = None,
    full_result_path: str = "",
    next_action: dict | None = None,
) -> dict:
    target = summary_path(state_path if state_path.is_absolute() else repo / state_path)
    result = result or {}
    action = next_action if next_action is not None else result.get("next") if isinstance(result.get("next"), dict) else None
    data = {
        "schema": SCHEMA,
        "run_id": state.get("run_id", result.get("run_id", "")),
        "lifecycle": state.get("lifecycle", result.get("lifecycle", "")),
        "selected_mode": state.get("selected_mode", result.get("selected_mode", "")),
        "ready": bool(result.get("ready", True)),
        "blocked_reasons": _limited(result.get("blocked_reasons", [])),
        "warnings": _limited(result.get("warnings", [])),
        "next_action": _compact_next(action)
        or {"orchestration_action": "phase-transition", "command": "Run e2e_dev_harness.py next to refresh coordinator action."},
        "execution_packet": _compact_execution_packet(result.get("execution_packet")),
        "active_dispatches": _active_dispatches(state),
        "artifact_pointers": _artifact_pointers(target.parent / "run-state.json", result, full_result_path),
        "manual_recovery_events": _manual_recovery_events(target.parent / "run-state.json"),
        "created_at": now_iso(),
        "truncated": False,
    }
    if len(json.dumps(data, ensure_ascii=False)) > MAX_SUMMARY_CHARS:
        data["truncated"] = True
        data["warnings"] = data["warnings"][:5]
        data["blocked_reasons"] = data["blocked_reasons"][:5]
        data["active_dispatches"] = dict(list(data["active_dispatches"].items())[:10])
        data["artifact_pointers"] = {key: value for key, value in data["artifact_pointers"].items() if key in {"run_state", "full_result"}}
    atomic_write_json(target, data)
    return {
        "ready": True,
        "blocked_reasons": [],
        "warnings": [],
        "coordinator_summary": str(target),
        "truncated": bool(data["truncated"]),
    }

