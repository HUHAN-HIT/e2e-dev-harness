#!/usr/bin/env python3
"""Strict workflow guard for e2e-dev-harness status artifacts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


APPROVAL_RE = re.compile(r"Approval\s*:\s*(user-approved|approved)", re.IGNORECASE)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path | None) -> str:
    if not path:
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def has_approval(approval_text: str) -> bool:
    return bool(APPROVAL_RE.search(approval_text or ""))


def unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def normalized_agent(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower().replace("_", "-"))


def validate_semantic_reviews(gate: dict, workflow: dict, strict: bool, completion_required: bool) -> list[str]:
    if not strict or not completion_required:
        return []
    blocked: list[str] = []
    if workflow.get("require_semantic_reviews") is not True:
        blocked.append("Strict completion requires independent semantic reviews to be enabled.")
    semantic = gate.get("semantic_reviews")
    if not isinstance(semantic, dict):
        return blocked + ["Strict completion requires semantic review gate evidence."]
    if not semantic.get("ready"):
        blocked.append("Semantic review gate is not ready.")
    covered = set(semantic.get("covered_phases") or [])
    missing = [phase for phase in ("design", "test", "implementation") if phase not in covered]
    if missing:
        blocked.append("Strict completion requires semantic review phases: " + ", ".join(missing))
    for item in semantic.get("items") or []:
        developer = normalized_agent(item.get("developer_agent", ""))
        reviewer = normalized_agent(item.get("reviewer_agent", ""))
        if developer and reviewer and developer == reviewer:
            blocked.append(f"Semantic review phase {item.get('phase', '<unknown>')} is self-review.")
        if item.get("independence") != "independent-agent":
            blocked.append(f"Semantic review phase {item.get('phase', '<unknown>')} is not independent-agent.")
    return blocked


def validate_requirements_archive(gate: dict, workflow: dict, strict: bool, completion_required: bool) -> list[str]:
    if not strict or not completion_required:
        return []
    blocked: list[str] = []
    if workflow.get("require_requirements_archive") is not True:
        blocked.append("Strict completion requires requirements archive validation to be enabled.")
    archive = gate.get("requirements_archive")
    if not isinstance(archive, dict):
        return blocked + ["Strict completion requires requirements archive gate evidence."]
    if not archive.get("ready"):
        blocked.append("Requirements archive gate is not ready.")
        blocked.extend(str(reason) for reason in archive.get("blocked_reasons", []) or [])
    return blocked


def validate_prepare(prepare: dict | None, strict: bool, approval_text: str) -> tuple[list[str], list[str]]:
    blocked: list[str] = []
    warnings: list[str] = []
    approved = has_approval(approval_text)
    if not isinstance(prepare, dict):
        return ["Prepare status is missing; run e2e_dev_harness.py prepare before later phases."], warnings
    if prepare.get("blocked"):
        blocked.append("Prepare phase is blocked.")
    for component in ("agent_instructions", "superpowers", "memory", "orchestration"):
        status = prepare.get(component)
        if isinstance(status, dict) and status.get("blocked"):
            blocked.append(f"Prepare component is blocked: {component}.")
    kg_status = prepare.get("knowledge_graph")
    if isinstance(kg_status, dict) and not kg_status.get("selected_tools"):
        warnings.append("Knowledge graph status has no selected_tools.")
    dependency = prepare.get("cross_service_dependencies")
    if strict:
        if not isinstance(dependency, dict):
            blocked.append("Strict workflow requires cross-service dependency scan status from prepare.")
        elif dependency.get("mode") == "off" or dependency.get("enabled") is False:
            blocked.append("Strict workflow requires dependency scan; --dependency-scan-mode off is not allowed.")
        else:
            if dependency.get("ready") is False:
                blocked.append("Dependency scan is not ready.")
            for question in dependency.get("unresolved_questions", []) or []:
                blocked.append(f"Unresolved dependency question: {question}")
            if not dependency.get("report_paths", {}).get("json") and not approved:
                blocked.append("Strict workflow requires a written cross-service dependency report.")
    return blocked, warnings


def validate_verify_result(
    verify_result: dict,
    strict: bool = False,
    require_completion: bool = False,
    approval_text: str = "",
) -> dict:
    blocked: list[str] = []
    warnings: list[str] = []
    workflow = verify_result.get("workflow") if isinstance(verify_result.get("workflow"), dict) else {}
    phase = workflow.get("phase")
    completion_required = require_completion or phase == "completion"
    approved = has_approval(approval_text)

    if strict:
        if workflow.get("dependency_scan_mode") == "off":
            blocked.append("Strict workflow does not allow --dependency-scan-mode off.")
        if workflow.get("write_dependency_report") is False and not approved:
            blocked.append("Strict workflow requires dependency report writing; --no-write-dependency-report is not allowed.")
        if workflow.get("skip_maven") and not approved:
            blocked.append("Maven verification cannot be skipped in strict workflow.")
        if completion_required and workflow.get("skip_spring_static_check") and not approved:
            blocked.append("Spring static check cannot be skipped in strict completion workflow.")

    prepare_blocked, prepare_warnings = validate_prepare(verify_result.get("prepare"), strict, approval_text)
    blocked.extend(prepare_blocked)
    warnings.extend(prepare_warnings)

    clarification = verify_result.get("clarification")
    if isinstance(clarification, dict) and not clarification.get("ready_for_implementation", False):
        blocked.append("Clarification gate is not ready.")
    elif completion_required and clarification is None:
        blocked.append("Completion workflow requires clarification status.")

    gate = verify_result.get("implementation_gate")
    if completion_required:
        if not isinstance(gate, dict):
            blocked.append("Completion gate result is missing.")
        else:
            if gate.get("phase") != "completion":
                blocked.append("Completion gate was not run with --phase completion.")
            if not gate.get("ready"):
                blocked.append("Completion gate is not ready.")
                blocked.extend(str(reason) for reason in gate.get("blocked_reasons", []) or [])
            blocked.extend(validate_semantic_reviews(gate, workflow, strict, completion_required))
            blocked.extend(validate_requirements_archive(gate, workflow, strict, completion_required))
    elif isinstance(gate, dict) and not gate.get("ready", True):
        blocked.append("Implementation gate is not ready.")
        blocked.extend(str(reason) for reason in gate.get("blocked_reasons", []) or [])

    maven = verify_result.get("maven")
    if strict:
        if not isinstance(maven, dict):
            blocked.append("Maven verification result is missing.")
        elif maven.get("skipped") and not approved:
            blocked.append("Maven verification cannot be skipped in strict workflow.")
        elif not maven.get("skipped") and maven.get("exit_code") != 0:
            blocked.append(f"Maven verification failed with exit_code={maven.get('exit_code')}.")

    return {
        "ready": not blocked,
        "strict": strict,
        "require_completion": completion_required,
        "blocked_reasons": unique(blocked),
        "warnings": unique(warnings),
    }


def validate_status_file(
    repo: Path,
    verify_status: Path,
    strict: bool = False,
    require_completion: bool = False,
    approval_file: Path | None = None,
) -> dict:
    status_path = verify_status if verify_status.is_absolute() else repo / verify_status
    approval_path = approval_file if not approval_file or approval_file.is_absolute() else repo / approval_file
    if not status_path.exists():
        return {
            "ready": False,
            "strict": strict,
            "require_completion": require_completion,
            "verify_status": str(status_path),
            "blocked_reasons": [f"Verify status file not found: {status_path}"],
            "warnings": [],
        }
    result = validate_verify_result(
        read_json(status_path),
        strict=strict,
        require_completion=require_completion,
        approval_text=read_text(approval_path),
    )
    result["verify_status"] = str(status_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--verify-status", required=True, type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--require-completion", action="store_true")
    parser.add_argument("--approval-file", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate_status_file(
        args.repo.resolve(),
        args.verify_status,
        strict=args.strict,
        require_completion=args.require_completion,
        approval_file=args.approval_file,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Workflow guard: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
