#!/usr/bin/env python3
"""Validate assigned acceptance criteria are complete before R3 review."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import clarification_gate  # noqa: E402
import coverage_gate  # noqa: E402
from common import posix  # noqa: E402


AC_RE = re.compile(r"\bAC-\d+\b", re.IGNORECASE)


def resolve(repo: Path, path: Path | None) -> Path | None:
    if not path:
        return None
    return path if path.is_absolute() else repo / path


def ac_ids_in_text(text: str) -> set[str]:
    return {match.upper() for match in AC_RE.findall(text)}


def assigned_acceptance_ids(design_doc: Path | None, service_design: Path | None) -> list[str]:
    if service_design and service_design.exists():
        text = service_design.read_text(encoding="utf-8", errors="replace")
        ids = sorted(ac_ids_in_text(text))
        if ids:
            return ids
    if design_doc and design_doc.exists():
        return [item["id"].upper() for item in clarification_gate.extract_acceptance_items(design_doc)]
    return []


def coverage_acceptance_ids(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    rows = coverage_gate.parse_markdown_tables(path.read_text(encoding="utf-8", errors="replace"))
    ids: set[str] = set()
    for row in rows:
        value = row.get("id", "")
        normalized = clarification_gate.normalize_acceptance_id(value).upper() if value else ""
        if normalized:
            ids.add(normalized)
        ids.update(ac_ids_in_text(" ".join(str(item) for item in row.values())))
    return ids


def manifest_acceptance_ids(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    rows = coverage_gate.parse_markdown_tables(path.read_text(encoding="utf-8", errors="replace"))
    ids: set[str] = set()
    for row in rows:
        ids.update(ac_ids_in_text(" ".join(str(item) for item in row.values())))
    return ids


def unit_evidence_ready(path: Path | None, repo: Path, blocked: list[str]) -> list[dict]:
    if not path:
        blocked.append("Green/unit test evidence is required before R3 review.")
        return []
    resolved = resolve(repo, path)
    if not resolved or not resolved.exists():
        blocked.append(f"Green/unit test evidence not found: {resolved}")
        return []
    local_blocked: list[str] = []
    entries = coverage_gate.validate_command_evidence(
        resolved.read_text(encoding="utf-8", errors="replace"),
        "Green/unit test",
        local_blocked,
    )
    blocked.extend(local_blocked)
    return entries


def validate(
    repo: Path,
    design_doc: Path | None = None,
    service_design: Path | None = None,
    coverage_matrix: Path | None = None,
    implementation_manifest: Path | None = None,
    unit_test_evidence: Path | None = None,
) -> dict:
    repo = repo.resolve()
    design_path = resolve(repo, design_doc)
    service_design_path = resolve(repo, service_design)
    coverage_path = resolve(repo, coverage_matrix)
    manifest_path = resolve(repo, implementation_manifest)
    unit_path = resolve(repo, unit_test_evidence)
    blocked: list[str] = []
    warnings: list[str] = []
    assigned = assigned_acceptance_ids(design_path, service_design_path)
    if not assigned:
        blocked.append("No assigned acceptance criteria found; provide --design-doc or --service-design.")

    coverage_ids = coverage_acceptance_ids(coverage_path)
    manifest_ids = manifest_acceptance_ids(manifest_path)
    if not coverage_path or not coverage_path.exists():
        blocked.append("Coverage matrix is required before R3 review.")
    if not manifest_path or not manifest_path.exists():
        blocked.append("Implementation manifest is required before R3 review.")

    missing_coverage = [ac_id for ac_id in assigned if ac_id not in coverage_ids]
    missing_manifest = [ac_id for ac_id in assigned if ac_id not in manifest_ids]
    if missing_coverage:
        blocked.append("Assigned ACs missing from coverage matrix before R3: " + ", ".join(missing_coverage))
    if missing_manifest:
        blocked.append("Assigned ACs missing from implementation manifest before R3: " + ", ".join(missing_manifest))
    unit_commands = unit_evidence_ready(unit_path, repo, blocked)
    completed = [
        ac_id
        for ac_id in assigned
        if ac_id in coverage_ids and ac_id in manifest_ids and unit_commands and not blocked
    ]
    if missing_coverage or missing_manifest:
        warnings.append("Continue TDD red/green for remaining assigned ACs; do not ask for R3 review yet.")
    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "design_doc": posix(design_path.relative_to(repo)) if design_path and design_path.exists() else "",
        "service_design": posix(service_design_path.relative_to(repo)) if service_design_path and service_design_path.exists() else "",
        "assigned_acceptance_ids": assigned,
        "completed_acceptance_ids": completed,
        "missing_coverage": missing_coverage,
        "missing_manifest": missing_manifest,
        "unit_test_commands": unit_commands,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--design-doc", type=Path)
    parser.add_argument("--service-design", type=Path)
    parser.add_argument("--coverage-matrix", type=Path)
    parser.add_argument("--implementation-manifest", type=Path)
    parser.add_argument("--unit-test-evidence", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate(
        args.repo,
        args.design_doc,
        args.service_design,
        args.coverage_matrix,
        args.implementation_manifest,
        args.unit_test_evidence,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("AC progress gate: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
