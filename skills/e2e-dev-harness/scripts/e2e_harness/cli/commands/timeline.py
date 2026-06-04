"""Timeline command facade."""

from __future__ import annotations

from pathlib import Path

from e2e_harness.cli.status import write_status
from e2e_harness.engine import timeline


def run(repo: Path, state: Path) -> dict:
    return timeline.report(repo, state)


def run_from_args(args) -> tuple[int, dict]:
    result = run(args.repo, args.state)
    write_status(getattr(args, "status_file", None), result)
    return (0 if result["ready"] else 2), result
