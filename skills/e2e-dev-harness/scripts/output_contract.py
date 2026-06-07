#!/usr/bin/env python3
"""Compact stdout contract for coordinator-safe harness commands."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from common import atomic_write_json, now_iso

MAX_COMPACT_CHARS = 1_000
MAX_SUMMARY_ITEMS = 12
MAX_COMPACT_STRING_CHARS = 140

WORKFLOW_STAGE_BY_LIFECYCLE = {
    "CREATED": "CLARIFY",
    "CLARIFIED": "PLAN_REVIEW",
    "SERVICE_DESIGN_REQUIRED": "PLAN_REVIEW",
    "PLANNED": "TEST_READY",
    "RED_READY": "TEST_READY",
    "IMPLEMENTED": "IMPLEMENT",
    "REVIEWED": "VERIFY",
    "VERIFIED": "VERIFY",
    "ARCHIVED": "VERIFY",
    "REWORK_REQUIRED": "VERIFY",
    "WAITING_DISPATCH": "TEST_READY",
}


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip().lower()).strip("-")
    return slug or "command"


def _resolve(repo: Path, value: str | Path | None) -> Path | None:
    if not value:
        return None
    path = value if isinstance(value, Path) else Path(str(value))
    return path if path.is_absolute() else repo / path


def _display_path(repo: Path, value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    path = Path(text)
    try:
        resolved = path if path.is_absolute() else repo / path
        return resolved.resolve().relative_to(repo.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def workflow_stage_for_lifecycle(lifecycle: Any) -> str:
    return WORKFLOW_STAGE_BY_LIFECYCLE.get(str(lifecycle or "").strip(), "UNKNOWN")


def _run_dir_from_result(repo: Path, result: dict, args: Any | None = None) -> Path:
    candidates: list[Any] = [
        result.get("run_state"),
        result.get("agent_schedule_written"),
        result.get("schedule"),
        result.get("phase_lock"),
    ]
    handoffs = result.get("handoff_artifacts")
    if isinstance(handoffs, dict):
        candidates.extend([handoffs.get("agent_schedule"), handoffs.get("run_state")])
    if args is not None:
        candidates.extend(
            [
                getattr(args, "state", None),
                getattr(args, "run_state", None),
                getattr(args, "schedule", None),
                getattr(args, "agent_run_dir", None),
            ]
        )
    for candidate in candidates:
        path = _resolve(repo, candidate)
        if not path:
            continue
        normalized = path if path.suffix == "" else path.parent
        parts = [part.lower() for part in normalized.parts]
        if "agent-runs" in parts:
            return normalized
    return repo / ".e2e"


def default_full_result_path(repo: Path, command: str, result: dict, args: Any | None = None) -> Path:
    run_dir = _run_dir_from_result(repo, result, args)
    stamp = now_iso().replace(":", "").replace("-", "").replace("Z", "Z")
    return run_dir / "coordinator-results" / f"{stamp}-{_slug(command)}.json"


def write_full_result(repo: Path, command: str, result: dict, args: Any | None = None) -> Path:
    status_file = getattr(args, "status_file", None) if args is not None else None
    target = _resolve(repo, status_file) if status_file else default_full_result_path(repo, command, result, args)
    if target is None:
        target = default_full_result_path(repo, command, result, args)
    atomic_write_json(target, result)
    append_full_result_index(repo, command, result, target)
    return target


def append_full_result_index(repo: Path, command: str, result: dict, full_result_path: Path) -> Path:
    index_path = full_result_path.parent / "index.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "schema": "e2e-dev-harness.coordinator-result-index.v1",
        "created_at": now_iso(),
        "command": command,
        "workflow_stage": workflow_stage_for_lifecycle(result.get("lifecycle", "")),
        "lifecycle": result.get("lifecycle", ""),
        "ready": bool(result.get("ready", False)),
        "full_result_path": str(full_result_path),
        "display_path": _display_path(repo, full_result_path),
    }
    with index_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
    return index_path


def _limited_list(values: Any, limit: int = MAX_SUMMARY_ITEMS) -> list:
    if not isinstance(values, list):
        return []
    return values[:limit]


def _compact_string(value: Any, limit: int = MAX_COMPACT_STRING_CHARS) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 12)] + "...<truncated>"


def _limited_strings(values: Any, limit: int = MAX_SUMMARY_ITEMS) -> list[str]:
    if not isinstance(values, list):
        return []
    return [_compact_string(value) for value in values[:limit]]


def _compact_next(next_action: Any) -> dict:
    if not isinstance(next_action, dict):
        return {}
    keys = [
        "workflow_stage",
        "phase",
        "command",
        "coordinator_mode",
        "orchestration_action",
        "dispatch_runtime",
        "dispatch_command",
        "expected_worker",
    ]
    compact = {key: next_action[key] for key in keys if key in next_action}
    single = next_action.get("next_single_action")
    if isinstance(single, dict):
        single = single.get("command", "")
    single_text = str(single or "").strip()
    if single_text:
        compact["command"] = single_text
        compact["next_single_action"] = single_text
    return compact


def _compact_execution_packet(packet: Any) -> dict:
    if not isinstance(packet, dict):
        return {}
    keys = [
        "schema",
        "lifecycle",
        "phase",
        "objective",
        "primary_command",
        "exact_next_command",
        "allowed_writes",
        "forbidden_writes",
        "completion_requires",
        "required_actions",
        "required_evidence",
        "forbidden_actions",
        "completion_checks",
        "next_gate",
    ]
    compact = {key: packet[key] for key in keys if key in packet}
    evidence_paths = packet.get("evidence_paths")
    if isinstance(evidence_paths, dict):
        compact["evidence_paths"] = {
            key: evidence_paths[key]
            for key in ("run_state", "agent_schedule", "red_test_evidence", "green_test_evidence", "coverage_matrix")
            if key in evidence_paths
        }
    return compact


def _artifact_paths(repo: Path, result: dict, full_result_path: Path, coordinator_summary_path: str = "") -> dict:
    artifacts: dict[str, Any] = {"full_result": _display_path(repo, full_result_path)}
    for key in (
        "run_state",
        "phase_lock",
        "agent_schedule",
        "agent_schedule_written",
        "context_pack",
        "invocation_path",
        "run_summary_json",
        "run_summary_md",
        "coordinator_summary_path",
    ):
        if result.get(key):
            artifacts[key] = _display_path(repo, result[key])
    handoffs = result.get("handoff_artifacts")
    if isinstance(handoffs, dict):
        artifacts["handoff_artifacts"] = {
            key: _display_path(repo, value)
            for key, value in handoffs.items()
            if isinstance(value, (str, Path))
        }
    if coordinator_summary_path:
        artifacts["coordinator_summary"] = _display_path(repo, coordinator_summary_path)
    return artifacts


def _stdout_path(repo: Path, path: Path | str) -> str:
    value = Path(str(path))
    if "coordinator-results" in value.parts or value.name == "coordinator-summary.json":
        return _display_path(repo, value)
    return str(path)


def _minimal_execution_packet(packet: Any) -> dict:
    if not isinstance(packet, dict):
        return {}
    return {
        key: packet[key]
        for key in ("schema", "lifecycle", "phase", "primary_command", "next_gate")
        if key in packet
    }


def _compact_review_policy(policy: Any) -> dict:
    if not isinstance(policy, dict):
        return {}
    auto_minimum = policy.get("auto_minimum") if isinstance(policy.get("auto_minimum"), dict) else {}
    effective = policy.get("effective") if isinstance(policy.get("effective"), dict) else {}
    compact: dict[str, Any] = {}
    if policy.get("user_requested"):
        compact["user_requested"] = policy["user_requested"]
    if auto_minimum.get("tier"):
        compact["auto_minimum"] = auto_minimum["tier"]
    if effective.get("tier"):
        compact["effective"] = effective["tier"]
    if "downgrade_blocked" in policy:
        compact["downgrade_blocked"] = bool(policy["downgrade_blocked"])
    return compact


def _compact_navigation_map(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    if not any(
        key in value
        for key in ("schema", "you_are_here", "status", "next_single_action", "active_work", "artifacts")
    ):
        return {}
    you_are_here = value.get("you_are_here") if isinstance(value.get("you_are_here"), dict) else {}
    status = value.get("status") if isinstance(value.get("status"), dict) else {}
    next_action = value.get("next_single_action") if isinstance(value.get("next_single_action"), dict) else {}
    artifacts = value.get("artifacts") if isinstance(value.get("artifacts"), dict) else {}
    diagnostics = value.get("diagnostics") if isinstance(value.get("diagnostics"), dict) else {}
    authority = value.get("authority") if isinstance(value.get("authority"), dict) else {}
    result = {
        "you_are_here": {
            key: you_are_here[key]
            for key in ("lifecycle", "workflow_stage", "phase")
            if you_are_here.get(key)
        },
        "status": {
            "ready": bool(status.get("ready", False)),
            "health": status.get("health", "blocked"),
            "blocked_by": _limited_strings(status.get("blocked_by", []), 3),
        },
        "next_single_action": {
            key: next_action[key]
            for key in ("command", "source")
            if next_action.get(key)
        },
        "active_work": _limited_list(value.get("active_work", []), 3),
        "artifacts": {
            key: artifacts[key]
            for key in ("run_state", "coordinator_summary")
            if artifacts.get(key)
        },
    }
    if value.get("state_confidence"):
        result["state_confidence"] = value["state_confidence"]
    compact_diagnostics = {
        key: diagnostics[key]
        for key in ("primary_blocker_code",)
        if diagnostics.get(key)
    }
    if compact_diagnostics:
        result["diagnostics"] = compact_diagnostics
    must_read_paths = _limited_strings(value.get("must_read_paths", []), 3)
    if must_read_paths:
        result["must_read_paths"] = must_read_paths
    if authority.get("primary"):
        result["authority"] = {"primary": authority["primary"]}
    return {key: item for key, item in result.items() if item not in ({}, [])}


def _minimal_navigation_map(value: Any) -> dict:
    compact = _compact_navigation_map(value)
    if not compact:
        return {}
    return {
        key: compact[key]
        for key in ("you_are_here", "status", "next_single_action", "state_confidence", "diagnostics", "must_read_paths", "authority")
        if compact.get(key)
    }


def _tiny_navigation_map(value: Any) -> dict:
    compact = _compact_navigation_map(value)
    if not compact:
        return {}
    result = {
        key: compact[key]
        for key in ("you_are_here", "next_single_action", "state_confidence", "diagnostics", "authority")
        if compact.get(key)
    }
    paths = compact.get("must_read_paths")
    if isinstance(paths, list):
        tiny_paths: list[str] = []
        for path in paths:
            text = str(path)
            if text and (not tiny_paths or "coordinator-summary" in text):
                tiny_paths.append(text)
            if len(tiny_paths) >= 2:
                break
        if tiny_paths:
            result["must_read_paths"] = tiny_paths
    return result


def _navigation_map_source(result: dict) -> Any:
    if isinstance(result.get("navigation_map"), dict):
        return result["navigation_map"]
    if result.get("schema") == "e2e-dev-harness.navigation-map.v1":
        return result
    return {}


def compact_payload(
    repo: Path,
    command: str,
    result: dict,
    full_result_path: Path,
    coordinator_summary_path: str = "",
) -> dict:
    session = result.get("session_checkpoint") if isinstance(result.get("session_checkpoint"), dict) else {}
    coordinator_budget = result.get("coordinator_context_budget")
    if not isinstance(coordinator_budget, dict):
        coordinator_budget = session.get("context_budget") if isinstance(session.get("context_budget"), dict) else {}
    dispatch_packets = result.get("dispatch_packets") if isinstance(result.get("dispatch_packets"), list) else []
    review_policy = _compact_review_policy(result.get("review_policy"))
    navigation_source = _navigation_map_source(result)
    navigation_here = navigation_source.get("you_are_here") if isinstance(navigation_source.get("you_are_here"), dict) else {}
    navigation_status = navigation_source.get("status") if isinstance(navigation_source.get("status"), dict) else {}
    lifecycle = result.get("lifecycle", "") or navigation_here.get("lifecycle", "")
    workflow_stage = navigation_here.get("workflow_stage") or workflow_stage_for_lifecycle(lifecycle)
    ready = bool(result.get("ready", navigation_status.get("ready", False)))
    payload = {
        "ready": ready,
        "workflow_stage": workflow_stage,
        "blocked_reasons": _limited_strings(result.get("blocked_reasons", [])),
        "warnings": _limited_strings(result.get("warnings", [])),
        "summary": {
            "command": command,
            "workflow_stage": workflow_stage,
            "lifecycle": lifecycle,
            "phase": result.get("phase", ""),
            "message": result.get("message", "") or result.get("next_beat_hint", ""),
            "claimed_tasks": _limited_list(result.get("claimed_tasks", []), 5),
            "blocked_tasks": _limited_list(result.get("blocked_tasks", []), 5),
        },
        "artifact_paths": _artifact_paths(repo, result, full_result_path, coordinator_summary_path),
        "next_action": _compact_next(result.get("next")),
        "execution_packet": _compact_execution_packet(result.get("execution_packet")),
        "navigation_map": _compact_navigation_map(navigation_source),
        "checkpoint": session.get("checkpoint", ""),
        "coordinator_context_budget": coordinator_budget,
        "resume_instruction": (
            coordinator_budget.get("resume_instruction")
            or "Resume from the checkpoint and run only the next phase allowed by run-state."
            if session.get("checkpoint")
            else ""
        ),
        "spawn_request_paths": _limited_list(
            [
                packet.get("spawn_request_path", "")
                for packet in dispatch_packets
                if isinstance(packet, dict) and packet.get("spawn_request_path")
            ]
        ),
        "task_prompt_paths": _limited_list(
            [
                packet.get("task_prompt_path", "")
                for packet in dispatch_packets
                if isinstance(packet, dict) and packet.get("task_prompt_path")
            ]
        ),
        "claimed_tasks": _limited_list(result.get("claimed_tasks", []), 5),
        "blocked_tasks": _limited_list(result.get("blocked_tasks", result.get("skipped_tasks", [])), 5),
        "recent_events": _limited_list(result.get("recent_events", []), 5),
        "command_event_path": result.get("command_event_path", ""),
        "full_result_path": str(full_result_path),
        "coordinator_summary_path": str(coordinator_summary_path) if coordinator_summary_path else "",
        "stdout_mode": "compact",
        "truncated": False,
    }
    if review_policy:
        payload["review_policy"] = review_policy
    if not payload["navigation_map"]:
        payload.pop("navigation_map")
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) <= MAX_COMPACT_CHARS:
        return payload
    payload["truncated"] = True
    payload["navigation_map"] = _minimal_navigation_map(navigation_source)
    payload["warnings"] = _limited_strings(payload["warnings"], 3)
    payload["blocked_reasons"] = _limited_strings(payload["blocked_reasons"], 5)
    payload["summary"] = {
        "command": command,
        "workflow_stage": workflow_stage,
        "lifecycle": lifecycle,
        "message": "Compact stdout truncated; read full_result_path for complete machine-readable output.",
    }
    payload["execution_packet"] = _minimal_execution_packet(result.get("execution_packet"))
    payload["claimed_tasks"] = []
    payload["blocked_tasks"] = []
    payload["recent_events"] = []
    payload["spawn_request_paths"] = []
    payload["task_prompt_paths"] = []
    if len(json.dumps(payload, ensure_ascii=False)) > MAX_COMPACT_CHARS:
        payload["artifact_paths"] = {
            "full_result": _display_path(repo, full_result_path),
            **({"coordinator_summary": _display_path(repo, coordinator_summary_path)} if coordinator_summary_path else {}),
        }
    if len(json.dumps(payload, ensure_ascii=False)) > MAX_COMPACT_CHARS:
        payload["next_action"] = {}
        payload["execution_packet"] = _minimal_execution_packet(result.get("execution_packet"))
        payload["navigation_map"] = _minimal_navigation_map(navigation_source)
        payload["coordinator_context_budget"] = {
            key: coordinator_budget[key]
            for key in ("exceeded_limits", "handoff_recommended")
            if key in coordinator_budget
        }
    if len(json.dumps(payload, ensure_ascii=False)) > MAX_COMPACT_CHARS:
        next_action = _compact_next(result.get("next"))
        payload = {
            "ready": ready,
            "workflow_stage": workflow_stage,
            "blocked_reasons": _limited_strings(result.get("blocked_reasons", []), 3),
            "warnings": _limited_strings(result.get("warnings", []), 2),
            "summary": {
                "command": command,
                "workflow_stage": workflow_stage,
                "lifecycle": lifecycle,
                "message": "Read full_result_path for complete machine-readable output.",
            },
            "next_action": {
                key: next_action[key]
                for key in ("workflow_stage", "phase", "command", "orchestration_action", "dispatch_command")
                if key in next_action
            },
            "navigation_map": _minimal_navigation_map(navigation_source),
            "full_result_path": _stdout_path(repo, full_result_path),
            "command_event_path": _stdout_path(repo, result.get("command_event_path", "")) if result.get("command_event_path") else "",
            "coordinator_summary_path": _stdout_path(repo, coordinator_summary_path) if coordinator_summary_path else "",
            "stdout_mode": "compact",
            "truncated": True,
        }
        budget_signal = {
            key: coordinator_budget[key]
            for key in ("exceeded_limits", "handoff_recommended")
            if key in coordinator_budget and coordinator_budget[key]
        }
        if budget_signal:
            payload["coordinator_context_budget"] = budget_signal
        if review_policy:
            payload["review_policy"] = review_policy
        if payload.get("navigation_map") and len(json.dumps(payload, ensure_ascii=False)) > MAX_COMPACT_CHARS:
            payload["navigation_map"] = _tiny_navigation_map(navigation_source)
        map_action = payload.get("navigation_map", {}).get("next_single_action", {})
        if (
            isinstance(map_action, dict)
            and map_action.get("source") == "preflight"
            and workflow_stage != "CLARIFY"
            and len(json.dumps(payload, ensure_ascii=False)) > MAX_COMPACT_CHARS
        ):
            payload["next_action"] = {}
            payload["warnings"] = []
            payload["blocked_reasons"] = []
    return payload


def render_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
