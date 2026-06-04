"""Run timeline report engine facade."""

from __future__ import annotations

import json
from pathlib import Path

import event_log
import harness_doctor


def _resolve(repo: Path, value: Path) -> Path:
    return value if value.is_absolute() else repo / value


def _rel(repo: Path, value: Path) -> str:
    try:
        return value.resolve().relative_to(repo.resolve()).as_posix()
    except (OSError, ValueError):
        return value.as_posix()


def _read_lifecycle(state_path: Path) -> str:
    if not state_path.exists():
        return ""
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ""
    return str(data.get("lifecycle", "")).strip() if isinstance(data, dict) else ""


def report(repo: Path, state: Path) -> dict:
    repo = repo.resolve()
    state_path = _resolve(repo, state)
    run_dir = state_path.parent
    timeline = harness_doctor.run_timeline(run_dir)
    events = event_log.read_events(run_dir)
    return {
        "schema": "e2e-dev-harness.timeline-report.v1",
        "ready": True,
        "workflow_stage": "TIMELINE",
        "repo": str(repo),
        "run_id": _rel(repo, run_dir),
        "state": _rel(repo, state_path),
        "lifecycle": _read_lifecycle(state_path),
        "event_count": len(events),
        "timeline_count": len(timeline),
        "latest_event": timeline[-1] if timeline else {},
        "events": timeline,
    }
