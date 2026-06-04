"""Runtime-capability command facade."""

from __future__ import annotations

import json
from pathlib import Path

from e2e_harness.engine import dispatch_engine


def run(runtime: str | None = "claude-code") -> dict:
    return dispatch_engine.runtime_capabilities(runtime)


def _write_status(path: Path | None, result: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_from_args(args) -> tuple[int, dict]:
    result = run(getattr(args, "runtime", "claude-code"))
    _write_status(getattr(args, "status_file", None), result)
    return 0, result
