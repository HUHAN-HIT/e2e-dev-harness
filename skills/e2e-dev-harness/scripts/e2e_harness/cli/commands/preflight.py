"""Preflight command facade."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path

from e2e_harness.cli.status import write_status


def _legacy_cli():
    return importlib.import_module("e2e_dev_harness")


def run(repo: Path, state: Path | None = None, status_file: Path | None = None) -> tuple[int, dict]:
    return run_from_args(
        argparse.Namespace(
            repo=repo,
            state=state,
            status_file=status_file,
        )
    )


def run_from_args(args) -> tuple[int, dict]:
    legacy = _legacy_cli()
    repo = legacy.as_repo(args.repo)
    result = legacy.aggregate_preflight_blockers(repo, getattr(args, "state", None))
    write_status(getattr(args, "status_file", None), result)
    return (0 if result["ready"] else 2), result
