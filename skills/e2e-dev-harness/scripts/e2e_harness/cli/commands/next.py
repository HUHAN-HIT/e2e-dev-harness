"""Next command facade."""

from __future__ import annotations

import argparse
from pathlib import Path

import coordinator_flow
from e2e_harness.cli.status import write_status


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
    repo = Path(args.repo).resolve()
    state = Path(args.state)
    resolved_state = state if state.is_absolute() else repo / state
    if not resolved_state.exists():
        start_command = 'e2e-harness start . --feature "<feature>" --request "<request>"'
        state_display = state.as_posix()
        result = {
            "schema": "e2e-dev-harness.next.v1",
            "ready": False,
            "code": "missing_run_state",
            "failure_taxonomy": "missing_run_state",
            "blocker_codes": ["missing_run_state"],
            "blocked_reason_codes": ["missing_run_state"],
            "blocked_reasons": [
                f"Missing run-state: {state_display}. Run start before next."
            ],
            "warnings": [],
            "run_state": state_display,
            "next_single_action": start_command,
            "next": {
                "workflow_stage": "BOOTSTRAP",
                "phase": "start",
                "command": start_command,
                "next_single_action": start_command,
                "orchestration_action": "start-run",
            },
            "navigation_map": {
                "schema": "e2e-dev-harness.navigation-map.v1",
                "you_are_here": {
                    "workflow_stage": "BOOTSTRAP",
                    "phase": "start",
                },
                "status": {
                    "ready": False,
                    "health": "blocked",
                    "blocked_by": ["missing_run_state"],
                },
                "next_single_action": {
                    "command": start_command,
                    "source": "start",
                    "reason": "run-state is missing.",
                },
                "diagnostics": {
                    "primary_blocker_code": "missing_run_state",
                },
                "artifacts": {
                    "run_state": state_display,
                },
            },
            "message": "Run start first, then rerun next with the returned run-state path.",
        }
        write_status(getattr(args, "status_file", None), result)
        return 2, result
    return coordinator_flow.evaluate_navigation_state(args)
