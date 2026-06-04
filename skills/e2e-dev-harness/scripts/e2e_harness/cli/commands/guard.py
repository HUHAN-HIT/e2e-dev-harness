"""Guard command facade."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path

from e2e_harness.cli.status import write_status


def _legacy_cli():
    return importlib.import_module("e2e_dev_harness")


def run(
    repo: Path,
    verify_status: Path,
    strict: bool = False,
    require_completion: bool = False,
    approval_file: Path | None = None,
    status_file: Path | None = None,
) -> tuple[int, dict]:
    return run_from_args(
        argparse.Namespace(
            repo=repo,
            verify_status=verify_status,
            strict=strict,
            require_completion=require_completion,
            approval_file=approval_file,
            status_file=status_file,
        )
    )


def run_from_args(args) -> tuple[int, dict]:
    legacy = _legacy_cli()
    repo = legacy.as_repo(args.repo)
    result = legacy.workflow_guard.validate_status_file(
        repo,
        args.verify_status,
        strict=args.strict,
        require_completion=args.require_completion,
        approval_file=args.approval_file,
    )
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result
