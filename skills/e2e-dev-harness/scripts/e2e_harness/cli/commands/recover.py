"""Recovery command facade."""

from __future__ import annotations

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
