"""Doctor command facade."""

from __future__ import annotations

from pathlib import Path

from e2e_harness.cli.status import write_status
from e2e_harness.engine import doctor as doctor_engine


def run(repo: Path, strict: bool = False, state: Path | None = None) -> dict:
    return doctor_engine.evaluate(repo, strict=strict, state=state)


def run_from_args(args) -> tuple[int, dict]:
    result = run(
        args.repo,
        strict=getattr(args, "strict", False),
        state=getattr(args, "state", None),
    )
    write_status(getattr(args, "status_file", None), result)
    return (0 if result["ready"] else 2), result
