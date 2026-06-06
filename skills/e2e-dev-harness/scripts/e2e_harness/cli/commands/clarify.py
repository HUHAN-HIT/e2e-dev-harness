"""Clarification command facade."""

from __future__ import annotations

from pathlib import Path

from e2e_harness.engine import clarification_flow


def run(
    repo: Path,
    design_doc: Path,
    run_state: Path | None = None,
    require_intent: bool = True,
    require_user_confirmation: bool = True,
    status_file: Path | None = None,
) -> tuple[int, dict]:
    return clarification_flow.run(
        repo,
        design_doc,
        run_state=run_state,
        require_intent=require_intent,
        require_user_confirmation=require_user_confirmation,
        status_file=status_file,
    )


def run_from_args(args) -> tuple[int, dict]:
    return run(
        getattr(args, "repo"),
        getattr(args, "design_doc"),
        run_state=getattr(args, "run_state", None),
        require_intent=getattr(args, "require_intent", True),
        require_user_confirmation=getattr(args, "require_user_confirmation", True),
        status_file=getattr(args, "status_file", None),
    )
