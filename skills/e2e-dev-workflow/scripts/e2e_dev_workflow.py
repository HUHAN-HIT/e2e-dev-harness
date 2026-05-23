#!/usr/bin/env python3
"""Unified CLI for the e2e-dev-workflow workflow."""

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
import clarification_gate  # noqa: E402
import implementation_gate  # noqa: E402
import kg_refresh  # noqa: E402
import memory_capture  # noqa: E402
import orchestration_plan  # noqa: E402
import superpowers_probe  # noqa: E402


def as_repo(path: Path) -> Path:
    repo = path.resolve()
    if not repo.exists():
        raise FileNotFoundError(f"Repo not found: {repo}")
    return repo


def resolve_repo_path(repo: Path, path: Path | None) -> Path | None:
    if not path:
        return None
    return path if path.is_absolute() else repo / path


def write_status(path: Path | None, result: dict) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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
) -> dict:
    if mode == "off":
        return {"requested_mode": mode, "enabled": False, "selected_mode": "off", "blocked": False}
    design_path = resolve_repo_path(repo, design_doc)
    design_text = orchestration_plan.read_design(design_path)
    facts = facts or kg_refresh.detect(repo)
    design_is_template = bool(design_path and "template" in design_path.stem.lower())
    slug = orchestration_plan.feature_slug(design_path)
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
        "requested_paths": paths_requested or [],
        "selected_services": services,
        "reasons": reasons,
        "agent_run_dir": artifacts["agent_run_dir"],
        "handoff_artifacts": artifacts,
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
    return effective_agent_scope, effective_service_scope, notes


def prepare(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    effective_agent_scope, effective_service_scope, scope_notes = align_prepare_scopes(args.agent_scope, args.service_scope)
    kg_facts = kg_refresh.detect(repo)
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
        ),
        "knowledge_graph": kg_status(repo, args.kg_mode, kg_facts),
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
    write_status(args.status_file, result)
    return (0 if result["ready_for_implementation"] else 2), result


def exec_plan_text(repo: Path, design_doc: Path | None, plan: dict) -> str:
    artifacts = plan["handoff_artifacts"]
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
- Superpowers skills applied:

## Target Behavior

- Goal:
- Non-goals:
- Acceptance criteria:

## Handoff Artifacts

- Agent run directory: {artifacts['agent_run_dir']}
- Requirements: {artifacts['requirements']}
- Use cases: {artifacts['use_cases']}
- Test plan: {artifacts['test_plan']}
- Implementation plan: {artifacts['implementation_plan']}
- Proposed memory updates: {artifacts['proposed_memory_updates']}

## Service Implementation Plans

{service_plans}

## Evidence Paths

- Knowledge graph status: {artifacts['knowledge_graph_status']}
- Red test: {artifacts['red_test_evidence']}
- Green test: {artifacts['green_test_evidence']}
- Coverage matrix: {artifacts['coverage_matrix']}
- Business review: {artifacts['business_review']}
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
"""


def handoff_text(agent_name: str) -> str:
    return f"""---
agent: {agent_name}
status: draft
inputs: []
outputs: []
blocked_by: []
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
        path = resolve_repo_path(repo, Path(relative_path))
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(handoff_text(role), encoding="utf-8")
            created.append(str(path))
    starter_files = {
        artifacts["green_test_evidence"]: "# Unit Test Evidence\n\nRecord the passing narrow and broadened test commands here.\n",
        artifacts["coverage_matrix"]: coverage_matrix_template("all-services"),
        artifacts["business_review"]: handoff_text("business-logic-review"),
    }
    for relative_path, text in starter_files.items():
        path = resolve_repo_path(repo, Path(relative_path))
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(text, encoding="utf-8")
            created.append(str(path))
    for service, paths in artifacts.get("service_plans", {}).items():
        for key, title in (
            ("service_plan", f"service-plan-{service}"),
            ("code_agent", f"code-developer-{orchestration_plan.service_slug(service)}"),
            ("test_evidence", f"unit-test-evidence-{service}"),
            ("coverage_matrix", f"coverage-{service}"),
            ("business_review", f"business-review-{service}"),
        ):
            path = resolve_repo_path(repo, Path(paths[key]))
            assert path is not None
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                if key == "coverage_matrix":
                    path.write_text(coverage_matrix_template(service), encoding="utf-8")
                elif key == "test_evidence":
                    path.write_text("# Unit Test Evidence\n\nRecord the passing service test command here.\n", encoding="utf-8")
                else:
                    path.write_text(handoff_text(title), encoding="utf-8")
                created.append(str(path))
    return created


def coverage_matrix_template(service: str) -> str:
    return f"""# Coverage Matrix: {service}

| id | acceptance | use_case | service | tests | code_refs | business_review | status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AC-1 |  |  | {service} |  |  |  |  |
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
    )
    if (args.create_archive or args.write_exec_plan) and not result.get("handoff_artifacts"):
        result["blocked"] = True
        result["blocked_reasons"] = [
            "Discovery scope does not create ExecPlan or agent-run archives; rerun with --service-scope affected plus --service or --path."
        ]
        write_status(args.status_file, result)
        return 2, result
    if args.create_archive or args.write_exec_plan:
        run_dir = resolve_repo_path(repo, Path(result["agent_run_dir"]))
        assert run_dir is not None
        (run_dir / "handoffs").mkdir(parents=True, exist_ok=True)
        (run_dir / "evidence").mkdir(parents=True, exist_ok=True)
        result["handoff_files_created"] = create_handoff_files(repo, result["handoff_artifacts"])
        proposed = resolve_repo_path(repo, Path(result["handoff_artifacts"]["proposed_memory_updates"]))
        assert proposed is not None
        if not proposed.exists():
            proposed.write_text("# Proposed Memory Updates\n\n", encoding="utf-8")
        result["agent_run_archive_created"] = str(run_dir)
    if args.write_exec_plan or args.create_archive:
        target = resolve_repo_path(repo, args.write_exec_plan or Path(result["handoff_artifacts"]["exec_plan"]))
        assert target is not None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(exec_plan_text(repo, args.design_doc, result), encoding="utf-8")
        result["exec_plan_written"] = str(target)
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
    )
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result


def verify(args) -> tuple[int, dict]:
    prepare_code, prep = prepare(args)
    clarify_code = 0
    clarify_result = None
    if args.design_doc:
        clarify_code, clarify_result = clarify(args)
    gate_result = None
    gate_code = 0
    if args.run_gate:
        gate_code, gate_result = gate(args)

    maven_result = {"skipped": True}
    if not args.skip_maven:
        command = ["mvn", "test"] if not args.module else ["mvn", "-pl", args.module, "-am", "test"]
        completed = subprocess.run(command, cwd=as_repo(args.repo), text=True, capture_output=True)
        maven_result = {
            "skipped": False,
            "command": " ".join(command),
            "exit_code": completed.returncode,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
        }
    result = {
        "prepare": prep,
        "clarification": clarify_result,
        "implementation_gate": gate_result,
        "maven": maven_result,
    }
    exit_code = max(prepare_code, clarify_code, gate_code, maven_result.get("exit_code", 0) if not args.skip_maven else 0)
    write_status(args.status_file, result)
    return exit_code, result


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
    parser.add_argument("--agent-orchestration-mode", choices=["auto", "single", "multi", "off"], default="auto")
    parser.add_argument("--service-scope", choices=["auto", "discovery", "affected", "all"], default="auto")
    parser.add_argument("--agent-run-dir", help="Archive directory for generated agent run files.")
    parser.add_argument("--run-date", help="Date prefix for default agent run directory, YYYY-MM-DD.")
    parser.add_argument("--kg-mode", choices=["auto", "gitnexus", "graphify", "both"], default="auto")
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
    clarify_parser.add_argument("--status-file", type=Path)

    plan_parser = subparsers.add_parser("plan", help="Plan agent orchestration and optionally write an ExecPlan.")
    plan_parser.add_argument("repo", nargs="?", default=".", type=Path)
    plan_parser.add_argument("--mode", choices=["auto", "single", "multi"], default="auto")
    plan_parser.add_argument("--design-doc", type=Path)
    plan_parser.add_argument("--agent-run-dir", help="Archive directory for generated agent run files.")
    plan_parser.add_argument("--run-date", help="Date prefix for default agent run directory, YYYY-MM-DD.")
    plan_parser.add_argument("--path", action="append", help="Path that may be touched; can be repeated.")
    plan_parser.add_argument("--service", action="append", help="Affected service directory or service name; can be repeated.")
    plan_parser.add_argument("--service-scope", choices=["auto", "discovery", "affected", "all"], default="auto")
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
    verify_parser.add_argument("--skip-maven", action="store_true")

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
        else:
            exit_code, result = verify(args)
    except FileNotFoundError as error:
        print(str(error), file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
