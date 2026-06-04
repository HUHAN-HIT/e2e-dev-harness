"""Runtime-capability command facade."""

from __future__ import annotations

from e2e_harness.cli.status import write_status
from e2e_harness.engine import dispatch_engine


def run(runtime: str | None = "claude-code") -> dict:
    return dispatch_engine.runtime_capabilities(runtime)


def run_from_args(args) -> tuple[int, dict]:
    result = run(getattr(args, "runtime", "claude-code"))
    write_status(getattr(args, "status_file", None), result)
    return 0, result
