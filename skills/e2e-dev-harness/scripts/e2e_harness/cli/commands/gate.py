"""Implementation gate command facade."""

from __future__ import annotations

import json
from pathlib import Path

import implementation_gate
from e2e_harness.cli.status import write_status
from e2e_harness.engine import state_store


DEFAULT_REVIEW_PROFILE = "skills/e2e-dev-harness/review-profiles/default.json"


def _as_repo(path: Path) -> Path:
    return Path(path).resolve()


def _resolve_repo_path(repo: Path, path: Path | None) -> Path | None:
    if path is None:
        return None
    return path if path.is_absolute() else repo / path


def _require_repo_path(repo: Path, path: Path | None, label: str) -> Path:
    resolved = _resolve_repo_path(repo, path)
    if resolved is None:
        raise ValueError(f"{label} is required")
    return resolved


def run(
    repo: Path,
    phase: str,
    design_doc: Path | None = None,
    kg_status_file: Path | None = None,
    red_test_evidence: Path | None = None,
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
    require_semantic_reviews: bool = False,
    review_profile: Path | None = None,
    requirements_archive: Path | None = None,
    require_requirements_archive: bool = False,
    strict_workflow: bool = False,
    changed_files: list[Path] | None = None,
    test_impact_plan: Path | None = None,
    base_ref: str | None = None,
    checkpoint_mode: str = "off",
    confirmation_dirs: list[Path] | None = None,
    require_intent: bool = False,
    tdd_mode: str = "auto",
    workflow_tier: str = "auto",
    run_state: Path | None = None,
    state: Path | None = None,
    no_harness_state: bool = False,
    harness_state_approval: Path | None = None,
    require_gitnexus_evidence: str = "auto",
    gitnexus_degradation: Path | None = None,
    status_file: Path | None = None,
) -> tuple[int, dict]:
    repo = _as_repo(repo)
    run_state_path = run_state or state
    result = implementation_gate.validate_gate_request(
        implementation_gate.GateRequest(
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
            review_profile=review_profile or Path(DEFAULT_REVIEW_PROFILE),
            requirements_archive=requirements_archive,
            require_requirements_archive=require_requirements_archive or (strict_workflow and phase == "completion"),
            changed_files=changed_files,
            test_impact_plan=test_impact_plan,
            base_ref=base_ref,
            checkpoint_mode=checkpoint_mode,
            confirmation_dirs=confirmation_dirs,
            require_intent=require_intent,
            tdd_mode=tdd_mode,
            workflow_tier=workflow_tier,
            run_state=run_state_path,
            no_harness_state=no_harness_state,
            harness_state_approval=harness_state_approval,
            require_gitnexus_evidence=require_gitnexus_evidence,
            gitnexus_degradation=gitnexus_degradation,
        )
    )
    if result.get("ready"):
        transition_target = {
            "implementation": "IMPLEMENTED",
            "completion": "VERIFIED",
        }.get(phase)
        if transition_target and run_state_path:
            state_file = _require_repo_path(repo, run_state_path, "run state")
            status_evidence = state_file.parent / "evidence" / f"{phase}-gate.json"
            status_evidence.parent.mkdir(parents=True, exist_ok=True)
            status_payload = dict(result)
            status_payload.setdefault("phase", phase)
            status_payload["ready"] = True
            for attr, value in (
                ("red_test_evidence", red_test_evidence),
                ("unit_test_evidence", unit_test_evidence),
                ("implementation_manifest", implementation_manifest),
            ):
                if value:
                    try:
                        resolved = _resolve_repo_path(repo, value)
                        status_payload[attr] = str(resolved.relative_to(repo)) if resolved else str(value)
                    except ValueError:
                        status_payload[attr] = str(value)
            status_evidence.write_text(json.dumps(status_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            transition = state_store.transition_lifecycle(
                repo,
                run_state_path,
                transition_target,
                gate=phase,
                gate_status="passed",
                evidence=_resolve_repo_path(repo, status_evidence),
            )
            result["run_state_transition"] = transition
            if not transition["ready"]:
                result["ready"] = False
                result["blocked_reasons"].extend("Run state transition: " + reason for reason in transition["blocked_reasons"])
    write_status(status_file, result)
    return (0 if result["ready"] else 2), result


def run_from_args(args) -> tuple[int, dict]:
    return run(
        getattr(args, "repo"),
        getattr(args, "phase"),
        design_doc=getattr(args, "design_doc", None),
        kg_status_file=getattr(args, "kg_status_file", None),
        red_test_evidence=getattr(args, "red_test_evidence", None),
        coverage_matrix=getattr(args, "coverage_matrix", None),
        unit_test_evidence=getattr(args, "unit_test_evidence", None),
        business_review=getattr(args, "business_review", None),
        memory_updates=getattr(args, "memory_updates", None),
        skip_spring_static_check=getattr(args, "skip_spring_static_check", False),
        rework_dirs=getattr(args, "rework_dir", None),
        dependency_report=getattr(args, "dependency_report", None),
        implementation_manifest=getattr(args, "implementation_manifest", None),
        review_dirs=getattr(args, "review_dir", None),
        handoff_dirs=getattr(args, "handoff_dir", None),
        contract_dirs=getattr(args, "contract_dir", None),
        require_contracts=getattr(args, "require_contracts", False),
        require_handoffs=getattr(args, "require_handoffs", False),
        require_semantic_reviews=getattr(args, "require_semantic_reviews", False),
        review_profile=getattr(args, "review_profile", None),
        requirements_archive=getattr(args, "requirements_archive", None),
        require_requirements_archive=getattr(args, "require_requirements_archive", False),
        strict_workflow=getattr(args, "strict_workflow", False),
        changed_files=getattr(args, "changed_files", None),
        test_impact_plan=getattr(args, "test_impact_plan", None),
        base_ref=getattr(args, "base_ref", None),
        checkpoint_mode=getattr(args, "checkpoint_mode", "off"),
        confirmation_dirs=getattr(args, "confirmation_dir", None),
        require_intent=getattr(args, "require_intent", False),
        tdd_mode=getattr(args, "tdd_mode", "auto"),
        workflow_tier=getattr(args, "workflow_tier", "auto"),
        run_state=getattr(args, "run_state", None),
        state=getattr(args, "state", None),
        no_harness_state=getattr(args, "no_harness_state", False),
        harness_state_approval=getattr(args, "harness_state_approval", None),
        require_gitnexus_evidence=getattr(args, "require_gitnexus_evidence", "auto"),
        gitnexus_degradation=getattr(args, "gitnexus_degradation", None),
        status_file=getattr(args, "status_file", None),
    )
