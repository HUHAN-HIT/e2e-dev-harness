"""Test-impact command facade."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from e2e_harness.cli.status import write_status


def _legacy_cli():
    return importlib.import_module("e2e_dev_harness")


def run(
    repo: Path,
    changed_files: Path | None = None,
    dependency_report: Path | None = None,
    output: Path | None = None,
    validate_plan: Path | None = None,
    unit_test_evidence: Path | None = None,
    status_file: Path | None = None,
) -> tuple[int, dict]:
    return run_from_args(
        argparse.Namespace(
            repo=repo,
            changed_files=changed_files,
            dependency_report=dependency_report,
            output=output,
            validate_plan=validate_plan,
            unit_test_evidence=unit_test_evidence,
            status_file=status_file,
        )
    )


def run_from_args(args) -> tuple[int, dict]:
    legacy = _legacy_cli()
    repo = legacy.as_repo(args.repo)
    if args.validate_plan:
        result = legacy.test_impact_plan.validate(repo, args.validate_plan, args.unit_test_evidence)
        write_status(args.status_file, result)
        return (0 if result["ready"] else 2), result
    changed_files = legacy.test_impact_plan.parse_changed_files(legacy.resolve_repo_path(repo, args.changed_files))
    result = legacy.test_impact_plan.build_plan(
        repo,
        changed_files,
        legacy.resolve_repo_path(repo, args.dependency_report),
    )
    if args.output:
        output = legacy.require_repo_path(repo, args.output, "test impact output")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_status(args.status_file, result)
    return 0, result
