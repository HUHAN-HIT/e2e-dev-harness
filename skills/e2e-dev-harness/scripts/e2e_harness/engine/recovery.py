"""Recovery engine facade."""

from __future__ import annotations

from pathlib import Path

import harness_doctor


def plan(
    repo: Path,
    state: Path,
    schedule: Path | None = None,
    task_id: str = "",
    agent: str = "",
    evidence: list[str] | None = None,
) -> dict:
    result = harness_doctor.recovery_plan(repo, state, schedule, task_id, agent, evidence or [])
    result["workflow_stage"] = "RECOVER"
    return result
