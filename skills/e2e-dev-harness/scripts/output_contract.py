#!/usr/bin/env python3
"""Compact stdout contract for coordinator-safe harness commands."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from common import atomic_write_json, now_iso

MAX_COMPACT_CHARS = 8_000
MAX_SUMMARY_ITEMS = 12


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip().lower()).strip("-")
    return slug or "command"


def _resolve(repo: Path, value: str | Path | None) -> Path | None:
    if not value:
        return None
    path = value if isinstance(value, Path) else Path(str(value))
    return path if path.is_absolute() else repo / path


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
    return target


def _limited_list(values: Any, limit: int = MAX_SUMMARY_ITEMS) -> list:
    if not isinstance(values, list):
        return []
    return values[:limit]


def _compact_next(next_action: Any) -> dict:
    if not isinstance(next_action, dict):
        return {}
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


def _artifact_paths(result: dict, full_result_path: Path, coordinator_summary_path: str = "") -> dict:
    artifacts: dict[str, Any] = {"full_result": str(full_result_path)}
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
            artifacts[key] = result[key]
    handoffs = result.get("handoff_artifacts")
    if isinstance(handoffs, dict):
        artifacts["handoff_artifacts"] = handoffs
    if coordinator_summary_path:
        artifacts["coordinator_summary"] = coordinator_summary_path
    return artifacts


def compact_payload(
    repo: Path,
    command: str,
    result: dict,
    full_result_path: Path,
    coordinator_summary_path: str = "",
) -> dict:
    payload = {
        "ready": bool(result.get("ready", False)),
        "blocked_reasons": _limited_list(result.get("blocked_reasons", [])),
        "warnings": _limited_list(result.get("warnings", [])),
        "summary": {
            "command": command,
            "lifecycle": result.get("lifecycle", ""),
            "phase": result.get("phase", ""),
            "message": result.get("message", "") or result.get("next_beat_hint", ""),
            "claimed_tasks": _limited_list(result.get("claimed_tasks", []), 5),
            "blocked_tasks": _limited_list(result.get("blocked_tasks", []), 5),
        },
        "artifact_paths": _artifact_paths(result, full_result_path, coordinator_summary_path),
        "next_action": _compact_next(result.get("next")),
        "full_result_path": str(full_result_path),
        "coordinator_summary_path": coordinator_summary_path,
        "stdout_mode": "compact",
        "truncated": False,
    }
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) <= MAX_COMPACT_CHARS:
        return payload
    payload["truncated"] = True
    payload["warnings"] = payload["warnings"][:3]
    payload["blocked_reasons"] = payload["blocked_reasons"][:5]
    payload["summary"] = {
        "command": command,
        "lifecycle": result.get("lifecycle", ""),
        "message": "Compact stdout truncated; read full_result_path for complete machine-readable output.",
    }
    if len(json.dumps(payload, ensure_ascii=False)) > MAX_COMPACT_CHARS:
        payload["artifact_paths"] = {
            "full_result": str(full_result_path),
            **({"coordinator_summary": coordinator_summary_path} if coordinator_summary_path else {}),
        }
    return payload


def render_json(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)
