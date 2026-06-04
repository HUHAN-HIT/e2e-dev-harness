"""Doctor command facade."""

from __future__ import annotations

from pathlib import Path

from e2e_harness.engine import doctor as doctor_engine


def run(repo: Path, strict: bool = False, state: Path | None = None) -> dict:
    return doctor_engine.evaluate(repo, strict=strict, state=state)
