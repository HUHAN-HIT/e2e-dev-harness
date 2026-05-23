#!/usr/bin/env python3
"""Validate design-to-code/test/business coverage before completion."""

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

REQUIRED_COLUMNS = {
    "id",
    "acceptance",
    "use_case",
    "service",
    "tests",
    "code_refs",
    "business_review",
    "status",
}
PASS_STATUSES = {"covered", "done", "pass", "passed", "verified"}
TODO_RE = re.compile(r"\b(todo|tbd|fixme|unresolved|pending)\b|待确认|未确认|未完成", re.IGNORECASE)
REVIEW_RE = re.compile(r"\b(reviewed|verified|approved|pass|passed)\b|已审查|已验证|已确认|通过", re.IGNORECASE)
UNIT_RE = re.compile(r"\b(pass|passed|success|successful|build success|tests run)\b|通过|成功", re.IGNORECASE)


def normalize_header(value: str) -> str:
    value = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "acceptance_criteria": "acceptance",
        "criterion": "acceptance",
        "criteria": "acceptance",
        "use_cases": "use_case",
        "services": "service",
        "test": "tests",
        "ut": "tests",
        "code": "code_refs",
        "code_ref": "code_refs",
        "business": "business_review",
        "review": "business_review",
    }
    return aliases.get(value, value)


def parse_markdown_tables(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line.startswith("|") or index + 1 >= len(lines):
            index += 1
            continue
        separator = lines[index + 1].strip()
        if not separator.startswith("|") or not re.fullmatch(r"[|:\-\s]+", separator):
            index += 1
            continue
        headers = [normalize_header(part) for part in line.strip("|").split("|")]
        index += 2
        while index < len(lines) and lines[index].strip().startswith("|"):
            values = [part.strip() for part in lines[index].strip().strip("|").split("|")]
            row = {header: values[pos] if pos < len(values) else "" for pos, header in enumerate(headers)}
            rows.append(row)
            index += 1
    return rows


def file_ok(path: Path | None, repo: Path, label: str, blocked: list[str]) -> tuple[str | None, str]:
    if not path:
        blocked.append(f"{label} evidence is required.")
        return None, ""
    resolved = path if path.is_absolute() else repo / path
    if not resolved.exists():
        blocked.append(f"{label} evidence is missing or empty: {resolved}")
        return str(resolved), ""
    text = resolved.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        blocked.append(f"{label} evidence is missing or empty: {resolved}")
        return str(resolved), text
    if TODO_RE.search(text):
        blocked.append(f"{label} evidence contains unresolved TODO/TBD markers: {resolved}")
    return str(resolved), text


def validate(
    repo: Path,
    coverage_matrix: Path | None,
    unit_test_evidence: Path | None,
    business_review: Path | None,
    design_doc: Path | None = None,
) -> dict:
    repo = repo.resolve()
    blocked: list[str] = []
    warnings: list[str] = []

    matrix_path = coverage_matrix if coverage_matrix and coverage_matrix.is_absolute() else (repo / coverage_matrix if coverage_matrix else None)
    rows: list[dict[str, str]] = []
    expected_acs: list[str] = []
    missing_acs: list[str] = []
    if not matrix_path:
        blocked.append("Coverage matrix is required.")
    elif not matrix_path.exists():
        blocked.append(f"Coverage matrix not found: {matrix_path}")
    else:
        text = matrix_path.read_text(encoding="utf-8", errors="replace")
        rows = parse_markdown_tables(text)
        if not rows:
            blocked.append(f"Coverage matrix has no Markdown table rows: {matrix_path}")
        else:
            columns = set().union(*(row.keys() for row in rows))
            missing = sorted(REQUIRED_COLUMNS - columns)
            if missing:
                blocked.append("Coverage matrix missing columns: " + ", ".join(missing))
            for row_index, row in enumerate(rows, start=1):
                row_id = row.get("id") or f"row {row_index}"
                for column in sorted(REQUIRED_COLUMNS):
                    if not row.get(column, "").strip():
                        blocked.append(f"Coverage matrix {row_id} missing {column}.")
                status = row.get("status", "").strip().lower()
                if status and status not in PASS_STATUSES:
                    blocked.append(f"Coverage matrix {row_id} status is not covered/verified: {row.get('status')}")
                for column in ("acceptance", "use_case", "tests", "code_refs", "business_review"):
                    value = row.get(column, "")
                    if TODO_RE.search(value):
                        blocked.append(f"Coverage matrix {row_id} has unresolved marker in {column}.")

    if design_doc:
        design_path = design_doc if design_doc.is_absolute() else repo / design_doc
        if not design_path.exists():
            blocked.append(f"Design document not found for acceptance coverage check: {design_path}")
        else:
            expected_acs = clarification_gate.extract_acceptance_criteria(design_path)
            if expected_acs:
                matrix_acs = {
                    clarification_gate.normalize_acceptance_id(row.get("id", ""))
                    for row in rows
                    if row.get("id", "").strip()
                }
                missing_acs = [ac for ac in expected_acs if ac not in matrix_acs]
                if missing_acs:
                    blocked.append(
                        "Coverage matrix missing acceptance criteria from design: " + ", ".join(missing_acs)
                    )

    unit_test_path, unit_text = file_ok(unit_test_evidence, repo, "Unit test", blocked)
    if unit_test_path:
        if not UNIT_RE.search(unit_text):
            blocked.append(f"Unit test evidence must explicitly show tests passed: {unit_test_path}")
    business_review_path, review_text = file_ok(business_review, repo, "Business review", blocked)
    if business_review_path:
        if not REVIEW_RE.search(review_text):
            blocked.append(f"Business review evidence must explicitly say reviewed/verified/approved: {business_review_path}")

    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "coverage_matrix": str(matrix_path) if matrix_path else None,
        "coverage_rows": len(rows),
        "expected_acceptance_ids": expected_acs,
        "missing_acceptance_ids": missing_acs,
        "unit_test_evidence": unit_test_path,
        "business_review": business_review_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--coverage-matrix", type=Path)
    parser.add_argument("--unit-test-evidence", type=Path)
    parser.add_argument("--business-review", type=Path)
    parser.add_argument("--design-doc", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate(args.repo, args.coverage_matrix, args.unit_test_evidence, args.business_review, args.design_doc)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Coverage gate: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
