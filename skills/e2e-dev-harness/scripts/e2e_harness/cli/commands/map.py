"""Navigation map command facade."""

from __future__ import annotations

import argparse
from pathlib import Path

import coordinator_flow


def run(
    repo: Path,
    state: Path,
    runtime: str = "claude-code",
    status_file: Path | None = None,
) -> tuple[int, dict]:
    return run_from_args(
        argparse.Namespace(
            repo=repo,
            state=state,
            runtime=runtime,
            status_file=status_file,
        )
    )


def run_from_args(args) -> tuple[int, dict]:
    code, result = coordinator_flow.evaluate_navigation_state(args)
    navigation = result.get("navigation_map") if isinstance(result.get("navigation_map"), dict) else {}
    if getattr(args, "status_file", None):
        coordinator_flow.write_status(args.status_file, navigation)
    return code, navigation
