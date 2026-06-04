"""Timeline command facade."""

from __future__ import annotations

from pathlib import Path

from e2e_harness.engine import timeline


def run(repo: Path, state: Path) -> dict:
    return timeline.report(repo, state)
