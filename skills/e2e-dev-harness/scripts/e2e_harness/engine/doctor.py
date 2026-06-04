"""Doctor engine facade."""

from __future__ import annotations

from pathlib import Path

import harness_doctor


def evaluate(repo: Path, strict: bool = False, state: Path | None = None) -> dict:
    return harness_doctor.evaluate(repo, strict, state)
