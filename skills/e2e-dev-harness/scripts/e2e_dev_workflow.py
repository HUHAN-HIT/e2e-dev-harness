#!/usr/bin/env python3
"""Unified CLI for the e2e-dev-harness workflow."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import agent_instructions  # noqa: E402
import artifact_registry  # noqa: E402
import clarification_gate  # noqa: E402
import cross_service_dependency_scan  # noqa: E402
import implementation_gate  # noqa: E402
import kg_refresh  # noqa: E402
import handoff_gate  # noqa: E402
import harness_verify  # noqa: E402
import memory_capture  # noqa: E402
import orchestration_plan  # noqa: E402
import run_state  # noqa: E402
import superpowers_probe  # noqa: E402
import task_tier  # noqa: E402
import workflow_guard  # noqa: E402


DEFAULT_REVIEW_PROFILE = "skills/e2e-dev-harness/review-profiles/default.json"
DEFAULT_REVIEW_CHECKLIST = {
    "design": [
        ("ac-completeness", "Acceptance criteria cover goals, non-goals, affected modules, and open questions."),
        ("dependency-impact", "Bounded Impact Summary maps GitNexus/scanner evidence to affected interfaces, ACs, and test obligations."),
        ("security-sensitive-paths", "Security-sensitive behavior and failure paths are identified."),
    ],
    "test": [
        ("happy-and-failure-paths", "Red tests cover meaningful happy and failure paths."),
        ("contract-coverage", "Cross-service HTTP/DMQ contracts have tests or explicit non-applicability."),
        ("security-negative-paths", "Security and permission negative paths are covered when relevant."),
    ],
    "implementation": [
        ("ac-code-path-trace", "For every AC, trace the concrete runtime path from entry point through service/repository/client/sender to output or side effect."),
        ("implementation-completeness", "Implementation covers every AC with concrete code refs, concrete tests, and approved deferrals only."),
        ("security-negative-paths", "Security-sensitive happy/failure paths are implemented and tested."),
        ("project-pattern-consistency", "Code follows existing project patterns and avoids local anti-patterns."),
    ],
}


def as_repo(path: Path) -> Path:
    repo = path.resolve()
    if not repo.exists():
        raise FileNotFoundError(f"Repo not found: {repo}")
    return repo


def resolve_repo_path(repo: Path, path: Path | None) -> Path | None:
    if not path:
        return None
    return path if path.is_absolute() else repo / path


def require_repo_path(repo: Path, path: Path | None, label: str) -> Path:
    resolved = resolve_repo_path(repo, path)
    if resolved is None:
        raise ValueError(f"{label} path is required.")
    repo_root = repo.resolve()
    target = resolved.resolve()
    try:
        target.relative_to(repo_root)
    except ValueError as error:
        raise ValueError(f"{label} path resolves outside repository: {resolved}") from error
    return target


def write_status(path: Path | None, result: dict) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def optional_text(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def without_status_file(args):
    values = vars(args).copy()
    values["status_file"] = None
    return argparse.Namespace(**values)


def superpowers_status(mode: str, phase: str) -> dict:
    if mode == "off":
        return {
            "mode": mode,
            "phase": phase,
            "enabled": False,
            "blocked": False,
            "available": False,
            "message": "Superpowers adapter disabled by policy.",
        }
    result = superpowers_probe.discover()
    if phase != "all":
        result["missing"] = {phase: result["missing"][phase]}
        result["available"] = not result["missing"][phase]
    result.update({
        "mode": mode,
        "phase": phase,
        "enabled": result["available"],
        "blocked": mode == "strict" and not result["available"],
        "message": "Superpowers adapter available." if result["available"] else "Superpowers adapter incomplete or unavailable.",
    })
    return result


def memory_status(repo: Path, mode: str) -> dict:
    if mode == "off":
        return {"mode": mode, "enabled": False, "blocked": False, "message": "Memory adapter disabled by policy."}
    if mode == "strict":
        result = memory_capture.validate_memory(repo)
        result.update({
            "mode": mode,
            "enabled": True,
            "blocked": not result["ready"],
        })
        return result
    result = memory_capture.scan_memory(repo)
    result.update({
        "mode": mode,
        "enabled": True,
        "blocked": False,
    })
    return result


def kg_status(repo: Path, mode: str, facts: dict | None = None) -> dict:
    facts = facts or kg_refresh.detect(repo)
    selected = kg_refresh.choose_tools(mode, facts)
    availability = {"gitnexus": shutil.which("gitnexus"), "graphify": shutil.which("graphify")}
    return {
        "mode": mode,
        "detected": facts,
        "selected_tools": selected,
        "available_tools": availability,
        "suggested_commands": kg_refresh.suggested_commands(selected, facts, availability),
    }


def dependency_scan_status(repo: Path, args) -> dict:
    mode = getattr(args, "dependency_scan_mode", "auto")
    if mode == "off":
        return {
            "mode": mode,
            "enabled": False,
            "ready": True,
            "message": "Cross-service dependency scan disabled by policy.",
        }
    output_dir = resolve_repo_path(repo, getattr(args, "dependency_output_dir", None))
    return cross_service_dependency_scan.scan(
        repo,
        gitnexus_mode=mode,
        graphify_mode="auxiliary",
        write_reports=getattr(args, "write_dependency_report", True),
        output_dir=output_dir,
    )


def workflow_tier_status(repo: Path, args, facts: dict, dependency_scan: dict) -> dict:
    design_text = optional_text(resolve_repo_path(repo, getattr(args, "design_doc", None)))
    return task_tier.evaluate(
        getattr(args, "workflow_tier", "auto"),
        design_text,
        facts,
        dependency_scan,
    )


def orchestration_status(
    repo: Path,
    mode: str,
    design_doc: Path | None,
    agent_run_dir: str | None = None,
    run_date: str | None = None,
    service_scope: str = "auto",
    services_requested: list[str] | None = None,
    paths_requested: list[str] | None = None,
    facts: dict | None = None,
    dependency_report: Path | None = None,
) -> dict:
    if mode == "off":
        return {"requested_mode": mode, "enabled": False, "selected_mode": "off", "blocked": False}
    design_path = resolve_repo_path(repo, design_doc)
    design_text = orchestration_plan.read_design(design_path)
    facts = facts or kg_refresh.detect(repo)
    design_is_template = bool(design_path and "template" in design_path.stem.lower())
    slug = orchestration_plan.feature_slug(design_path)
    dependency_services = orchestration_plan.services_from_dependency_report(resolve_repo_path(repo, dependency_report))
    design_services = [] if design_is_template else orchestration_plan.services_from_design(design_text, facts)
    if service_scope == "auto" and not services_requested and not paths_requested:
        if dependency_services:
            services_requested = dependency_services
        elif design_services:
            services_requested = design_services
    elif service_scope == "affected" and not services_requested and not paths_requested and design_services:
        services_requested = design_services
    services, resolved_service_scope = orchestration_plan.select_services(
        facts,
        services_requested,
        paths_requested,
        service_scope,
    )
    unmatched_services = orchestration_plan.unmatched_requested_services(facts, services_requested)
    if unmatched_services:
        return {
            "repo": str(repo),
            "requested_mode": mode,
            "enabled": True,
            "selected_mode": "blocked",
            "requested_service_scope": service_scope,
            "resolved_service_scope": resolved_service_scope,
            "requested_services": services_requested or [],
            "design_selected_services": design_services,
            "requested_paths": paths_requested or [],
            "selected_services": services,
            "unmatched_requested_services": unmatched_services,
            "blocked": True,
            "blocked_reasons": [
                "Requested services were not found in service_candidates: " + ", ".join(unmatched_services)
            ],
            "detected": orchestration_plan.detection_summary(facts),
            "handoff_artifacts": {},
            "agents": [],
        }
    if resolved_service_scope == "discovery":
        result = orchestration_plan.discovery_result(
            repo,
            mode,
            service_scope,
            services_requested,
            paths_requested,
            facts,
        )
        result.update({"enabled": True, "blocked": False})
        return result
    mode_facts = orchestration_plan.mode_facts_for_service_scope(facts, services, resolved_service_scope)
    selected, reasons = orchestration_plan.choose_mode(mode, mode_facts, design_text, design_is_template)
    artifacts = orchestration_plan.artifacts(slug, agent_run_dir, run_date, services)
    return {
        "requested_mode": mode,
        "enabled": True,
        "selected_mode": selected,
        "requested_service_scope": service_scope,
        "resolved_service_scope": resolved_service_scope,
        "requested_services": services_requested or [],
        "design_selected_services": design_services,
        "requested_paths": paths_requested or [],
        "selected_services": services,
        "reasons": reasons,
        "agent_run_dir": artifacts["agent_run_dir"],
        "handoff_artifacts": artifacts,
        "multi_agent_decision": orchestration_plan.multi_agent_decision(selected, services, reasons),
        "agents": orchestration_plan.agent_plan(selected, artifacts, services),
    }


def align_prepare_scopes(agent_scope: str, service_scope: str) -> tuple[str, str, list[str]]:
    notes: list[str] = []
    effective_agent_scope = agent_scope
    effective_service_scope = service_scope
    if service_scope == "auto" and agent_scope in {"discovery", "affected", "all"}:
        effective_service_scope = agent_scope
        notes.append(f"service-scope inherited from agent-scope: {agent_scope}")
    elif agent_scope == "auto" and service_scope in {"discovery", "affected", "all"}:
        effective_agent_scope = service_scope
        notes.append(f"agent-scope inherited from service-scope: {service_scope}")
    elif (
        agent_scope in {"discovery", "affected", "all"}
        and service_scope in {"discovery", "affected", "all"}
        and agent_scope != service_scope
    ):
        notes.append(
            f"agent-scope and service-scope differ: agent-scope={agent_scope}, service-scope={service_scope}; "
            "keep this only when AGENT loading and service planning intentionally use different boundaries."
        )
    return effective_agent_scope, effective_service_scope, notes


def prepare(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    effective_agent_scope, effective_service_scope, scope_notes = align_prepare_scopes(args.agent_scope, args.service_scope)
    kg_facts = kg_refresh.detect(repo)
    dependency_scan = dependency_scan_status(repo, args)
    dependency_report_path = dependency_scan.get("report_paths", {}).get("json")
    agent = (
        {"mode": args.agent_mode, "enabled": False, "blocked": False}
        if args.agent_mode == "off"
        else agent_instructions.scan(
            repo,
            args.include_agent_content,
            args.max_agent_chars,
            args.path,
            effective_agent_scope,
            args.service,
            args.max_discovered_services,
        )
    )
    if args.agent_mode != "off":
        missing = (
            agent["missing"]["root"]
            or bool(agent["missing"]["services"])
            or bool(agent["missing"].get("requested_services"))
        )
        agent.update({"mode": args.agent_mode, "enabled": True, "blocked": args.agent_mode == "strict" and missing})

    result = {
        "repo": str(repo),
        "scope_alignment": {
            "requested_agent_scope": args.agent_scope,
            "requested_service_scope": args.service_scope,
            "effective_agent_scope": effective_agent_scope,
            "effective_service_scope": effective_service_scope,
            "notes": scope_notes,
        },
        "agent_instructions": agent,
        "superpowers": superpowers_status(args.superpowers_mode, "all"),
        "memory": memory_status(repo, args.memory_mode),
        "orchestration": orchestration_status(
            repo,
            args.agent_orchestration_mode,
            args.design_doc,
            args.agent_run_dir,
            args.run_date,
            effective_service_scope,
            args.service,
            args.path,
            kg_facts,
            Path(dependency_report_path) if dependency_report_path else None,
        ),
        "knowledge_graph": kg_status(repo, args.kg_mode, kg_facts),
        "cross_service_dependencies": dependency_scan,
        "workflow_tier": workflow_tier_status(repo, args, kg_facts, dependency_scan),
    }
    blocked = [
        name
        for name in ("agent_instructions", "superpowers", "memory", "orchestration")
        if result[name].get("blocked")
    ]
    result["blocked"] = bool(blocked)
    result["blocked_components"] = blocked
    write_status(args.status_file, result)
    return (2 if blocked else 0), result


def clarify(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    design_path = resolve_repo_path(repo, args.design_doc)
    if not design_path or not design_path.exists():
        return 2, {"ready_for_implementation": False, "error": f"Design doc not found: {design_path}"}
    result = clarification_gate.validate(design_path)
    run_state_path = getattr(args, "run_state", None)
    if run_state_path and result.get("ready_for_implementation"):
        result["run_state_transition"] = run_state.transition_state(
            repo,
            run_state_path,
            "CLARIFIED",
            gate="clarification",
            gate_status="passed",
            evidence=design_path,
        )
    write_status(args.status_file, result)
    return (0 if result["ready_for_implementation"] else 2), result


def exec_plan_text(repo: Path, design_doc: Path | None, plan: dict) -> str:
    artifacts = plan["handoff_artifacts"]
    decision = plan.get("multi_agent_decision", {})
    agents = "\n".join(
        f"- {agent['name']}: owns {', '.join(agent['owns'])}; gate: {agent['gate']}"
        for agent in plan["agents"]
    )
    service_plans = "\n".join(
        f"- {service}: {paths['service_plan']}"
        for service, paths in artifacts.get("service_plans", {}).items()
    ) or "- None"
    design = str(design_doc or "docs/design/<feature>.md")
    return f"""# ExecPlan

This is a living plan. Keep it current while implementing the feature.

## Design Source

- Design document: {design}
- Repository: {repo}

## Current State

- AGENT instructions loaded:
- Memory reviewed:
- Knowledge graph refreshed:
- Cross-service dependency report:
- Superpowers skills applied:

## Target Behavior

- Goal:
- Non-goals:
- Acceptance criteria:

## Handoff Artifacts

- Agent run directory: {artifacts['agent_run_dir']}
- Run state: {artifacts['run_state']}
- Artifact registry: {artifacts['artifact_registry']}
- Requirements: {artifacts['requirements']}
- Impact summary: {artifacts['impact_summary']}
- Raw impact evidence: {artifacts['impact_evidence']}
- Use cases: {artifacts['use_cases']}
- Test plan: {artifacts['test_plan']}
- Implementation plan: {artifacts['implementation_plan']}
- Implementation manifest: {artifacts['implementation_manifest']}
- Proposed memory updates: {artifacts['proposed_memory_updates']}
- Review requests: {artifacts['review_requests_dir']}
- Semantic reviews: {artifacts['reviews_dir']}
- Rework log: {artifacts['rework_pattern']}
- Cross-service dependencies: {artifacts['dependency_report']}
- Cross-service contracts: {artifacts['contract_pattern']}

## Service Implementation Plans

{service_plans}

## Multi-Agent Decision

- Use multi-agent: {decision.get('use_multi_agent', False)}
- Selected mode: {decision.get('selected_mode', plan.get('selected_mode'))}
- Evidence:
{chr(10).join(f"  - {item}" for item in decision.get('evidence', [])) or "  - None"}
- Required when multi:
{chr(10).join(f"  - {item}" for item in decision.get('required_when_multi', [])) or "  - None"}

## Evidence Paths

- Knowledge graph status: {artifacts['knowledge_graph_status']}
- Dependency report: {artifacts['dependency_report']}
- Impact summary: {artifacts['impact_summary']}
- Raw impact evidence: {artifacts['impact_evidence']}
- Implementation manifest: {artifacts['implementation_manifest']}
- Red test: {artifacts['red_test_evidence']}
- Green test: {artifacts['green_test_evidence']}
- Coverage matrix: {artifacts['coverage_matrix']}
- Business review: {artifacts['business_review']}
- Rework gate: {artifacts['rework_dir']}
- Verification: {artifacts['verification_evidence']}

## Agent Protocol

{agents}

## Milestones

1. Clarify behavior and clear all open questions.
2. Refresh and record knowledge graph findings.
3. Write the first failing test and capture red-test evidence.
4. Implement the smallest change that makes the test pass.
5. Refactor while green and broaden verification.

## Evidence

Record concise command output, graph status, failing-test output, passing-test output, and residual risks here.

## Rework Log

If coverage review, tests, business review, or user review finds a missed requirement or logic issue, create `rework-NNN.md` under the global or service-scoped rework path, route it back to the earliest required phase, and close it as `verified` or explicitly approved `deferred` before reporting done.
"""


def handoff_text(agent_name: str) -> str:
    return f"""---
agent: {agent_name}
agent_id: <agent-id>
status: draft
service_scope: all-services
inputs: []
outputs: []
input_hashes: []
output_hashes: []
blocked_by: []
consumed_by: []
open_questions: <none-before-downstream-consumption>
memory_updates_proposed: []
---

# Agent Handoff

## Summary

## Facts Used

## Decisions Made

## Open Questions

## Downstream Assumptions

## Verification Evidence

## Proposed Memory Updates
"""


def create_handoff_files(repo: Path, artifacts: dict) -> list[str]:
    role_files = {
        "requirements-clarifier": artifacts["requirements"],
        "use-case-designer": artifacts["use_cases"],
        "test-case-developer": artifacts["test_plan"],
        "code-developer": artifacts["implementation_plan"],
    }
    created: list[str] = []
    for role, relative_path in role_files.items():
        path = require_repo_path(repo, Path(relative_path), role)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(handoff_text(role), encoding="utf-8")
            created.append(str(path))
    starter_files = {
        artifacts["design_review_request"]: review_request_template(
            "design",
            "R1 design semantic review request",
            artifacts["design_review"],
            "all-services",
        ),
        artifacts["test_review_request"]: review_request_template(
            "test",
            "R2 test semantic review request",
            artifacts["test_review"],
            "all-services",
        ),
        artifacts["implementation_review_request"]: review_request_template(
            "implementation",
            "R3 implementation semantic review request",
            artifacts["implementation_review"],
            "all-services",
        ),
        artifacts["impact_summary"]: impact_summary_template("all-services", artifacts["impact_evidence"]),
        artifacts["impact_evidence"]: impact_evidence_template(),
        artifacts["implementation_manifest"]: implementation_manifest_template("all-services"),
        artifacts["requirements_archive"]: requirements_archive_template("all-services"),
        artifacts["green_test_evidence"]: unit_test_evidence_template("all-services"),
        artifacts["verification_evidence"]: handoff_text("verification-evidence"),
        artifacts["coverage_matrix"]: coverage_matrix_template("all-services"),
        artifacts["business_review"]: handoff_text("business-logic-review"),
    }
    for relative_path, text in starter_files.items():
        path = require_repo_path(repo, Path(relative_path), "starter artifact")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(text, encoding="utf-8")
            created.append(str(path))
    for service, paths in artifacts.get("service_plans", {}).items():
        service_review_requests = {
            "test_review_request": review_request_template(
                "test",
                f"test-review-request-{service}",
                paths["test_review"],
                service,
            ),
            "implementation_review_request": review_request_template(
                "implementation",
                f"implementation-review-request-{service}",
                paths["implementation_review"],
                service,
            ),
        }
        for key, text in service_review_requests.items():
            path = require_repo_path(repo, Path(paths[key]), f"{service} {key}")
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(text, encoding="utf-8")
                created.append(str(path))
        for key, title in (
            ("service_plan", f"service-plan-{service}"),
            ("code_agent", f"code-developer-{orchestration_plan.service_slug(service)}"),
            ("implementation_manifest", f"implementation-manifest-{service}"),
            ("test_evidence", f"unit-test-evidence-{service}"),
            ("coverage_matrix", f"coverage-{service}"),
            ("business_review", f"business-review-{service}"),
        ):
            path = require_repo_path(repo, Path(paths[key]), f"{service} {key}")
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                if key == "coverage_matrix":
                    path.write_text(coverage_matrix_template(service), encoding="utf-8")
                elif key == "test_evidence":
                    path.write_text(unit_test_evidence_template(service), encoding="utf-8")
                elif key == "implementation_manifest":
                    path.write_text(implementation_manifest_template(service), encoding="utf-8")
                elif key == "service_plan":
                    path.write_text(service_plan_template(service), encoding="utf-8")
                else:
                    path.write_text(handoff_text(title), encoding="utf-8")
                created.append(str(path))
    return created


def coverage_matrix_template(service: str) -> str:
    return f"""# Coverage Matrix: {service}

Each completed row must name concrete test references and concrete production code references.
For MQ/DMQ/Kafka/event ACs, include sender/producer and send/publish/topic/payload evidence.

| id | acceptance | use_case | service | tests | code_refs | business_review | status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AC-1 |  |  | {service} |  |  |  |  |
"""


def impact_summary_template(scope: str, raw_evidence_path: str) -> str:
    return f"""# Impact Summary: {scope}

- Source: GitNexus impact + dependency scanner
- Raw Evidence: {raw_evidence_path}

Keep this summary bounded: list only direct callers/consumers and high-risk indirect effects.
Put full GitNexus/scanner output in the raw evidence file.

| type | interface | affected callers/consumers | related AC | required tests/contracts | risk |
| --- | --- | --- | --- | --- | --- |
| N/A | No public/cross-service/interface impact identified | N/A | AC-1 | N/A | low |
"""


def impact_evidence_template() -> str:
    return json.dumps(
        {
            "source": "gitnexus impact + dependency scanner",
            "commands": [],
            "notes": "Store raw impact output here; keep design docs and handoffs to bounded summaries.",
        },
        indent=2,
    ) + "\n"


def implementation_manifest_template(scope: str) -> str:
    return f"""# Implementation Manifest: {scope}

| id | module | artifact | artifact_type | source | required | tests | status | evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IM-1 | {scope} |  |  | explicit-requirement | yes |  |  |  |
"""


def unit_test_evidence_template(scope: str) -> str:
    return json.dumps(
        {
            "scope": scope,
            "command": "",
            "exit_code": None,
            "stdout_tail": "",
            "stderr_tail": "",
        },
        indent=2,
    ) + "\n"


def requirements_archive_template(scope: str) -> str:
    return f"""# Requirements Archive

## Original Request

## Final Clarified Requirement

## Scope And Non-Goals
Scope: {scope}

## Acceptance Criteria Status
| id | requirement | status | evidence |
| --- | --- | --- | --- |
| AC-1 |  |  |  |

## Use Case Coverage

## Impacted Services APIs And Contracts

## Implementation Evidence
- Implementation manifest:
- Code references:
- AC completion proof:

## Test Evidence
- Red test evidence:
- Green test command JSON:
- Coverage matrix:
- Business review:

## Review And Rework Summary
- R1 design review:
- R2 test review:
- R3 implementation review:
- Rework:

## Deferred And Residual Risks

## Promoted Memory Entries

## Follow Up Opportunities
"""


def review_checklist_template(phase: str) -> str:
    lines = []
    for item_id, description in DEFAULT_REVIEW_CHECKLIST.get(phase, []):
        lines.append(f"- [ ] {item_id}: {description}")
    return "\n".join(lines) or "- [ ] phase-specific-review: Complete the phase-specific review focus."


def review_request_template(phase: str, title: str, output_path: str, scope: str = "all-services") -> str:
    invocation_path = output_path.replace("/reviews/", "/review-invocations/").replace("\\reviews\\", "\\review-invocations\\")
    if invocation_path.endswith(".md"):
        invocation_path = invocation_path[:-3] + "-invocation.json"
    checklist = review_checklist_template(phase)
    return f"""# {title}

- Phase: {phase}
- Reviewer Role: independent semantic reviewer
- Review Profile: {DEFAULT_REVIEW_PROFILE}
- Context Package: request-scoped; no inherited developer chat context
- Allowed Inputs: design doc, AGENT.md files, requirements, impact summary, use cases, test plan, implementation refs, dependency report, service plan for scope
- Forbidden: inherited developer chat context; production-code edits; self-review; writing implementation artifacts
- Output: {output_path}
- Scope: {scope}
- Developer Agent: <developer-agent-id>
- Reviewer Agent: <independent-reviewer-agent-id>
- Reviewer Invocation: {invocation_path}

## Review Assignment

Run this review in an independent reviewer agent. The reviewer may read only the allowed inputs and must write only the declared output review report or rework items requested by the gate.

## Required Review Checklist

The report must include checked `- [x] <id>: ...` lines for each required item:

{checklist}

For implementation reviews, also include:

## Code Path Trace

- AC-1: <entry point> -> <application service> -> <repository/client/sender> -> <response, persistence, or emitted event>.
"""


def semantic_review_template(phase: str, title: str, scope: str = "all-services", request_path: str = "") -> str:
    return f"""# {title}

- Phase: {phase}
- Reviewer: semantic-reviewer
- Review Request: {request_path}
- Developer Agent: <developer-agent-id>
- Reviewer Agent: <independent-reviewer-agent-id>
- Reviewer Session: <reviewer-session-id>
- Request Hash: <sha256-of-review-request-file>
- Independence: independent-agent
- Context Boundary: request-scoped; no inherited developer chat context
- No Code Changes: confirmed
- Scope: {scope}
- Inputs Reviewed:
- Findings:
- Required Rework:
- Status:

## Review Focus

- Requirement/design completeness versus user request.
- Project pattern consistency versus existing similar implementations.
- Security-sensitive happy/failure paths and contract risks.
- Missing artifacts, tests, code refs, or service ownership gaps.
"""


def service_plan_template(service: str) -> str:
    return f"""# Service Implementation Plan: {service}

## Agent Assignment

- Code agent:
- Reviewer agents:
- Mode decision evidence:
- Upstream handoffs consumed:
- Downstream artifacts produced:

## Scope

- Service/module:
- Files allowed to change:
- Shared files allowed to change:
- Out of scope:

## Modification Points

| path | planned change | reason | acceptance/use case |
| --- | --- | --- | --- |
|  |  |  |  |

## Change Logic

- Current behavior:
- Target behavior:
- Runtime path:
- State/data/API/event effects:
- Compatibility or migration notes:

## Implementation Manifest

Copy service/module-local required artifacts into the global `evidence/implementation-manifest.md`.

| id | module | artifact | artifact_type | source | required | tests | status | evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IM-1 | {service} |  |  | explicit-requirement | yes |  |  |  |

## Service-local TDD Plan

| red test | expected failure | implementation target | verification command |
| --- | --- | --- | --- |
|  |  |  | mvn -pl {service} -am test |

## Cross-service Contracts

| dependency/contract | producer | consumer | compatibility rule | verification |
| --- | --- | --- | --- | --- |
|  |  | {service} |  |  |

```mermaid
sequenceDiagram
    participant Caller
    participant Service as {orchestration_plan.service_slug(service)}
    Caller->>Service: request
    Service-->>Caller: response
```

## Data And Transaction Effects

- Tables/entities:
- Events/messages:
- Idempotency/retry/timeout behavior:

## Risks And Rollback

- Risk:
- Mitigation:
- Rollback:

## Completion Evidence

- Red test evidence:
- Green test command JSON:
- Coverage matrix:
- Business review:
"""


def plan(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    kg_facts = kg_refresh.detect(repo)
    result = orchestration_status(
        repo,
        args.mode,
        args.design_doc,
        args.agent_run_dir,
        args.run_date,
        args.service_scope,
        args.service,
        args.path,
        kg_facts,
        getattr(args, "dependency_report", None),
    )
    if (args.create_archive or args.write_exec_plan) and not result.get("handoff_artifacts"):
        result["blocked"] = True
        result["blocked_reasons"] = [
            "Discovery scope does not create ExecPlan or agent-run archives; rerun with --service-scope affected plus --service or --path."
        ]
        write_status(args.status_file, result)
        return 2, result
    if args.create_archive or args.write_exec_plan:
        run_dir = require_repo_path(repo, Path(result["agent_run_dir"]), "agent run directory")
        (run_dir / "handoffs").mkdir(parents=True, exist_ok=True)
        (run_dir / "evidence").mkdir(parents=True, exist_ok=True)
        require_repo_path(repo, Path(result["handoff_artifacts"]["review_requests_dir"]), "review requests directory").mkdir(parents=True, exist_ok=True)
        require_repo_path(repo, Path(result["handoff_artifacts"]["reviews_dir"]), "reviews directory").mkdir(parents=True, exist_ok=True)
        require_repo_path(repo, Path(result["handoff_artifacts"]["rework_dir"]), "rework directory").mkdir(parents=True, exist_ok=True)
        require_repo_path(repo, Path(result["handoff_artifacts"]["contracts_dir"]), "contracts directory").mkdir(parents=True, exist_ok=True)
        result["handoff_files_created"] = create_handoff_files(repo, result["handoff_artifacts"])
        proposed = require_repo_path(repo, Path(result["handoff_artifacts"]["proposed_memory_updates"]), "proposed memory updates")
        if not proposed.exists():
            proposed.write_text("# Proposed Memory Updates\n\n", encoding="utf-8")
        result["agent_run_archive_created"] = str(run_dir)
    if args.write_exec_plan or args.create_archive:
        target = require_repo_path(repo, args.write_exec_plan or Path(result["handoff_artifacts"]["exec_plan"]), "exec plan")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(exec_plan_text(repo, args.design_doc, result), encoding="utf-8")
        result["exec_plan_written"] = str(target)
    if args.create_archive:
        registry_artifacts = dict(result["handoff_artifacts"])
        if args.design_doc:
            registry_artifacts["design_doc"] = str(args.design_doc).replace("\\", "/")
        registry = artifact_registry.build_registry(
            repo,
            result["agent_run_dir"],
            registry_artifacts,
            result.get("selected_mode", ""),
            result.get("selected_services", []),
        )
        registry_path = require_repo_path(repo, Path(result["handoff_artifacts"]["artifact_registry"]), "artifact registry")
        artifact_registry.write_registry(repo, registry_path, registry)
        state = run_state.build_state(
            result["agent_run_dir"],
            result.get("selected_mode", ""),
            result.get("selected_services", []),
            result["handoff_artifacts"]["artifact_registry"],
            lifecycle="PLANNED",
        )
        state_path = require_repo_path(repo, Path(result["handoff_artifacts"]["run_state"]), "run state")
        run_state.write_state(repo, state_path, state)
        result["artifact_registry_written"] = str(registry_path)
        result["run_state_written"] = str(state_path)
    write_status(args.status_file, result)
    return 0, result


def gate(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    result = implementation_gate.validate_gate(
        repo,
        args.design_doc,
        args.kg_status_file,
        args.phase,
        args.red_test_evidence,
        args.coverage_matrix,
        args.unit_test_evidence,
        args.business_review,
        args.memory_updates,
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
        require_requirements_archive=(
            getattr(args, "require_requirements_archive", False)
            or (getattr(args, "strict_workflow", False) and args.phase == "completion")
        ),
    )
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result


def verify(args) -> tuple[int, dict]:
    phase_args = without_status_file(args)
    prepare_code, prep = prepare(phase_args)
    clarify_code = 0
    clarify_result = None
    if args.design_doc:
        clarify_code, clarify_result = clarify(phase_args)
    gate_result = None
    gate_code = 0
    if args.run_gate:
        gate_code, gate_result = gate(phase_args)

    maven_result = {"skipped": True}
    if not args.skip_maven:
        command = ["mvn", "test"] if not args.module else ["mvn", "-pl", args.module, "-am", "test"]
        maven_executable = shutil.which("mvn") or shutil.which("mvn.cmd")
        if not maven_executable:
            maven_result = {
                "skipped": False,
                "command": " ".join(command),
                "exit_code": 127,
                "stdout_tail": "",
                "stderr_tail": "Maven executable not found on PATH. Install Maven or pass --skip-maven only with explicit workflow approval.",
            }
        else:
            command[0] = maven_executable
            completed = subprocess.run(command, cwd=as_repo(args.repo), text=True, capture_output=True)
            display_command = ["mvn"] + command[1:]
            maven_result = {
                "skipped": False,
                "command": " ".join(display_command),
                "exit_code": completed.returncode,
                "stdout_tail": completed.stdout[-4000:],
                "stderr_tail": completed.stderr[-4000:],
            }
    result = {
        "workflow": {
            "strict": getattr(args, "strict_workflow", False),
            "tier": getattr(args, "workflow_tier", "auto"),
            "harness": getattr(args, "harness", False),
            "phase": args.phase,
            "run_gate": args.run_gate,
            "skip_maven": args.skip_maven,
            "skip_spring_static_check": getattr(args, "skip_spring_static_check", False),
            "dependency_scan_mode": getattr(args, "dependency_scan_mode", "auto"),
            "write_dependency_report": getattr(args, "write_dependency_report", True),
            "implementation_manifest": str(getattr(args, "implementation_manifest", "") or ""),
            "require_semantic_reviews": args.phase == "completion" or getattr(args, "require_semantic_reviews", False),
            "require_contracts": getattr(args, "require_contracts", False),
            "require_handoffs": getattr(args, "require_handoffs", False),
            "require_requirements_archive": (
                getattr(args, "require_requirements_archive", False)
                or (getattr(args, "strict_workflow", False) and args.phase == "completion")
            ),
        },
        "prepare": prep,
        "clarification": clarify_result,
        "implementation_gate": gate_result,
        "maven": maven_result,
    }
    exit_code = max(prepare_code, clarify_code, gate_code, maven_result.get("exit_code", 0) if not args.skip_maven else 0)
    if getattr(args, "strict_workflow", False):
        approval_path = resolve_repo_path(as_repo(args.repo), getattr(args, "workflow_approval", None))
        guard_result = workflow_guard.validate_verify_result(
            result,
            strict=True,
            require_completion=args.phase == "completion",
            approval_text=optional_text(approval_path),
        )
        result["workflow_guard"] = guard_result
        if not guard_result["ready"]:
            exit_code = max(exit_code, 2)
    if getattr(args, "harness", False):
        state_path = getattr(args, "state", None)
        if not state_path:
            harness_result = {
                "ready": False,
                "blocked_reasons": ["--harness requires --state docs/agent-runs/<run>/run-state.json."],
                "warnings": [],
            }
        else:
            repo = as_repo(args.repo)
            harness_result = harness_verify.validate(
                repo,
                state_path,
                getattr(args, "policy", None),
                getattr(args, "strict_artifacts", False),
                getattr(args, "run_completion_gate", False),
            )
            summary = harness_verify.write_summary_outputs(
                repo,
                state_path,
                harness_result,
                getattr(args, "summary_json", None),
                getattr(args, "summary_md", None),
            )
            if summary:
                harness_result["run_summary"] = summary
        result["harness"] = harness_result
        if not harness_result["ready"]:
            exit_code = max(exit_code, 2)
    write_status(args.status_file, result)
    return exit_code, result


def guard(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    result = workflow_guard.validate_status_file(
        repo,
        args.verify_status,
        strict=args.strict,
        require_completion=args.require_completion,
        approval_file=args.approval_file,
    )
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result


def add_prepare_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--design-doc", type=Path)
    parser.add_argument("--path", action="append", help="Path that may be touched; can be repeated.")
    parser.add_argument("--service", action="append", help="Affected service directory or service name; can be repeated.")
    parser.add_argument("--agent-mode", choices=["auto", "strict", "optional", "off"], default="strict")
    parser.add_argument("--agent-scope", choices=["auto", "discovery", "affected", "all"], default="auto")
    parser.add_argument("--include-agent-content", action="store_true")
    parser.add_argument("--max-agent-chars", type=int, default=12000)
    parser.add_argument("--max-discovered-services", type=int, default=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT)
    parser.add_argument("--superpowers-mode", choices=["auto", "strict", "optional", "off"], default="auto")
    parser.add_argument("--memory-mode", choices=["auto", "strict", "optional", "off"], default="auto")
    parser.add_argument("--agent-orchestration-mode", choices=["auto", "single", "single-review", "multi", "off"], default="auto")
    parser.add_argument("--service-scope", choices=["auto", "discovery", "affected", "all"], default="auto")
    parser.add_argument("--agent-run-dir", help="Archive directory for generated agent run files.")
    parser.add_argument("--run-date", help="Date prefix for default agent run directory, YYYY-MM-DD.")
    parser.add_argument("--kg-mode", choices=["auto", "gitnexus", "graphify", "both"], default="auto")
    parser.add_argument("--dependency-scan-mode", choices=["auto", "strict", "optional", "off"], default="auto")
    parser.add_argument("--dependency-output-dir", type=Path)
    parser.add_argument("--workflow-tier", choices=task_tier.TIERS, default="auto")
    parser.add_argument("--no-write-dependency-report", dest="write_dependency_report", action="store_false")
    parser.set_defaults(write_dependency_report=True)
    parser.add_argument("--status-file", type=Path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="Run pre-clarification/pre-planning discovery.")
    add_prepare_args(prepare_parser)

    clarify_parser = subparsers.add_parser("clarify", help="Run the clarification gate.")
    clarify_parser.add_argument("repo", nargs="?", default=".", type=Path)
    clarify_parser.add_argument("--design-doc", required=True, type=Path)
    clarify_parser.add_argument("--run-state", type=Path)
    clarify_parser.add_argument("--status-file", type=Path)

    plan_parser = subparsers.add_parser("plan", help="Plan agent orchestration and optionally write an ExecPlan.")
    plan_parser.add_argument("repo", nargs="?", default=".", type=Path)
    plan_parser.add_argument("--mode", choices=["auto", "single", "single-review", "multi"], default="auto")
    plan_parser.add_argument("--design-doc", type=Path)
    plan_parser.add_argument("--agent-run-dir", help="Archive directory for generated agent run files.")
    plan_parser.add_argument("--run-date", help="Date prefix for default agent run directory, YYYY-MM-DD.")
    plan_parser.add_argument("--path", action="append", help="Path that may be touched; can be repeated.")
    plan_parser.add_argument("--service", action="append", help="Affected service directory or service name; can be repeated.")
    plan_parser.add_argument("--service-scope", choices=["auto", "discovery", "affected", "all"], default="auto")
    plan_parser.add_argument("--dependency-report", type=Path)
    plan_parser.add_argument("--workflow-tier", choices=task_tier.TIERS, default="auto")
    plan_parser.add_argument("--create-archive", action="store_true", help="Create agent run archive directories and starter files.")
    plan_parser.add_argument("--write-exec-plan", type=Path)
    plan_parser.add_argument("--status-file", type=Path)

    gate_parser = subparsers.add_parser("gate", help="Run hook-like planning or implementation gates.")
    gate_parser.add_argument("repo", nargs="?", default=".", type=Path)
    gate_parser.add_argument("--design-doc", type=Path)
    gate_parser.add_argument("--kg-status-file", type=Path)
    gate_parser.add_argument("--phase", choices=["planning", "implementation", "completion"], default="planning")
    gate_parser.add_argument("--red-test-evidence", type=Path)
    gate_parser.add_argument("--coverage-matrix", type=Path)
    gate_parser.add_argument("--unit-test-evidence", type=Path)
    gate_parser.add_argument("--business-review", type=Path)
    gate_parser.add_argument("--memory-updates", type=Path)
    gate_parser.add_argument("--requirements-archive", type=Path)
    gate_parser.add_argument("--require-requirements-archive", action="store_true")
    gate_parser.add_argument("--dependency-report", type=Path)
    gate_parser.add_argument("--implementation-manifest", type=Path)
    gate_parser.add_argument("--rework-dir", action="append", type=Path)
    gate_parser.add_argument("--review-dir", action="append", type=Path)
    gate_parser.add_argument("--review-profile", type=Path)
    gate_parser.add_argument("--handoff-dir", action="append", type=Path)
    gate_parser.add_argument("--contract-dir", action="append", type=Path)
    gate_parser.add_argument("--require-contracts", action="store_true")
    gate_parser.add_argument("--require-handoffs", action="store_true")
    gate_parser.add_argument("--require-semantic-reviews", action="store_true")
    gate_parser.add_argument("--skip-spring-static-check", action="store_true")
    gate_parser.add_argument("--status-file", type=Path)

    verify_parser = subparsers.add_parser("verify", help="Run prepare, clarification, optional gate, and optional Maven.")
    add_prepare_args(verify_parser)
    verify_parser.add_argument("--module")
    verify_parser.add_argument("--run-gate", action="store_true")
    verify_parser.add_argument("--phase", choices=["planning", "implementation", "completion"], default="planning")
    verify_parser.add_argument("--kg-status-file", type=Path)
    verify_parser.add_argument("--red-test-evidence", type=Path)
    verify_parser.add_argument("--coverage-matrix", type=Path)
    verify_parser.add_argument("--unit-test-evidence", type=Path)
    verify_parser.add_argument("--business-review", type=Path)
    verify_parser.add_argument("--memory-updates", type=Path)
    verify_parser.add_argument("--requirements-archive", type=Path)
    verify_parser.add_argument("--require-requirements-archive", action="store_true")
    verify_parser.add_argument("--dependency-report", type=Path)
    verify_parser.add_argument("--implementation-manifest", type=Path)
    verify_parser.add_argument("--rework-dir", action="append", type=Path)
    verify_parser.add_argument("--review-dir", action="append", type=Path)
    verify_parser.add_argument("--review-profile", type=Path)
    verify_parser.add_argument("--handoff-dir", action="append", type=Path)
    verify_parser.add_argument("--contract-dir", action="append", type=Path)
    verify_parser.add_argument("--require-contracts", action="store_true")
    verify_parser.add_argument("--require-handoffs", action="store_true")
    verify_parser.add_argument("--require-semantic-reviews", action="store_true")
    verify_parser.add_argument("--skip-spring-static-check", action="store_true")
    verify_parser.add_argument("--skip-maven", action="store_true")
    verify_parser.add_argument("--strict-workflow", action="store_true")
    verify_parser.add_argument("--workflow-approval", type=Path)
    verify_parser.add_argument("--harness", action="store_true")
    verify_parser.add_argument("--state", type=Path)
    verify_parser.add_argument("--policy", type=Path)
    verify_parser.add_argument("--strict-artifacts", action="store_true")
    verify_parser.add_argument("--run-completion-gate", action="store_true")
    verify_parser.add_argument("--summary-json", type=Path)
    verify_parser.add_argument("--summary-md", type=Path)

    guard_parser = subparsers.add_parser("guard", help="Run strict workflow guard against a verify status artifact.")
    guard_parser.add_argument("repo", nargs="?", default=".", type=Path)
    guard_parser.add_argument("--verify-status", required=True, type=Path)
    guard_parser.add_argument("--strict", action="store_true")
    guard_parser.add_argument("--require-completion", action="store_true")
    guard_parser.add_argument("--approval-file", type=Path)
    guard_parser.add_argument("--status-file", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "prepare":
            exit_code, result = prepare(args)
        elif args.command == "clarify":
            exit_code, result = clarify(args)
        elif args.command == "plan":
            exit_code, result = plan(args)
        elif args.command == "gate":
            exit_code, result = gate(args)
        elif args.command == "guard":
            exit_code, result = guard(args)
        else:
            exit_code, result = verify(args)
    except (FileNotFoundError, ValueError) as error:
        print(f"e2e-dev-harness error: {error}", file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
