#!/usr/bin/env python3
"""Validate semantic reviewer-agent artifacts before completion."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


REQUIRED_FIELDS = {
    "phase": "Phase",
    "reviewer": "Reviewer",
    "review_request": "Review Request",
    "developer_agent": "Developer Agent",
    "reviewer_agent": "Reviewer Agent",
    "independence": "Independence",
    "context_boundary": "Context Boundary",
    "no_code_changes": "No Code Changes",
    "scope": "Scope",
    "inputs_reviewed": "Inputs Reviewed",
    "findings": "Findings",
    "required_rework": "Required Rework",
    "status": "Status",
}
PHASE_ALIASES = {
    "r1": "design",
    "design-review": "design",
    "requirements-review": "design",
    "r2": "test",
    "test-review": "test",
    "red-test-review": "test",
    "r3": "implementation",
    "implementation-review": "implementation",
    "code-review": "implementation",
}
PASS_STATUSES = {"approved", "verified", "clear", "passed"}
PASS_WITH_REWORK_STATUSES = {"approved-with-rework", "verified-with-rework"}
BLOCK_STATUSES = {"open", "in-progress", "in_progress", "blocked", "changes-requested", "needs-rework"}
NONE_VALUES = {"", "-", "none", "n/a", "na", "no", "no findings", "no rework", "无", "没有"}
INDEPENDENT_VALUES = {"independent-agent", "separate-agent", "subagent", "separate-session", "parallel-agent"}
SELF_REVIEW_VALUES = {"self-review", "same-agent", "developer-agent", "same-session"}
NO_CODE_CHANGE_VALUES = {"confirmed", "true", "yes", "no-code-changes", "read-only", "none"}
REQUEST_REQUIRED_FIELDS = {
    "phase": "Phase",
    "reviewer_role": "Reviewer Role",
    "context_package": "Context Package",
    "forbidden": "Forbidden",
    "output": "Output",
}
FIELD_RE = re.compile(r"^\s*-?\s*([A-Za-z][A-Za-z _-]*):\s*(.*?)\s*$")


def normalize_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def normalize_value(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def normalize_phase(value: str) -> str:
    phase = normalize_value(value)
    return PHASE_ALIASES.get(phase, phase)


def is_none_value(value: str) -> bool:
    return normalize_value(value) in NONE_VALUES


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


def normalize_agent_id(value: str) -> str:
    return re.sub(r"\s+", "", normalize_value(value).strip("<>"))


def resolve_repo_path(repo: Path, value: str) -> Path:
    path = Path(value.strip())
    return path if path.is_absolute() else repo / path


def inside_repo(repo: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(repo.resolve())
        return True
    except ValueError:
        return False


def explicit_files(repo: Path, inputs: list[Path] | None) -> list[Path]:
    files: list[Path] = []
    for item in inputs or []:
        resolved = item if item.is_absolute() else repo / item
        if resolved.is_file():
            files.append(resolved)
        elif resolved.is_dir():
            files.extend(sorted(resolved.glob("*review*.md")))
            files.extend(sorted(resolved.glob("reviews/*review*.md")))
    return sorted(
        path
        for path in dict.fromkeys(files)
        if "review-request" not in path.name.lower()
    )


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
    if (run_dir / "reviews").exists():
        candidates.extend(sorted((run_dir / "reviews").glob("*review*.md")))
    service_plans = run_dir / "service-plans"
    if service_plans.exists():
        candidates.extend(sorted(service_plans.glob("*/reviews/*review*.md")))
    return sorted(dict.fromkeys(candidates))


def validate_item(repo: Path, path: Path, fields: dict[str, str]) -> tuple[dict, list[str]]:
    blocked: list[str] = []
    missing = [label for key, label in REQUIRED_FIELDS.items() if not fields.get(key, "").strip()]
    if missing:
        blocked.append(f"Semantic review {path} missing required fields: {', '.join(missing)}")

    phase = normalize_phase(fields.get("phase", ""))
    status = normalize_value(fields.get("status", ""))
    required_rework = fields.get("required_rework", "")
    developer_agent = fields.get("developer_agent", "").strip()
    reviewer_agent = fields.get("reviewer_agent", "").strip()
    independence = normalize_value(fields.get("independence", ""))
    no_code_changes = normalize_value(fields.get("no_code_changes", ""))
    context_boundary = fields.get("context_boundary", "").strip().lower()
    review_request = fields.get("review_request", "").strip()

    if developer_agent and reviewer_agent and normalize_agent_id(developer_agent) == normalize_agent_id(reviewer_agent):
        blocked.append(f"Semantic review {path} uses the same Developer Agent and Reviewer Agent; self-review is not allowed.")
    if not independence or independence in SELF_REVIEW_VALUES or independence not in INDEPENDENT_VALUES:
        blocked.append(f"Semantic review {path} must declare Independence: independent-agent or equivalent, got {fields.get('independence')}.")
    if not no_code_changes or no_code_changes not in NO_CODE_CHANGE_VALUES:
        blocked.append(f"Semantic review {path} must declare No Code Changes: confirmed/read-only, got {fields.get('no_code_changes')}.")
    if not context_boundary or not ("request" in context_boundary and ("no inherited" in context_boundary or "isolated" in context_boundary)):
        blocked.append(f"Semantic review {path} must use a request-scoped isolated context boundary.")
    if review_request:
        resolved_request = resolve_repo_path(repo, review_request)
        if not inside_repo(repo, resolved_request):
            blocked.append(f"Semantic review {path} references Review Request outside repo: {review_request}")
        elif not resolved_request.exists():
            blocked.append(f"Semantic review {path} references missing Review Request: {review_request}")
        else:
            request_fields = parse_item(resolved_request)
            missing_request = [
                label
                for key, label in REQUEST_REQUIRED_FIELDS.items()
                if not request_fields.get(key, "").strip()
            ]
            if missing_request:
                blocked.append(
                    f"Review Request {resolved_request} missing required fields: {', '.join(missing_request)}"
                )
            request_phase = normalize_phase(request_fields.get("phase", ""))
            if phase and request_phase and phase != request_phase:
                blocked.append(
                    f"Semantic review {path} phase {phase} does not match Review Request phase {request_phase}."
                )
            output = request_fields.get("output", "").strip()
            if output:
                resolved_output = resolve_repo_path(repo, output)
                if not inside_repo(repo, resolved_output):
                    blocked.append(f"Review Request {resolved_request} declares output outside repo: {output}")
                elif resolved_output.resolve() != path.resolve():
                    blocked.append(f"Semantic review {path} is not the declared Review Request output: {output}")
    if status in BLOCK_STATUSES:
        blocked.append(f"Semantic review {path} is still {status}; create rework items and return to the required phase.")
    elif status in PASS_WITH_REWORK_STATUSES and is_none_value(required_rework):
        blocked.append(f"Semantic review {path} is {status} but Required Rework is empty.")
    elif status and status not in PASS_STATUSES and status not in PASS_WITH_REWORK_STATUSES:
        blocked.append(f"Semantic review {path} has unsupported Status: {fields.get('status')}")

    item = dict(fields)
    item.update(
        {
            "path": str(path),
            "phase": phase,
            "status": status,
            "developer_agent": developer_agent,
            "reviewer_agent": reviewer_agent,
            "independence": independence,
            "review_request": review_request,
            "has_required_rework": not is_none_value(required_rework),
        }
    )
    return item, blocked


def validate(
    repo: Path,
    review_dirs: list[Path] | None = None,
    anchor_paths: list[Path | None] | None = None,
    require_phases: list[str] | None = None,
) -> dict:
    repo = repo.resolve()
    files = explicit_files(repo, review_dirs)
    inferred_run_dir = None
    if not review_dirs:
        inferred_run_dir = infer_agent_run_dir(repo, anchor_paths)
        files = discovered_files(repo, inferred_run_dir)

    required = [normalize_phase(phase) for phase in require_phases or []]
    blocked: list[str] = []
    items: list[dict] = []
    covered: set[str] = set()
    for path in files:
        fields = parse_item(path)
        item, item_blocked = validate_item(repo, path, fields)
        items.append(item)
        blocked.extend(item_blocked)
        if item.get("phase"):
            covered.add(item["phase"])

    missing_phases = [phase for phase in required if phase not in covered]
    if missing_phases:
        blocked.append("Missing required semantic review phases: " + ", ".join(missing_phases))

    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": [],
        "scanned_files": [str(path) for path in files],
        "inferred_agent_run_dir": str(inferred_run_dir) if inferred_run_dir else None,
        "covered_phases": sorted(covered),
        "required_phases": required,
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--review-dir", action="append", type=Path)
    parser.add_argument("--anchor-path", action="append", type=Path)
    parser.add_argument("--require-phase", action="append", choices=["design", "test", "implementation"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate(args.repo, args.review_dir, args.anchor_path, args.require_phase)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Semantic review gate: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
