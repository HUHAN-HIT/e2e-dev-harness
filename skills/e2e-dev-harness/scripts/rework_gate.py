#!/usr/bin/env python3
"""Validate rework-loop artifacts before completion."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REQUIRED_FIELDS = {
    "source": "Source",
    "related_ac": "Related AC",
    "affected_services": "Affected Services",
    "problem_type": "Problem Type",
    "return_phase": "Return Phase",
    "required_red_test": "Required Red Test",
    "evidence": "Evidence",
    "exit_criteria": "Exit Criteria",
    "status": "Status",
}
ROUTE_BY_PROBLEM = {
    "unclear-requirement": "clarify",
    "missing-acceptance": "clarify",
    "missing-use-case": "use-case-design",
    "business-logic-risk": "use-case-design",
    "missing-test": "test-case-design",
    "missing-code": "tdd-implement",
    "test-failure": "tdd-implement",
    "multi-service-contract": "plan",
}
OPEN_STATUSES = {"open", "in-progress", "in_progress", "blocked"}
CLOSED_STATUSES = {"verified", "deferred"}
FIELD_RE = re.compile(r"^\s*-?\s*([A-Za-z][A-Za-z _-]*):\s*(.*?)\s*$")


def normalize_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def normalize_value(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def parse_item(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.lstrip("\ufeff")
        match = FIELD_RE.match(line)
        if not match:
            continue
        key = normalize_key(match.group(1))
        value = match.group(2).strip()
        if key not in fields:
            fields[key] = value
    return fields


def explicit_files(repo: Path, inputs: list[Path] | None) -> list[Path]:
    files: list[Path] = []
    for item in inputs or []:
        resolved = item if item.is_absolute() else repo / item
        if resolved.is_file():
            files.append(resolved)
        elif resolved.is_dir():
            files.extend(sorted(resolved.glob("rework*.md")))
    return sorted(dict.fromkeys(files))


def agent_run_dir_from_path(repo: Path, path: Path | None) -> Path | None:
    if not path:
        return None
    resolved = path if path.is_absolute() else repo / path
    parts = resolved.resolve().parts
    for index in range(len(parts) - 2):
        if parts[index] == "docs" and parts[index + 1] == "agent-runs":
            return Path(*parts[: index + 3])
    return None


def infer_agent_run_dir(repo: Path, anchor_paths: list[Path | None] | None) -> Path | None:
    for path in anchor_paths or []:
        run_dir = agent_run_dir_from_path(repo, path)
        if run_dir:
            return run_dir
    return None


def discovered_files(repo: Path, agent_run_dir: Path | None) -> list[Path]:
    if not agent_run_dir:
        return []
    run_dir = agent_run_dir if agent_run_dir.is_absolute() else repo / agent_run_dir
    candidates: list[Path] = []
    candidates.extend(sorted((run_dir / "rework").glob("rework*.md")) if (run_dir / "rework").exists() else [])
    service_plans = run_dir / "service-plans"
    if service_plans.exists():
        candidates.extend(sorted(service_plans.glob("*/rework*.md")))
    return sorted(dict.fromkeys(candidates))


def has_deferred_approval(fields: dict[str, str]) -> bool:
    approval = fields.get("approval", "").strip().lower()
    return bool(approval) and "approved" in approval


def validate_item(path: Path, fields: dict[str, str]) -> tuple[dict, list[str], bool]:
    blocked: list[str] = []
    normalized = dict(fields)
    missing = [label for key, label in REQUIRED_FIELDS.items() if not fields.get(key, "").strip()]
    if missing:
        blocked.append(f"Rework item {path} missing required fields: {', '.join(missing)}")

    problem_type = normalize_value(fields.get("problem_type", ""))
    return_phase = normalize_value(fields.get("return_phase", ""))
    expected_return_phase = ROUTE_BY_PROBLEM.get(problem_type)
    if problem_type and not expected_return_phase:
        blocked.append(f"Rework item {path} has unknown Problem Type: {fields.get('problem_type')}")
    elif expected_return_phase and return_phase and return_phase != expected_return_phase:
        blocked.append(
            f"Rework item {path} must return to {expected_return_phase} for Problem Type {problem_type}, got {return_phase}."
        )

    status = normalize_value(fields.get("status", ""))
    is_open = status in OPEN_STATUSES
    if status in OPEN_STATUSES:
        blocked.append(f"Rework item {path} is still {status}; return to {expected_return_phase or return_phase or 'the required phase'}.")
    elif status == "deferred" and not has_deferred_approval(fields):
        blocked.append(f"Rework item {path} is deferred without explicit Approval: user-approved.")
    elif status and status not in CLOSED_STATUSES:
        blocked.append(f"Rework item {path} has unsupported Status: {fields.get('status')}")

    normalized.update(
        {
            "path": str(path),
            "problem_type": problem_type,
            "return_phase": return_phase,
            "expected_return_phase": expected_return_phase,
            "status": status,
            "approved_deferred": status == "deferred" and has_deferred_approval(fields),
        }
    )
    return normalized, blocked, is_open


def validate(
    repo: Path,
    rework_dirs: list[Path] | None = None,
    anchor_paths: list[Path | None] | None = None,
) -> dict:
    repo = repo.resolve()
    files = explicit_files(repo, rework_dirs)
    inferred_run_dir = None
    if not rework_dirs:
        inferred_run_dir = infer_agent_run_dir(repo, anchor_paths)
        files = discovered_files(repo, inferred_run_dir)

    blocked: list[str] = []
    items: list[dict] = []
    open_count = 0
    for path in files:
        fields = parse_item(path)
        item, item_blocked, is_open = validate_item(path, fields)
        items.append(item)
        blocked.extend(item_blocked)
        if is_open:
            open_count += 1

    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": [],
        "scanned_files": [str(path) for path in files],
        "inferred_agent_run_dir": str(inferred_run_dir) if inferred_run_dir else None,
        "items": items,
        "open_count": open_count,
        "closed_count": len(items) - open_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--rework-dir", action="append", type=Path)
    parser.add_argument("--anchor-path", action="append", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate(args.repo, args.rework_dir, args.anchor_path)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Rework gate: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
