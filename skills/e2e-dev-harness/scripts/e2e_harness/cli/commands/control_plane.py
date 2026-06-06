"""Control-plane repair command facade."""

from __future__ import annotations

from pathlib import Path

from e2e_harness.cli.status import write_status
from e2e_harness.engine import control_plane


def run_repair(repo: Path, run_dir: Path, scope: str) -> dict:
    return control_plane.repair(repo, run_dir, scope=scope)


def run_from_args(args) -> tuple[int, dict]:
    result = run_repair(args.repo, getattr(args, "run_dir"), getattr(args, "scope"))
    write_status(getattr(args, "status_file", None), result)
    return (0 if result.get("ready") else 2), result
