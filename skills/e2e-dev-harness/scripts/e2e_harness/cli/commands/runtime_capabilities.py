"""Runtime-capability command facade."""

from __future__ import annotations

from e2e_harness.engine import dispatch_engine


def run(runtime: str | None = "claude-code") -> dict:
    return dispatch_engine.runtime_capabilities(runtime)
