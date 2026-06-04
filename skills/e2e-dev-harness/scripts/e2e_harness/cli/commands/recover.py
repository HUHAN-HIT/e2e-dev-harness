"""Recovery command facade."""

from __future__ import annotations

import json
from pathlib import Path

from e2e_harness.engine import recovery


def run(
    repo: Path,
    state: Path,
    schedule: Path | None = None,
    task_id: str = "",
    agent: str = "",
    evidence: list[str] | None = None,
) -> dict:
    return recovery.plan(repo, state, schedule, task_id, agent, evidence or [])


def _write_status(path: Path | None, result: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_from_args(args) -> tuple[int, dict]:
    result = run(
        args.repo,
        state=args.state,
        schedule=getattr(args, "schedule", None),
        task_id=getattr(args, "task_id", "") or "",
        agent=getattr(args, "agent", "") or "",
        evidence=getattr(args, "evidence", None) or [],
    )
    _write_status(getattr(args, "status_file", None), result)
    return (0 if result["ready"] else 2), result
