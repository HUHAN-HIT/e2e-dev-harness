"""AC progress command facade."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path

from e2e_harness.cli.status import write_status


def _legacy_cli():
    return importlib.import_module("e2e_dev_harness")


def run(
    repo: Path,
    coverage_matrix: Path,
    implementation_manifest: Path,
    unit_test_evidence: Path,
    design_doc: Path | None = None,
    service_design: Path | None = None,
    status_file: Path | None = None,
) -> tuple[int, dict]:
    return run_from_args(
        argparse.Namespace(
            repo=repo,
            design_doc=design_doc,
            service_design=service_design,
            coverage_matrix=coverage_matrix,
            implementation_manifest=implementation_manifest,
            unit_test_evidence=unit_test_evidence,
            status_file=status_file,
        )
    )


def run_from_args(args) -> tuple[int, dict]:
    legacy = _legacy_cli()
    repo = legacy.as_repo(args.repo)
    result = legacy.ac_progress_gate.validate(
        repo,
        args.design_doc,
        args.service_design,
        args.coverage_matrix,
        args.implementation_manifest,
        args.unit_test_evidence,
    )
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result
