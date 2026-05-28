#!/usr/bin/env python3
"""Hook-like gates before planning or implementation."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import clarification_gate  # noqa: E402
import checkpoint_gate  # noqa: E402
import contract_gate  # noqa: E402
import coverage_gate  # noqa: E402
import cross_service_dependency_scan  # noqa: E402
import handoff_gate  # noqa: E402
import implementation_manifest as implementation_manifest_gate  # noqa: E402
import memory_capture  # noqa: E402
import requirements_archive as requirements_archive_gate  # noqa: E402
import reviewer_gate  # noqa: E402
import rework_gate  # noqa: E402
import spring_static_check  # noqa: E402
import task_alignment_guard  # noqa: E402
import task_tier  # noqa: E402
import tdd_evidence  # noqa: E402
import test_impact_plan as test_impact_plan_gate  # noqa: E402


@dataclass(frozen=True)
class GateRequest:
    repo: Path
    phase: str
    design_doc: Path | None = None
    kg_status_file: Path | None = None
    red_test_evidence: Path | None = None
    coverage_matrix: Path | None = None
    unit_test_evidence: Path | None = None
    business_review: Path | None = None
    memory_updates: Path | None = None
    skip_spring_static_check: bool = False
    rework_dirs: list[Path] | None = None
    dependency_report: Path | None = None
    implementation_manifest: Path | None = None
    review_dirs: list[Path] | None = None
    handoff_dirs: list[Path] | None = None
    contract_dirs: list[Path] | None = None
    require_contracts: bool = False
    require_handoffs: bool = False
    require_semantic_reviews: bool = True
    review_profile: Path | None = None
    requirements_archive: Path | None = None
    require_requirements_archive: bool = False
    changed_files: Path | None = None
    test_impact_plan: Path | None = None
    base_ref: str | None = None
    checkpoint_mode: str = "off"
    confirmation_dirs: list[Path] | None = None
    require_intent: bool = False
    tdd_mode: str = "basic"
    workflow_tier: str = "basic"


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def find_kg_status_file(repo: Path, explicit: Path | None) -> Path:
    if explicit:
        return explicit if explicit.is_absolute() else repo / explicit
    candidates = [
        repo / "knowledge-graph" / "knowledge-graph-refresh.json",
        repo / "graphify-out" / "knowledge-graph-refresh.json",
        repo / "graphify-out" / "kg-status.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    agent_run_evidence = repo / "docs" / "agent-runs"
    if agent_run_evidence.exists():
        matches = sorted(
            agent_run_evidence.glob("*/evidence/knowledge-graph-refresh.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if matches:
            return matches[0]
    return candidates[0]


def resolve_optional_repo_path(repo: Path, path: Path | None) -> Path | None:
    if not path:
        return None
    return path if path.is_absolute() else repo / path


def read_text_if_exists(path: Path | None) -> str:
    if path and path.exists() and path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    return ""


def load_dependency_report(repo: Path, path: Path | None) -> dict:
    resolved = resolve_optional_repo_path(repo, path)
    if not resolved or not resolved.exists():
        return {}
    data = read_json(resolved)
    return data if isinstance(data, dict) else {}


def discover_test_impact_plan(repo: Path, explicit: Path | None, related_paths: list[Path | None]) -> Path | None:
    if explicit:
        return explicit
    for related in related_paths:
        resolved = resolve_optional_repo_path(repo, related)
        if resolved and resolved.parent.exists():
            candidate = resolved.parent / "test-impact-plan.json"
            if candidate.exists():
                return candidate
    agent_runs = repo / "docs" / "agent-runs"
    if agent_runs.exists():
        matches = sorted(
            agent_runs.glob("*/evidence/test-impact-plan.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if matches:
            return matches[0]
    return None


def evaluate_workflow_tier(repo: Path, requested: str, design_doc: Path | None, dependency_report: Path | None) -> dict:
    design_text = read_text_if_exists(resolve_optional_repo_path(repo, design_doc))
    dependency_data = load_dependency_report(repo, dependency_report)
    return task_tier.evaluate(requested or "auto", design_text, {}, dependency_data)


def default_review_profile() -> Path:
    return SCRIPT_DIR.parent / "review-profiles" / "default.json"


def validate_gate_request(request: GateRequest) -> dict:
    repo = request.repo
    design_doc = request.design_doc
    kg_status_file = request.kg_status_file
    phase = request.phase
    red_test_evidence = request.red_test_evidence
    coverage_matrix = request.coverage_matrix
    unit_test_evidence = request.unit_test_evidence
    business_review = request.business_review
    memory_updates = request.memory_updates
    skip_spring_static_check = request.skip_spring_static_check
    rework_dirs = request.rework_dirs
    dependency_report = request.dependency_report
    implementation_manifest = request.implementation_manifest
    review_dirs = request.review_dirs
    handoff_dirs = request.handoff_dirs
    contract_dirs = request.contract_dirs
    require_contracts = request.require_contracts
    require_handoffs = request.require_handoffs
    review_profile = request.review_profile or default_review_profile()
    requirements_archive = request.requirements_archive
    require_requirements_archive = request.require_requirements_archive
    changed_files = request.changed_files
    test_impact_plan = request.test_impact_plan
    base_ref = request.base_ref
    checkpoint_mode = request.checkpoint_mode
    confirmation_dirs = request.confirmation_dirs
    require_intent = request.require_intent
    tdd_mode = request.tdd_mode
    workflow_tier = request.workflow_tier
    repo = repo.resolve()
    blocked_reasons: list[str] = []
    warnings: list[str] = []
    workflow_tier_result = evaluate_workflow_tier(repo, workflow_tier, design_doc, dependency_report)
    effective_workflow_tier = workflow_tier_result["tier"]
    if effective_workflow_tier in {"critical", "audited"} and tdd_mode == "off":
        blocked_reasons.append("Critical or audited workflow cannot disable TDD evidence; use --tdd-mode auto or strict.")

    design_result = None
    if design_doc:
        design_path = design_doc if design_doc.is_absolute() else repo / design_doc
        if not design_path.exists():
            blocked_reasons.append(f"Design document not found: {design_path}")
        else:
            design_result = clarification_gate.validate(design_path, require_intent=require_intent)
            if not design_result["ready_for_implementation"]:
                blocked_reasons.append("Clarification gate is not ready.")
    else:
        warnings.append("No design document supplied; clarification readiness was not checked.")
        if phase == "completion":
            blocked_reasons.append("Completion phase requires a design document via --design-doc for acceptance coverage checking.")

    kg_path = find_kg_status_file(repo, kg_status_file)
    kg_status = read_json(kg_path) if kg_path.exists() else None
    if not kg_status:
        blocked_reasons.append(f"Knowledge graph status file not found or unreadable: {kg_path}")
    elif not kg_status.get("selected_tools"):
        warnings.append("Knowledge graph status exists, but no graph tools were selected.")

    red_test_result = None
    tdd_result = None
    if phase == "implementation":
        tdd_result = tdd_evidence.validate(
            repo,
            red_test_evidence,
            phase="implementation",
            mode=tdd_mode,
            workflow_tier=effective_workflow_tier,
        )
        if not tdd_result["ready"]:
            blocked_reasons.extend(tdd_result["blocked_reasons"])
        warnings.extend(tdd_result["warnings"])
        red_test_result = tdd_result.get("red_evidence")

    coverage_result = None
    memory_result = None
    spring_result = None
    rework_result = None
    semantic_review_result = None
    dependency_result = None
    implementation_manifest_result = None
    task_alignment_result = None
    test_impact_plan_result = None
    handoff_result = None
    contract_result = None
    requirements_archive_result = None
    checkpoint_result = None

    required_review_phases = {
        "planning": ["design"],
        "implementation": ["design", "test"],
        "completion": ["design", "test", "implementation"],
    }[phase]
    semantic_review_result = reviewer_gate.validate(
        repo,
        review_dirs,
        [red_test_evidence, coverage_matrix, unit_test_evidence, business_review, implementation_manifest, design_doc],
        required_review_phases,
        review_profile,
    )
    if not semantic_review_result["ready"]:
        blocked_reasons.extend(semantic_review_result["blocked_reasons"])
    if handoff_dirs:
        handoff_result = handoff_gate.validate(
            repo,
            handoff_dirs,
            [red_test_evidence, coverage_matrix, unit_test_evidence, business_review, implementation_manifest, design_doc],
            require_handoffs,
        )
        if not handoff_result["ready"]:
            blocked_reasons.extend(handoff_result["blocked_reasons"])
    elif require_handoffs:
        blocked_reasons.append("Required handoff artifacts are missing; pass --handoff-dir for multi-service or split-agent work.")
    contract_result = contract_gate.validate(
        repo,
        contract_dirs,
        [red_test_evidence, coverage_matrix, unit_test_evidence, business_review, implementation_manifest, design_doc],
        require_contracts=require_contracts,
    )
    if not contract_result["ready"]:
        blocked_reasons.extend(contract_result["blocked_reasons"])

    if checkpoint_mode != "off":
        required_phases = checkpoint_gate.DEFAULT_PHASES_BY_GATE[phase]
        checkpoint_result = checkpoint_gate.validate(
            repo,
            confirmation_dirs,
            required_phases,
            "advisory" if checkpoint_mode == "advisory" else "required",
        )
        if checkpoint_mode == "required" and not checkpoint_result["ready"]:
            blocked_reasons.extend(checkpoint_result["blocked_reasons"])
        warnings.extend(checkpoint_result["warnings"])

    if phase == "completion":
        tdd_result = tdd_evidence.validate(
            repo,
            red_test_evidence,
            unit_test_evidence,
            phase="completion",
            mode=tdd_mode,
            workflow_tier=effective_workflow_tier,
        )
        if not tdd_result["ready"]:
            blocked_reasons.extend(tdd_result["blocked_reasons"])
        warnings.extend(tdd_result["warnings"])
        red_test_result = tdd_result.get("red_evidence")
        coverage_result = coverage_gate.validate(repo, coverage_matrix, unit_test_evidence, business_review, design_doc)
        if not coverage_result["ready"]:
            blocked_reasons.extend(coverage_result["blocked_reasons"])
        implementation_manifest_result = implementation_manifest_gate.validate(
            repo,
            implementation_manifest,
            design_doc,
        )
        if not implementation_manifest_result["ready"]:
            blocked_reasons.extend(implementation_manifest_result["blocked_reasons"])
        task_alignment_result = task_alignment_guard.validate(
            repo,
            design_doc,
            implementation_manifest,
            coverage_matrix,
            changed_files,
            base_ref,
        )
        if not task_alignment_result["ready"]:
            blocked_reasons.extend(task_alignment_result["blocked_reasons"])
        warnings.extend(task_alignment_result["warnings"])
        resolved_test_impact_plan = discover_test_impact_plan(
            repo,
            test_impact_plan,
            [unit_test_evidence, coverage_matrix, implementation_manifest, dependency_report],
        )
        test_impact_plan_result = test_impact_plan_gate.validate(repo, resolved_test_impact_plan, unit_test_evidence)
        if resolved_test_impact_plan:
            test_impact_plan_result["path"] = str(
                resolved_test_impact_plan if resolved_test_impact_plan.is_absolute() else repo / resolved_test_impact_plan
            )
        if not test_impact_plan_result["ready"]:
            blocked_reasons.extend(test_impact_plan_result["blocked_reasons"])
        warnings.extend(test_impact_plan_result["warnings"])
        dependency_result = cross_service_dependency_scan.validate_dependency_report(repo, dependency_report, design_doc)
        if not dependency_result["ready"]:
            blocked_reasons.extend(dependency_result["blocked_reasons"])
        if memory_updates:
            memory_path = memory_updates if memory_updates.is_absolute() else repo / memory_updates
            memory_result = memory_capture.validate_proposed_updates(memory_path, repo)
            if not memory_result["ready"]:
                blocked_reasons.extend(memory_result["blocked_reasons"])
        rework_result = rework_gate.validate(
            repo,
            rework_dirs,
            [red_test_evidence, coverage_matrix, unit_test_evidence, business_review, memory_updates, implementation_manifest],
        )
        if not rework_result["ready"]:
            blocked_reasons.extend(rework_result["blocked_reasons"])
        if requirements_archive or require_requirements_archive:
            resolved_archive = requirements_archive or requirements_archive_gate.discover(
                repo,
                [
                    red_test_evidence,
                    coverage_matrix,
                    unit_test_evidence,
                    business_review,
                    memory_updates,
                    implementation_manifest,
                    dependency_report,
                    design_doc,
                ] + list(review_dirs or []) + list(handoff_dirs or []) + list(contract_dirs or []) + list(rework_dirs or []),
            )
            if not resolved_archive:
                blocked_reasons.append("Completion phase requires --requirements-archive when requirements archive is required.")
            else:
                requirements_archive_result = requirements_archive_gate.validate(repo, resolved_archive)
                requirements_archive_result["source"] = "explicit" if requirements_archive else "auto"
                if not requirements_archive_result["ready"]:
                    blocked_reasons.extend(
                        "Requirements archive: " + reason
                        for reason in requirements_archive_result["blocked_reasons"]
                    )
        if not skip_spring_static_check:
            spring_result = spring_static_check.validate(repo)
            if not spring_result["ready"]:
                blocked_reasons.extend(spring_result["blocked_reasons"])

    return {
        "repo": str(repo),
        "phase": phase,
        "ready": not blocked_reasons,
        "blocked_reasons": blocked_reasons,
        "warnings": warnings,
        "workflow_tier": workflow_tier_result,
        "design": design_result,
        "knowledge_graph_status_file": str(kg_path),
        "knowledge_graph_status_loaded": bool(kg_status),
        "red_test_evidence": red_test_result,
        "tdd": tdd_result,
        "coverage": coverage_result,
        "implementation_manifest": implementation_manifest_result,
        "task_alignment": task_alignment_result,
        "test_impact_plan": test_impact_plan_result,
        "dependency_report": dependency_result,
        "memory_updates": memory_result,
        "requirements_archive": requirements_archive_result,
        "checkpoints": checkpoint_result,
        "rework": rework_result,
        "semantic_reviews": semantic_review_result,
        "handoffs": handoff_result,
        "contracts": contract_result,
        "spring_static_check": spring_result,
    }


def validate_gate(
    repo: Path,
    design_doc: Path | None,
    kg_status_file: Path | None,
    phase: str,
    red_test_evidence: Path | None,
    coverage_matrix: Path | None = None,
    unit_test_evidence: Path | None = None,
    business_review: Path | None = None,
    memory_updates: Path | None = None,
    skip_spring_static_check: bool = False,
    rework_dirs: list[Path] | None = None,
    dependency_report: Path | None = None,
    implementation_manifest: Path | None = None,
    review_dirs: list[Path] | None = None,
    handoff_dirs: list[Path] | None = None,
    contract_dirs: list[Path] | None = None,
    require_contracts: bool = False,
    require_handoffs: bool = False,
    require_semantic_reviews: bool = True,
    review_profile: Path | None = None,
    requirements_archive: Path | None = None,
    require_requirements_archive: bool = False,
    changed_files: Path | None = None,
    test_impact_plan: Path | None = None,
    base_ref: str | None = None,
    checkpoint_mode: str = "off",
    confirmation_dirs: list[Path] | None = None,
    require_intent: bool = False,
    tdd_mode: str = "auto",
    workflow_tier: str = "auto",
) -> dict:
    return validate_gate_request(
        GateRequest(
            repo=repo,
            design_doc=design_doc,
            kg_status_file=kg_status_file,
            phase=phase,
            red_test_evidence=red_test_evidence,
            coverage_matrix=coverage_matrix,
            unit_test_evidence=unit_test_evidence,
            business_review=business_review,
            memory_updates=memory_updates,
            skip_spring_static_check=skip_spring_static_check,
            rework_dirs=rework_dirs,
            dependency_report=dependency_report,
            implementation_manifest=implementation_manifest,
            review_dirs=review_dirs,
            handoff_dirs=handoff_dirs,
            contract_dirs=contract_dirs,
            require_contracts=require_contracts,
            require_handoffs=require_handoffs,
            require_semantic_reviews=require_semantic_reviews,
            review_profile=review_profile,
            requirements_archive=requirements_archive,
            require_requirements_archive=require_requirements_archive,
            changed_files=changed_files,
            test_impact_plan=test_impact_plan,
            base_ref=base_ref,
            checkpoint_mode=checkpoint_mode,
            confirmation_dirs=confirmation_dirs,
            require_intent=require_intent,
            tdd_mode=tdd_mode,
            workflow_tier=workflow_tier,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--design-doc", type=Path)
    parser.add_argument("--kg-status-file", type=Path)
    parser.add_argument("--phase", choices=["planning", "implementation", "completion"], default="planning")
    parser.add_argument("--red-test-evidence", type=Path)
    parser.add_argument("--coverage-matrix", type=Path)
    parser.add_argument("--unit-test-evidence", type=Path)
    parser.add_argument("--business-review", type=Path)
    parser.add_argument("--memory-updates", type=Path)
    parser.add_argument("--requirements-archive", type=Path)
    parser.add_argument("--require-requirements-archive", action="store_true")
    parser.add_argument("--dependency-report", type=Path)
    parser.add_argument("--implementation-manifest", type=Path)
    parser.add_argument("--changed-files", type=Path)
    parser.add_argument("--test-impact-plan", type=Path)
    parser.add_argument("--base-ref")
    parser.add_argument("--checkpoint-mode", choices=["off", "advisory", "required"], default="off")
    parser.add_argument("--confirmation-dir", action="append", type=Path)
    parser.add_argument("--require-intent", action="store_true")
    parser.add_argument("--tdd-mode", choices=tdd_evidence.MODES, default="auto")
    parser.add_argument("--workflow-tier", choices=task_tier.TIERS, default="auto")
    parser.add_argument("--rework-dir", action="append", type=Path)
    parser.add_argument("--review-dir", action="append", type=Path)
    parser.add_argument("--review-profile", type=Path)
    parser.add_argument("--handoff-dir", action="append", type=Path)
    parser.add_argument("--contract-dir", action="append", type=Path)
    parser.add_argument("--require-contracts", action="store_true")
    parser.add_argument("--require-handoffs", action="store_true")
    parser.add_argument("--require-semantic-reviews", action="store_true")
    parser.add_argument("--skip-spring-static-check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate_gate_request(
        GateRequest(
            repo=args.repo,
            design_doc=args.design_doc,
            kg_status_file=args.kg_status_file,
            phase=args.phase,
            red_test_evidence=args.red_test_evidence,
            coverage_matrix=args.coverage_matrix,
            unit_test_evidence=args.unit_test_evidence,
            business_review=args.business_review,
            memory_updates=args.memory_updates,
            skip_spring_static_check=args.skip_spring_static_check,
            rework_dirs=args.rework_dir,
            dependency_report=args.dependency_report,
            implementation_manifest=args.implementation_manifest,
            review_dirs=args.review_dir,
            handoff_dirs=args.handoff_dir,
            contract_dirs=args.contract_dir,
            require_contracts=args.require_contracts,
            require_handoffs=args.require_handoffs,
            require_semantic_reviews=args.require_semantic_reviews,
            review_profile=args.review_profile or default_review_profile(),
            requirements_archive=args.requirements_archive,
            require_requirements_archive=args.require_requirements_archive,
            changed_files=args.changed_files,
            test_impact_plan=args.test_impact_plan,
            base_ref=args.base_ref,
            checkpoint_mode=args.checkpoint_mode,
            confirmation_dirs=args.confirmation_dir,
            require_intent=args.require_intent,
            tdd_mode=args.tdd_mode,
            workflow_tier=args.workflow_tier,
        )
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Implementation gate: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
