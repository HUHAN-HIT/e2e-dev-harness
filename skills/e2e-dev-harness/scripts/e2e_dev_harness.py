#!/usr/bin/env python3
"""Unified CLI for the e2e-dev-harness workflow."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import agent_instructions  # noqa: E402
import ac_progress_gate  # noqa: E402
import agent_scheduler  # noqa: E402
import artifact_registry  # noqa: E402
import clarification_gate  # noqa: E402
from common import DEFAULT_SUBPROCESS_TIMEOUT_SECONDS, atomic_write_json, configure_utf8_stdio, posix, read_json_object  # noqa: E402
import cross_service_dependency_scan  # noqa: E402
import coordinator_flow  # noqa: E402
import dispatcher  # noqa: E402
import execution_trace  # noqa: E402
import implementation_gate  # noqa: E402
import install_hooks  # noqa: E402
import harness_doctor  # noqa: E402
import kg_refresh  # noqa: E402
import handoff_gate  # noqa: E402
import harness_verify  # noqa: E402
import memory_capture  # noqa: E402
import orchestration_plan  # noqa: E402
import output_contract  # noqa: E402
import phase_guard  # noqa: E402
import run_state  # noqa: E402
import session_checkpoint  # noqa: E402
import service_design_gate  # noqa: E402
import superpowers_probe  # noqa: E402
import task_tier  # noqa: E402
import test_impact_plan  # noqa: E402
import workflow_guard  # noqa: E402


DEFAULT_REVIEW_PROFILE = "skills/e2e-dev-harness/review-profiles/default.json"
__version__ = "0.2.0"
INSTALL_TARGETS = {
    "codex": (".codex", "skills", "e2e-dev-harness"),
    "claude": (".claude", "skills", "e2e-dev-harness"),
    "agents": (".agents", "skills", "e2e-dev-harness"),
}
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
DEFAULT_REVIEWER_AGENTS = {
    "design": "design-reviewer",
    "test": "test-reviewer",
    "implementation": "implementation-reviewer",
}
BLUEPRINT_STEPS = coordinator_flow.BLUEPRINT_STEPS
runtime_hook_status = coordinator_flow.runtime_hook_status
next_action_for_lifecycle = coordinator_flow.next_action_for_lifecycle
workflow_overview_for = coordinator_flow.workflow_overview_for
required_todo_list_for_lifecycle = coordinator_flow.required_todo_list_for_lifecycle
todo_policy_for_lifecycle = coordinator_flow.todo_policy_for_lifecycle
exploration_policy_for_lifecycle = coordinator_flow.exploration_policy_for_lifecycle
NOISY_STDOUT_COMMANDS = {
    "next",
    "gate",
    "dispatch-next",
    "dispatch-beat",
    "dispatch-ack",
    "dispatch-complete",
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


def normalize_cli_path(repo: Path, value: str | Path | None) -> str:
    if not value:
        return ""
    path = value if isinstance(value, Path) else Path(str(value))
    try:
        full = path if path.is_absolute() else repo / path
        return posix(full.resolve().relative_to(repo.resolve()))
    except (OSError, ValueError):
        return posix(str(value))


def run_state_path_from_args(repo: Path, args: argparse.Namespace, result: dict) -> Path | None:
    for name in ("state", "run_state"):
        value = getattr(args, name, None)
        if value:
            path = value if value.is_absolute() else repo / value
            return path
    value = result.get("run_state")
    if isinstance(value, str) and value.strip():
        path = Path(value)
        return path if path.is_absolute() else repo / path
    return None


def lifecycle_from_state(repo: Path, args: argparse.Namespace, result: dict) -> str:
    lifecycle = str(result.get("lifecycle", "")).strip()
    if lifecycle:
        return lifecycle
    state_path = run_state_path_from_args(repo, args, result)
    data = read_json_object(state_path) if state_path and state_path.exists() else {}
    return str(data.get("lifecycle", "")).strip()


def write_cli_response_artifact(repo: Path, command: str, args: argparse.Namespace, result: dict) -> str:
    state_path = run_state_path_from_args(repo, args, result)
    if not state_path:
        return ""
    run_dir = state_path.parent
    timestamp = f"{time.strftime('%Y%m%dT%H%M%S')}-{time.time_ns() % 1_000_000_000:09d}"
    path = run_dir / "evidence" / "cli-responses" / f"{command}-{timestamp}.json"
    atomic_write_json(path, result)
    return normalize_cli_path(repo, path)


def append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def merge_warnings(*groups: list | None) -> list[str]:
    warnings: list[str] = []
    for group in groups:
        for value in group or []:
            append_unique(warnings, str(value).strip())
    return warnings


def dispatch_summary_fields(repo: Path, result: dict) -> dict:
    dispatch = result.get("dispatch") if isinstance(result.get("dispatch"), dict) else {}
    dispatches = result.get("dispatches") if isinstance(result.get("dispatches"), dict) else {}
    packets = result.get("dispatch_packets") if isinstance(result.get("dispatch_packets"), list) else []
    claimed = result.get("claimed_tasks") if isinstance(result.get("claimed_tasks"), list) else []
    recent = result.get("recent_events") if isinstance(result.get("recent_events"), list) else []
    task_ids: list[str] = []
    worker_handles: list[str] = []
    spawn_request_paths: list[str] = []
    task_prompt_paths: list[str] = []
    evidence_paths: list[str] = []
    for task in claimed:
        if isinstance(task, dict):
            append_unique(task_ids, str(task.get("id", "")).strip())
    for task_id in dispatches:
        append_unique(task_ids, str(task_id).strip())
    append_unique(task_ids, str(dispatch.get("current_task_id", "")).strip())
    for item in [dispatch, *[value for value in dispatches.values() if isinstance(value, dict)]]:
        append_unique(worker_handles, str(item.get("worker_handle", "")).strip())
        for evidence in item.get("evidence", []) if isinstance(item.get("evidence"), list) else []:
            append_unique(evidence_paths, normalize_cli_path(repo, evidence))
    for packet in packets:
        if not isinstance(packet, dict):
            continue
        append_unique(spawn_request_paths, normalize_cli_path(repo, packet.get("spawn_request_path", "")))
        append_unique(task_prompt_paths, normalize_cli_path(repo, packet.get("task_prompt_path", "")))
    task = result.get("task") if isinstance(result.get("task"), dict) else {}
    for evidence in task.get("evidence", []) if isinstance(task.get("evidence"), list) else []:
        append_unique(evidence_paths, normalize_cli_path(repo, evidence))
    return {
        "task_ids": task_ids,
        "worker_handles": worker_handles,
        "spawn_request_paths": spawn_request_paths,
        "task_prompt_paths": task_prompt_paths,
        "evidence_paths": evidence_paths,
        "claimed_tasks": claimed,
        "blocked_tasks": result.get("blocked_tasks", result.get("skipped_tasks", [])),
        "recent_events": [
            {
                "task_id": item.get("task_id", ""),
                "event": item.get("event", ""),
                "path": normalize_cli_path(repo, item.get("path", "")),
                "evidence": [normalize_cli_path(repo, value) for value in item.get("evidence", [])]
                if isinstance(item.get("evidence"), list)
                else [],
            }
            for item in recent
            if isinstance(item, dict)
        ],
    }


def summarize_stdout_result(command: str, args: argparse.Namespace, result: dict) -> dict:
    if command not in NOISY_STDOUT_COMMANDS or getattr(args, "full_json", False):
        return result
    repo = as_repo(getattr(args, "repo", Path(".")))
    full_result_path = write_cli_response_artifact(repo, command, args, result)
    next_action = result.get("next") if isinstance(result.get("next"), dict) else {}
    session = result.get("session_checkpoint") if isinstance(result.get("session_checkpoint"), dict) else {}
    coordinator_budget = result.get("coordinator_context_budget")
    if not isinstance(coordinator_budget, dict):
        coordinator_budget = session.get("context_budget") if isinstance(session.get("context_budget"), dict) else {}
    summary = {
        "schema": "e2e-dev-harness.cli-summary.v1",
        "command": command,
        "ready": result.get("ready", False),
        "lifecycle": lifecycle_from_state(repo, args, result),
        "blocked_reasons": result.get("blocked_reasons", []),
        "warnings": result.get("warnings", []),
        "full_result_path": full_result_path,
        "checkpoint": normalize_cli_path(repo, session.get("checkpoint", "")),
        "coordinator_context_budget": coordinator_budget,
        "resume_instruction": (
            coordinator_budget.get("resume_instruction")
            or "Resume from the checkpoint and run only the next phase allowed by run-state."
            if session.get("checkpoint")
            else ""
        ),
        "next_action": {
            "phase": next_action.get("phase", ""),
            "command": next_action.get("command", ""),
        },
        "next_command": result.get("next_beat_hint") or next_action.get("command", "") or result.get("coordinator_action", ""),
    }
    if command.startswith("dispatch-"):
        summary.update(dispatch_summary_fields(repo, result))
        if not summary["resume_instruction"]:
            summary["resume_instruction"] = (
                "After each dispatch or completion wave, run next to refresh the session checkpoint before continuing."
            )
    return summary


def install_targets(target: str) -> list[str]:
    return list(INSTALL_TARGETS) if target == "all" else [target]


def copy_skill_tree(source: Path, destination: Path) -> dict:
    def ignore(_dir: str, names: list[str]) -> set[str]:
        return {
            name for name in names
            if name == "__pycache__" or name == ".pytest_cache" or name.endswith(".egg-info")
        }

    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=ignore)
    files = sum(1 for path in destination.rglob("*") if path.is_file())
    dirs = sum(1 for path in destination.rglob("*") if path.is_dir())
    return {"path": str(destination), "files": files, "directories": dirs}


def run_install_command(command: list[str], cwd: Path) -> dict:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=DEFAULT_SUBPROCESS_TIMEOUT_SECONDS,
    )
    return {
        "command": " ".join(str(part) for part in command),
        "exit_code": completed.returncode,
        "stdout_tail": (completed.stdout or "")[-4000:],
        "stderr_tail": (completed.stderr or "")[-4000:],
    }


def optional_text(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def design_template(feature: str, request: str = "") -> str:
    title = feature.strip() or "Feature"
    original = request.strip() or "<paste the original user request here>"
    return f"""# {title}

## Restated Intent
- Agent restatement:
- User confirmation: pending

## Goal
- {original}

## Scope
- Affected services/modules:
- In scope:
- Non-goals:

## Use Cases
- UC-1:

## System Sequence
```mermaid
sequenceDiagram
    actor User
    participant Entry as Entry point
    participant Service as Service/domain logic
    participant Data as Repository/client/sender
    User->>Entry: Trigger UC-1
    Entry->>Service: Execute AC-1 behavior
    Service->>Data: Read/write/call/publish declared effects
    Data-->>Service: Result or acknowledgement
    Service-->>Entry: Outcome
    Entry-->>User: Response or observable result
```

## Acceptance Criteria
- AC-1:

## Test Design
- First red test:
- Verification command:

## Impact Summary
- Source: manual pending GitNexus/dependency scanner evidence
- Raw Evidence:

| type | interface | affected callers/consumers | related AC | required tests/contracts | risk |
| --- | --- | --- | --- | --- | --- |
| N/A | No public/cross-service/interface impact identified yet | N/A | AC-1 | N/A | low |

## Change Logic
- Current behavior:
- Target behavior:
- Runtime path:
- State/data/API/event effects:
- Compatibility or migration notes:

## Contracts
- HTTP/API:
- MQ/DMQ/Kafka:

## Open Questions
- Pending user confirmation of Restated Intent.
"""


def load_phase_profile(repo: Path, path: Path | None) -> tuple[dict, list[str]]:
    if not path:
        return {}, []
    try:
        resolved = require_repo_path(repo, path, "phase profile")
    except ValueError as error:
        return {}, [str(error)]
    if not resolved.exists():
        return {}, [f"Phase profile not found: {resolved}"]
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as error:
        return {}, [f"Phase profile is invalid JSON: {error}"]
    if not isinstance(data, dict):
        return {}, ["Phase profile must be a JSON object."]
    return data, []


def workflow_plan_for_start(
    phase_mode: str,
    workflow_profile: str,
    phase_profile: dict | None = None,
    current_lifecycle: str = "CREATED",
) -> dict:
    profile = phase_profile or {}
    manual_confirm = profile.get("manual_confirm_phases")
    if not isinstance(manual_confirm, list):
        manual_confirm = ["clarify"] if phase_mode == "manual" else []
    dispatch_policy = profile.get("dispatch_policy") if isinstance(profile.get("dispatch_policy"), dict) else {}
    custom_checkpoints = profile.get("custom_checkpoints") if isinstance(profile.get("custom_checkpoints"), list) else []
    phases = []
    for lifecycle, phase, summary in BLUEPRINT_STEPS:
        phases.append(
            {
                "lifecycle": lifecycle,
                "phase": phase,
                "required": True,
                "gate_summary": summary,
                "advance_by": {
                    "clarify": "clarify gate",
                    "plan": "plan archive and R1 review",
                    "service-design": "service-design gate when multi-service",
                    "tdd-red": "TDD red task completion and R2 review completion",
                    "implementation-gate": "gate --phase implementation",
                    "implement-or-complete": "code-agent completion, AC progress, and R3 review",
                    "completion": "completion gate and strict guard",
                    "archive": "requirements archive and final evidence",
                }.get(phase, "harness gate or transition command"),
                "manual_confirm": phase in manual_confirm,
            }
        )
    return {
        "schema": "e2e-dev-harness.workflow-plan.v1",
        "phase_mode": phase_mode,
        "selected_profile": str(profile.get("name") or workflow_profile or "standard"),
        "current_lifecycle": current_lifecycle,
        "phases": phases,
        "dispatch_policy": {
            "r1_r2_r3": dispatch_policy.get("r1_r2_r3", "subagent-required"),
            "service_tdd": dispatch_policy.get("service_tdd", "parallel-when-services-independent"),
            "service_code": dispatch_policy.get("service_code", "after-IMPLEMENTED"),
            "completion": dispatch_policy.get("completion", "after-R3"),
        },
        "manual_confirm_phases": manual_confirm,
        "custom_checkpoints": custom_checkpoints,
        "forbidden": [
            "direct run-state edit",
            "production code before IMPLEMENTED",
            "skipping gates without approval evidence",
            "changing core lifecycle order from a phase profile",
        ],
    }


def without_status_file(args):
    values = vars(args).copy()
    values["status_file"] = None
    return argparse.Namespace(**values)


def trace_event(
    args,
    phase: str,
    event: str,
    status: str = "",
    elapsed_ms: int | None = None,
    artifacts: list[str] | None = None,
) -> None:
    trace_file = getattr(args, "trace_file", None)
    if not trace_file:
        return
    result = execution_trace.append_event(
        as_repo(args.repo),
        trace_file,
        phase,
        event,
        status=status,
        elapsed_ms=elapsed_ms,
        artifacts=artifacts,
    )
    if not result.get("ready", False):
        failures = getattr(args, "_trace_failures", [])
        for reason in result.get("blocked_reasons", []) or ["Execution trace update failed."]:
            if reason not in failures:
                failures.append(reason)
        setattr(args, "_trace_failures", failures)


def timed_phase(args, phase: str, func, *call_args):
    started = time.perf_counter()
    code, result = func(*call_args)
    trace_event(args, phase, "finish", "ready" if code == 0 else "blocked", int((time.perf_counter() - started) * 1000))
    return code, result


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


def write_kg_status_artifact(repo: Path, target: Path, mode: str, facts: dict | None = None) -> dict:
    status = kg_status(repo, mode, facts)
    resolved = require_repo_path(repo, target, "knowledge graph status")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"path": str(resolved), "status": status}


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
    # Capture what the operator explicitly asked for before auto-fill. Only explicit --service/--path
    # (and dependency-report services) force an isolated slice; design auto-fill does not.
    explicit_services = list(services_requested or [])
    explicit_paths = list(paths_requested or [])
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
    # Risk-tier the selected services: only isolation-needing services keep their own slice; the rest
    # collapse into a single merged slice routed via shared_edit_scopes. selected_services stays full.
    layout = orchestration_plan.plan_service_layout(
        services,
        explicit_services=explicit_services,
        explicit_paths=explicit_paths,
        dependency_services=dependency_services,
        design_text=design_text,
        facts=facts,
    )
    artifact_services = layout["artifact_services"]
    artifacts = orchestration_plan.artifacts(
        slug, agent_run_dir, run_date, artifact_services, merged_members=layout["merged_services"]
    )
    agents = orchestration_plan.agent_plan(selected, artifacts, artifact_services)
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
        "slice_services": layout["slice_services"],
        "merged_services": layout["merged_services"],
        "shared_edit_scopes": layout["shared_edit_scopes"],
        "shared_edit_scope_owners": layout["shared_edit_scope_owners"],
        "reasons": reasons,
        "agent_run_dir": artifacts["agent_run_dir"],
        "handoff_artifacts": artifacts,
        "multi_agent_decision": orchestration_plan.multi_agent_decision(selected, services, reasons),
        "agents": agents,
        "agent_schedule": orchestration_plan.agent_schedule(selected, artifact_services, agents),
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


def start(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    feature = args.feature or "feature"
    phase_mode = getattr(args, "phase_mode", "auto") or "auto"
    workflow_profile = getattr(args, "workflow_profile", "standard") or "standard"
    phase_profile, profile_blockers = load_phase_profile(repo, getattr(args, "phase_profile", None))
    if profile_blockers:
        result = {
            "repo": str(repo),
            "ready": False,
            "blocked_reasons": profile_blockers,
            "warnings": [],
        }
        write_status(args.status_file, result)
        return 2, result
    slug = orchestration_plan.safe_slug(feature)
    run_id = args.run_id or orchestration_plan.default_run_id(slug, args.run_date)
    run_dir = require_repo_path(repo, args.agent_run_dir or Path(f"docs/agent-runs/{run_id}"), "agent run directory")
    design_path = require_repo_path(repo, args.design_doc or Path(f"docs/design/{slug}.md"), "design document")
    artifacts = orchestration_plan.artifacts(slug, str(run_dir.relative_to(repo)).replace("\\", "/"), args.run_date, [])
    artifacts["design_doc"] = str(design_path.relative_to(repo)).replace("\\", "/")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence").mkdir(parents=True, exist_ok=True)
    (run_dir / "confirmations").mkdir(parents=True, exist_ok=True)
    design_path.parent.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    if design_path.exists() and not args.force:
        design_created = False
    else:
        design_path.write_text(design_template(feature, args.request or ""), encoding="utf-8")
        design_created = True
        created.append(str(design_path))
    role_templates_created = create_role_template_files(repo, artifacts)
    created.extend(role_templates_created)
    workflow_plan = workflow_plan_for_start(phase_mode, workflow_profile, phase_profile, "CREATED")
    workflow_plan_path = require_repo_path(repo, Path(artifacts["workflow_plan"]), "workflow plan")
    workflow_plan_path.write_text(json.dumps(workflow_plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    created.append(str(workflow_plan_path))
    bootstrap_agents = [
        orchestration_plan.with_role_template(
            {
                "name": "requirements-clarifier",
                "owns": ["goal", "non-goals", "constraints", "impact summary", "acceptance criteria", "open questions"],
                "inputs": ["user request", artifacts["design_doc"], artifacts["dependency_report"]],
                "outputs": [artifacts["requirements"], artifacts["impact_summary"], artifacts["impact_evidence"]],
                "gate": "Behavior/API/data/test-impacting open questions and bounded impact summary gaps must be resolved.",
            },
            artifacts,
        )
    ]
    schedule = orchestration_plan.agent_schedule("bootstrap", [], bootstrap_agents)
    schedule_path = require_repo_path(repo, Path(artifacts["agent_schedule"]), "agent schedule")
    schedule_path.write_text(json.dumps(schedule, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    created.append(str(schedule_path))
    registry = artifact_registry.build_registry(repo, artifacts["agent_run_dir"], artifacts, "bootstrap", [])
    registry_path = require_repo_path(repo, Path(artifacts["artifact_registry"]), "artifact registry")
    artifact_registry.write_registry(repo, registry_path, registry)
    created.append(str(registry_path))
    state = run_state.build_state(
        artifacts["agent_run_dir"],
        "bootstrap",
        [],
        artifacts["artifact_registry"],
        lifecycle="CREATED",
    )
    state["phase_mode"] = phase_mode
    state["workflow_profile"] = workflow_plan["selected_profile"]
    state["workflow_plan"] = artifacts["workflow_plan"]
    state["manual_confirm_phases"] = workflow_plan["manual_confirm_phases"]
    state["dispatch_policy"] = workflow_plan["dispatch_policy"]
    state_path = require_repo_path(repo, Path(artifacts["run_state"]), "run state")
    run_state.write_state(repo, state_path, state)
    created.append(str(state_path))
    lock_path = state_path.parent / run_state.PHASE_LOCK
    hooks = runtime_hook_status(repo)
    result = {
        "repo": str(repo),
        "ready": True,
        "feature": feature,
        "run_id": run_id,
        "agent_run_dir": str(run_dir),
        "design_doc": str(design_path),
        "design_created": design_created,
        "run_state": str(state_path),
        "phase_lock": str(lock_path),
        "artifact_registry": str(registry_path),
        "agent_schedule": str(schedule_path),
        "workflow_plan": str(workflow_plan_path),
        "phase_mode": phase_mode,
        "workflow_profile": workflow_plan["selected_profile"],
        "workflow": workflow_plan,
        "hook_status": hooks,
        "created": created,
        "next": next_action_for_lifecycle("CREATED", state),
        "blocked_reasons": [],
        "warnings": ([] if design_created else ["Design document already existed; use --force to rewrite the starter template."])
        + ["Runtime hook is not ready; install hooks or use pre-code before editing code."] if not hooks["ready"] else (
            [] if design_created else ["Design document already existed; use --force to rewrite the starter template."]
        ) + hooks.get("warnings", []),
    }
    write_status(args.status_file, result)
    return 0, result


def clarification_dispatch_blockers(repo: Path, run_state_path: Path | str | None) -> list[str]:
    state_file = require_repo_path(repo, Path(str(run_state_path)), "run state") if run_state_path else None
    if not state_file or not state_file.exists():
        return [f"Run state not found for clarification dispatch check: {run_state_path}"]
    state_data = read_json_object(state_file)
    if not state_data:
        return [f"Run state is unreadable for clarification dispatch check: {state_file}"]
    if str(state_data.get("lifecycle", "")).upper() != "CREATED":
        return []

    schedule_path = state_file.parent / "agent-schedule.json"
    if not schedule_path.exists():
        return [
            "Clarification gate blocked: CREATED run-state requires completed requirements-clarifier dispatch evidence; "
            "agent-schedule.json is missing beside run-state."
        ]
    schedule = read_json_object(schedule_path)
    if not schedule:
        return [f"Clarification gate blocked: agent schedule is unreadable: {schedule_path}"]

    tasks = [task for task in schedule.get("tasks", []) or [] if isinstance(task, dict)]
    clarifier_tasks = [
        task
        for task in tasks
        if str(task.get("agent", "")).strip() == "requirements-clarifier"
        or str(task.get("phase", "")).strip().lower() == "clarify"
    ]
    if not clarifier_tasks:
        return [
            "Clarification gate blocked: CREATED run-state requires a scheduled requirements-clarifier task."
        ]

    blockers = agent_scheduler.dispatch_completion_blockers_for_tasks(
        repo,
        schedule_path,
        state_file,
        clarifier_tasks,
        "Clarification gate blocked",
    )
    return blockers or []


def service_design_dispatch_blockers(repo: Path, run_state_path: Path | str | None) -> list[str]:
    state_file = require_repo_path(repo, Path(str(run_state_path)), "run state") if run_state_path else None
    if not state_file or not state_file.exists():
        return [f"Run state not found for service-design dispatch check: {run_state_path}"]
    state_data = read_json_object(state_file)
    if not state_data:
        return [f"Run state is unreadable for service-design dispatch check: {state_file}"]
    if str(state_data.get("lifecycle", "")).upper() != "SERVICE_DESIGN_REQUIRED":
        return []

    schedule_path = state_file.parent / "agent-schedule.json"
    if not schedule_path.exists():
        return [
            "Service-design gate blocked: SERVICE_DESIGN_REQUIRED requires dispatcher-confirmed "
            "service-design worker task outputs; agent-schedule.json is missing beside run-state."
        ]
    schedule = read_json_object(schedule_path)
    if not schedule:
        return [f"Service-design gate blocked: agent schedule is unreadable: {schedule_path}"]

    service_design_tasks = agent_scheduler.tasks_with_output_fragments(schedule, ["/service-designs/"])
    if not service_design_tasks:
        return [
            "Service-design gate blocked: SERVICE_DESIGN_REQUIRED requires scheduled service-design worker "
            "tasks that output service-designs/*.md before the main coordinator may transition to PLANNED."
        ]
    return agent_scheduler.dispatch_completion_blockers_for_tasks(
        repo,
        schedule_path,
        state_file,
        service_design_tasks,
        "Service-design gate blocked",
    )


def clarify(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    design_path = resolve_repo_path(repo, args.design_doc)
    if not design_path or not design_path.exists():
        return 2, {"ready_for_implementation": False, "error": f"Design doc not found: {design_path}"}
    run_state_path = getattr(args, "run_state", None)
    result = clarification_gate.validate(
        design_path,
        require_intent=getattr(args, "require_intent", True),
        require_user_confirmation=getattr(args, "require_user_confirmation", True),
    )
    if run_state_path and result.get("ready_for_implementation"):
        dispatch_blockers = clarification_dispatch_blockers(repo, run_state_path)
        if dispatch_blockers:
            result["ready_for_implementation"] = False
            result.setdefault("blocked_reasons", []).extend(dispatch_blockers)
            result["clarification_dispatch"] = {"ready": False, "blocked_reasons": dispatch_blockers}
            result["interaction_required"] = True
            result["questions_to_ask_user"] = [
                "Run dispatch-next for requirements-clarifier and relay its returned Restated Intent/Open Questions first."
            ]
            write_status(args.status_file, result)
            return 2, result
    if run_state_path and result.get("ready_for_implementation"):
        result["run_state_transition"] = run_state.transition_state(
            repo,
            run_state_path,
            "CLARIFIED",
            gate="clarification",
            gate_status="passed",
            evidence=design_path,
        )
        result["blocked_next_without_plan"] = True
        result["next_required"] = {
            "phase": "plan",
            "command": "Run e2e_dev_harness.py next, then e2e_dev_harness.py plan --create-archive before any code write.",
            "code_writes_allowed": False,
        }
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
- Test impact plan: {artifacts['test_impact_plan']}
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
- Test impact plan: {artifacts['test_impact_plan']}
- Implementation manifest: {artifacts['implementation_manifest']}
- Red test: {artifacts['red_test_evidence']}
- Green test: {artifacts['green_test_evidence']}
- Coverage matrix: {artifacts['coverage_matrix']}
- Business review: {artifacts['business_review']}
- Rework gate: {artifacts['rework_dir']}
- Verification: {artifacts['verification_evidence']}
- Phase coverage: {artifacts['phase_coverage']}
- Strict guard: {artifacts['strict_guard_result']}

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


def handoff_body_guidance(agent_name: str) -> dict[str, list[str]]:
    guidance = {
        "requirements-clarifier": {
            "Summary": [
                "TODO: Restate the user intent, final goal, non-goals, and confirmed scope.",
                "TODO: List resolved acceptance criteria and unresolved items that block downstream work.",
            ],
            "Facts Used": [
                "TODO: Name project instructions, design docs, GitNexus/Graphify evidence, and user confirmations used.",
            ],
            "Decisions Made": [
                "TODO: Record scope decisions, tier/orchestration decision, and why out-of-scope items were excluded.",
            ],
            "Downstream Assumptions": [
                "TODO: State what use-case/test agents may rely on without rereading the full conversation.",
            ],
            "Verification Evidence": [
                "TODO: Link clarification gate output, impact summary evidence, and confirmation artifacts.",
            ],
        },
        "use-case-designer": {
            "Summary": [
                "TODO: Summarize happy paths, failure paths, data effects, and cross-service flows.",
            ],
            "Facts Used": [
                "TODO: Name the requirements handoff, impact summary, contracts, and dependency evidence consumed.",
            ],
            "Decisions Made": [
                "TODO: Map every AC to one or more use cases, or mark an explicitly approved deferral.",
            ],
            "Downstream Assumptions": [
                "TODO: State API/data/contract behavior that test design must cover.",
            ],
            "Verification Evidence": [
                "TODO: Link use-case artifact, contract artifacts, and R1 review status when available.",
            ],
        },
        "test-case-developer": {
            "Summary": [
                "TODO: Summarize red-test intent, expected failure, test scope, and broadened verification plan.",
            ],
            "Facts Used": [
                "TODO: Name requirements, use cases, impact summary, contracts, and project test patterns consumed.",
            ],
            "Decisions Made": [
                "TODO: Record selected test types, Maven module commands, mocks/fakes, and non-covered risks.",
            ],
            "Downstream Assumptions": [
                "TODO: State exact failing tests and constraints the code developer must satisfy before production edits.",
            ],
            "Verification Evidence": [
                "TODO: Link red-test evidence, test-impact plan, and R2 review output.",
            ],
        },
        "code-developer": {
            "Summary": [
                "TODO: Summarize implementation scope, changed runtime path, and residual risk.",
            ],
            "Facts Used": [
                "TODO: Name requirements, use cases, test plan, red-test evidence, context pack, and service plan consumed.",
            ],
            "Decisions Made": [
                "TODO: Record implementation choices, project patterns reused, and any approved deviations.",
            ],
            "Downstream Assumptions": [
                "TODO: State what reviewers may assume about code ownership, contracts, and verification boundaries.",
            ],
            "Verification Evidence": [
                "TODO: Link green-test evidence, implementation manifest, coverage matrix, and command evidence.",
            ],
        },
    }
    base = guidance.get(agent_name, {})
    if not base:
        for role, role_guidance in sorted(guidance.items(), key=lambda item: len(item[0]), reverse=True):
            if agent_name.startswith(role + "-"):
                base = role_guidance
                break
    return base or {
        "Summary": ["TODO: Summarize the completed role output and remaining risk."],
        "Facts Used": ["TODO: Name all consumed artifacts and evidence."],
        "Decisions Made": ["TODO: Record important decisions and tradeoffs."],
        "Downstream Assumptions": ["TODO: State assumptions downstream agents may rely on."],
        "Verification Evidence": ["TODO: Link command, review, or gate evidence."],
    }


def handoff_text(agent_name: str) -> str:
    guidance = handoff_body_guidance(agent_name)

    def section(title: str) -> str:
        lines = "\n".join(f"- {item}" for item in guidance[title])
        return f"## {title}\n\n{lines}"

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

This is a draft starter handoff. It is NOT READY for downstream consumption until the owner replaces every TODO, records hashes for consumed/produced artifacts, sets `status: ready`, and writes the matching `.ready.json` marker. Do not put this handoff file in output_hashes; the ready marker records this handoff file hash.

{section("Summary")}

{section("Facts Used")}

{section("Decisions Made")}

## Open Questions

TODO: Use `None` only after all downstream-blocking questions are closed.

{section("Downstream Assumptions")}

{section("Verification Evidence")}

## Proposed Memory Updates

TODO: List proposed memory updates or `None`.
"""


ROLE_TEMPLATE_DETAILS = {
    "requirements-clarifier": {
        "boundary": "Clarify user intent, scope, ACs, unresolved questions, and bounded impact summary. Do not design tests or write code.",
        "inputs": "User request, project instructions, dependency/impact summaries, prior approved requirement facts.",
        "forbidden": "Production/test code edits, implementation planning, review approval, and speculative scope expansion.",
        "outputs": "Ready requirements handoff, impact summary rows, resolved/open question status, proposed memory updates.",
        "done": "All behavior/API/data/test-impacting questions are resolved or explicitly blocked, and downstream assumptions are stated.",
    },
    "use-case-designer": {
        "boundary": "Map ACs to use cases, failure paths, contracts, data effects, and service/module slices. Do not write tests or code.",
        "inputs": "Ready requirements handoff, impact summary, dependency report, project patterns.",
        "forbidden": "Changing accepted scope, production/test code edits, and approving own design.",
        "outputs": "Ready use-case handoff, service/use-case mapping, contract candidates, downstream assumptions.",
        "done": "Every AC maps to at least one use case or a documented deferral with owner and approval need.",
    },
    "implementation-planner": {
        "boundary": "Refine the implementation plan and dispatch sequence after R1 approval. Do not write tests or production code.",
        "inputs": "Ready requirements/use-case handoffs, R1 design review, impact summary, dependency report, project patterns.",
        "forbidden": "Approving own design, writing R1/R2/R3 reports, changing accepted scope, test edits, and production code edits.",
        "outputs": "Dispatch-ready exec plan evidence, open rework routing, service/code handoff assumptions.",
        "done": "TDD and implementation tasks have bounded inputs, ordered dependencies, and unresolved R1 findings are routed to rework.",
    },
    "test-case-developer": {
        "boundary": "Create test strategy, first red tests, contract tests, and test-impact commands. Do not modify production code.",
        "inputs": "Ready requirements and use-case handoffs, service design slices, TDD references.",
        "forbidden": "Production code edits, green implementation, semantic review approval, and changing AC scope.",
        "outputs": "Ready test handoff, red-test evidence path, test-impact plan, test command matrix.",
        "done": "A meaningful red test exists, fails for the expected reason, and R2 has enough evidence to review.",
    },
    "code-developer": {
        "boundary": "Implement only assigned ACs and service/module scope using red-green-refactor. Do not alter requirements or review outputs.",
        "inputs": "Ready design/test handoffs, approved R2, service plan, service design slice, failing test evidence.",
        "forbidden": "Writing R1/R2/R3 reports, expanding scope, editing unclaimed services, or skipping AC progress.",
        "outputs": "Implementation handoff, implementation manifest, unit-test command JSON, coverage matrix, business review notes.",
        "done": "All assigned ACs have concrete code refs and passing tests; no undeclared file or behavior drift remains.",
    },
    "semantic-reviewer": {
        "boundary": "Review one phase from request-scoped inputs only. Do not write code or patch artifacts under review.",
        "inputs": "Review request, context pack, role handoffs, design/test/code evidence allowed by the request.",
        "forbidden": "Inherited developer chat context, self-review, production/test code edits, and consolidated after-the-fact review.",
        "outputs": "R1/R2/R3 review report, reviewer invocation JSON, blocking findings or rework items.",
        "done": "Review report has request hash, concrete session isolation proof, checked profile items, and status.",
    },
    "coverage-reviewer": {
        "boundary": "Verify end-to-end AC coverage and archive outcomes. Do not patch implementation directly.",
        "inputs": "All ready role handoffs, semantic reviews, manifests, coverage matrix, command evidence, rework items.",
        "forbidden": "Closing gaps by editing code, ignoring failed commands, or archiving unresolved rework as complete.",
        "outputs": "Final coverage/business review, requirements archive, run summary, residual risk list.",
        "done": "Every AC maps to use case, tests, code refs, business review, accepted review status, and closed rework.",
    },
}


def role_template_text(role: str) -> str:
    detail = ROLE_TEMPLATE_DETAILS.get(role, ROLE_TEMPLATE_DETAILS["code-developer"])
    return f"""# Agent Role Template: {role}

## Role Boundary

{detail["boundary"]}

## Allowed Inputs

{detail["inputs"]}

## Forbidden

{detail["forbidden"]}

## Required Outputs

{detail["outputs"]}

## Done When

{detail["done"]}
"""


def create_role_template_files(repo: Path, artifacts: dict) -> list[str]:
    created: list[str] = []
    for role, relative_path in (artifacts.get("role_templates") or {}).items():
        path = require_repo_path(repo, Path(relative_path), f"{role} role template")
        path.parent.mkdir(parents=True, exist_ok=True)
        text = role_template_text(role)
        if not path.exists() or path.read_text(encoding="utf-8", errors="replace") != text:
            path.write_text(text, encoding="utf-8")
            created.append(str(path))
    return created


def normalize_artifact_path(value: str) -> str:
    return str(value).replace("\\", "/")


def reviewer_agent_for_output(agent_schedule: dict | None, output_path: str, phase: str) -> str:
    normalized_output = normalize_artifact_path(output_path)
    for task in (agent_schedule or {}).get("tasks", []) or []:
        if not isinstance(task, dict):
            continue
        outputs = {normalize_artifact_path(str(item)) for item in task.get("outputs", []) or []}
        if normalized_output in outputs:
            return str(task.get("agent", "")).strip() or DEFAULT_REVIEWER_AGENTS.get(phase, "semantic-reviewer")
    return DEFAULT_REVIEWER_AGENTS.get(phase, "semantic-reviewer")


def create_handoff_files(repo: Path, artifacts: dict, agent_schedule: dict | None = None) -> list[str]:
    role_files = {
        "requirements-clarifier": artifacts["requirements"],
        "use-case-designer": artifacts["use_cases"],
        "test-case-developer": artifacts["test_plan"],
        "code-developer": artifacts["implementation_plan"],
    }
    created: list[str] = []
    created.extend(create_role_template_files(repo, artifacts))
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
            reviewer_agent=reviewer_agent_for_output(agent_schedule, artifacts["design_review"], "design"),
        ),
        artifacts["test_review_request"]: review_request_template(
            "test",
            "R2 test semantic review request",
            artifacts["test_review"],
            "all-services",
            reviewer_agent=reviewer_agent_for_output(agent_schedule, artifacts["test_review"], "test"),
        ),
        artifacts["implementation_review_request"]: review_request_template(
            "implementation",
            "R3 implementation semantic review request",
            artifacts["implementation_review"],
            "all-services",
            reviewer_agent=reviewer_agent_for_output(agent_schedule, artifacts["implementation_review"], "implementation"),
        ),
        artifacts["impact_summary"]: impact_summary_template("all-services", artifacts["impact_evidence"]),
        artifacts["impact_evidence"]: impact_evidence_template(),
        artifacts["test_impact_plan"]: test_impact_plan_template(),
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
    global_design_ref = str(artifacts.get("design_doc", "<global-design-doc>"))
    global_design_path = resolve_repo_path(repo, Path(global_design_ref)) if global_design_ref != "<global-design-doc>" else None
    global_design_text = optional_text(global_design_path)
    for service, paths in artifacts.get("service_plans", {}).items():
        service_design = require_repo_path(repo, Path(paths["service_design"]), f"{service} service design")
        service_design.parent.mkdir(parents=True, exist_ok=True)
        if not service_design.exists():
            service_design.write_text(
                service_design_template(
                    service,
                    global_design_ref,
                    global_design_text,
                    merged_members=paths.get("merged_members"),
                ),
                encoding="utf-8",
            )
            created.append(str(service_design))
        service_review_requests = {
            "test_review_request": review_request_template(
                "test",
                f"test-review-request-{service}",
                paths["test_review"],
                service,
                reviewer_agent=reviewer_agent_for_output(agent_schedule, paths["test_review"], "test"),
            ),
            "implementation_review_request": review_request_template(
                "implementation",
                f"implementation-review-request-{service}",
                paths["implementation_review"],
                service,
                reviewer_agent=reviewer_agent_for_output(agent_schedule, paths["implementation_review"], "implementation"),
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
            ("test_impact_plan", f"test-impact-plan-{service}"),
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
                elif key == "test_impact_plan":
                    path.write_text(test_impact_plan_template(), encoding="utf-8")
                elif key == "service_plan":
                    path.write_text(service_plan_template(service), encoding="utf-8")
                else:
                    path.write_text(handoff_text(title), encoding="utf-8")
                created.append(str(path))
    return created


def service_tokens(service: str) -> list[str]:
    values = {service.lower(), orchestration_plan.service_slug(service).lower(), Path(service).name.lower()}
    for value in list(values):
        values.update(part for part in value.replace("_", "-").replace("/", "-").split("-") if len(part) > 2)
    return sorted(values, key=len, reverse=True)


def acceptance_items_from_text(markdown: str) -> list[dict[str, str]]:
    body = clarification_gate.section_text(markdown, clarification_gate.REQUIRED["acceptance"]) if markdown else None
    if not body:
        return []
    results: list[dict[str, str]] = []
    used: set[str] = set()
    next_index = 1
    for line in body.splitlines():
        stripped = line.strip()
        content = clarification_gate.ACCEPTANCE_LINE_RE.match(line)
        item_text = content.group(1).strip() if content else stripped
        if not item_text or set(item_text) <= {"|", "-", " "}:
            continue
        id_match = clarification_gate.ACCEPTANCE_ID_RE.match(item_text)
        if id_match:
            ac_id = clarification_gate.normalize_acceptance_id(item_text)
            description = item_text[id_match.end():].strip(" :-\t") or item_text
        else:
            while f"AC-{next_index}" in used:
                next_index += 1
            ac_id = f"AC-{next_index}"
            next_index += 1
            description = item_text
        if ac_id not in used:
            results.append({"id": ac_id, "text": description})
            used.add(ac_id)
    return results


def one_line_section(markdown: str, key: str) -> str:
    patterns = clarification_gate.REQUIRED.get(key, [])
    body = clarification_gate.section_text(markdown, patterns) if markdown and patterns else None
    for line in (body or "").splitlines():
        normalized = line.strip().strip("-* ")
        if normalized:
            return normalized
    return ""


def service_test_class_name(service: str) -> str:
    slug = orchestration_plan.service_slug(service)
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", slug) if part]
    base = "".join(part[:1].upper() + part[1:] for part in parts) or "Service"
    return f"{base}Test"


def service_acceptance_rows(service: str, global_design_text: str) -> str:
    items = acceptance_items_from_text(global_design_text)
    if not items:
        return f"| AC-1 | Derived from global design after clarification | {service} service responsibility to be confirmed during service-design gate | {service_test_class_name(service)} |\n"
    tokens = service_tokens(service)
    matched = [
        item
        for item in items
        if any(token in item["text"].lower() for token in tokens)
    ]
    selected = matched or items
    test_class = service_test_class_name(service)
    return "".join(
        f"| {item['id']} | {item['text']} | {service} owns the service-local behavior, integration points, or non-applicability decision for this AC | {test_class} |\n"
        for item in selected
    )


def service_scope_excerpt(service: str, global_design_text: str) -> str:
    scope = one_line_section(global_design_text, "scope")
    return scope or f"{service} service/module slice from the global design."


def service_design_template(
    service: str,
    global_design: str,
    global_design_text: str = "",
    merged_members: list[str] | None = None,
) -> str:
    ac_rows = service_acceptance_rows(service, global_design_text)
    test_class = service_test_class_name(service)
    intent = one_line_section(global_design_text, "restated_intent") or one_line_section(global_design_text, "goal")
    service_scope = service_scope_excerpt(service, global_design_text)
    # A merged slice owns several real modules; enumerate each so the code agent gets one allowed
    # edit scope and one Maven command per member module instead of the synthetic merged id.
    members = merged_members or [service]
    module_label = ", ".join(members) if merged_members else service
    allowed_scope = "\n".join(f"  - {member}/" for member in members)
    maven_block = "\n".join(f"- Required Maven command: mvn -pl {member} -am test" for member in members)
    test_impact_block = "\n".join(
        f"- Service-local test impact plan: mvn -pl {member} -am test" for member in members
    )
    return f"""# Service Design Slice: {service}

Global design: {global_design}

Primary development contract: this service design is the primary input for the service code agent. Keep global context bounded; copy only the ACs, constraints, and dependency facts this service needs.

## Service Scope
- Service/module: {module_label}
- Allowed edit scope:
{allowed_scope}
- Explicitly out of scope: other services unless listed in Dependency Boundary

## Global Intent Summary
- Restated user intent: {intent or 'See global design and requirements handoff.'}
- This service's responsibility: {service_scope}

## Mapped Acceptance Criteria
| AC | global requirement | service responsibility | local tests |
| --- | --- | --- | --- |
{ac_rows.rstrip()}

## Runtime Path
- Entry point: GitNexus-confirmed entry point -> {service_test_class_name(service).removesuffix('Test')}#method
- Service/domain path: {service_test_class_name(service).removesuffix('Test')}#method -> domain/service collaborator
- Repository/client/sender path: repository/client/sender decided by service-design gate
- Output or side effect: service-local state, API response, or event named in mapped ACs

## Local Sequence
```mermaid
sequenceDiagram
    participant Test as {test_class}
    participant Entry as {service} entry point
    participant Domain as service/domain logic
    participant Edge as repository/client/sender
    Test->>Entry: Exercise mapped AC rows
    Entry->>Domain: Execute service-local behavior
    Domain->>Edge: Persist, call, or publish declared side effect
    Edge-->>Domain: Result or acknowledgement
    Domain-->>Entry: Service-local outcome
    Entry-->>Test: Assertion target
```

## Service-local TDD Plan
- First red test: {test_class} should fail before implementation
- Expected failure: missing mapped service-local behavior
- Minimal green implementation: implement only the mapped AC rows above
- Refactor checks: keep edits inside allowed scope and declared dependency boundary
{maven_block}

## Dependency Boundary
- Independent service change: generated starter requires service owner confirmation before code dispatch
- HTTP/API dependencies: use dependency report and GitNexus impact evidence, or state None
- MQ/DMQ/Kafka dependencies: use dependency report and GitNexus impact evidence, or state None
- Shared DB/schema/config/security dependencies: list shared edit scope or state None
- Required contracts or explicit non-applicability: record before implementation

## Test Impact
{test_impact_block}
- Broadened verification: run impacted upstream/downstream modules from test-impact plan

## Reviewer Focus
- Service-local R2 review: mapped ACs, red test, dependency boundary
- Service-local R3 review: concrete code path, tests, and side effects for mapped ACs
- Known risks: generated starter must be verified against GitNexus evidence and project instructions
"""


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


def test_impact_plan_template() -> str:
    return json.dumps(
        {
            "schema": "e2e-dev-harness.test-impact-plan.v1",
            "status": "template",
            "strategy": "incremental-tests",
            "changed_files": [],
            "ignored_changes": [],
            "commands": [],
            "notes": (
                "Generate with test_impact_plan.py --changed-files <file> --output <this-file>. "
                "Completion blocks while status remains template."
            ),
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


def review_request_template(
    phase: str,
    title: str,
    output_path: str,
    scope: str = "all-services",
    developer_agent: str = "coordinator-agent",
    reviewer_agent: str | None = None,
    invocation_path: str | None = None,
) -> str:
    reviewer_agent = reviewer_agent or DEFAULT_REVIEWER_AGENTS.get(phase, "semantic-reviewer")
    invocation_path = invocation_path or output_path.replace("/reviews/", "/review-invocations/").replace("\\reviews\\", "\\review-invocations\\")
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
- Developer Agent: {developer_agent}
- Reviewer Agent: {reviewer_agent}
- Reviewer Invocation: {invocation_path}
- AC Progress Gate: required before R3; all assigned ACs must be present in coverage matrix, implementation manifest, and passing green/unit command evidence.

## Review Assignment

Run this review in an independent reviewer agent. The reviewer may read only the allowed inputs and must write only the declared output review report or rework items requested by the gate.
Before writing the report, create the declared Reviewer Invocation JSON with concrete `runtime`, isolated `invocation_type`, `developer_session`, `reviewer_session`, `context_pack`, `review_request`, `output`, `fork_context: false`, request-only `context_policy`, and `status: completed`. `developer_session` and `reviewer_session` must be different.

## Required Review Checklist

The report must include checked `- [x] <id>: ...` lines for each required item:

{checklist}

For implementation reviews, also include:

## Code Path Trace

- AC-1: <entry point> -> <application service> -> <repository/client/sender> -> <response, persistence, or emitted event>.
"""


def semantic_review_template(phase: str, title: str, scope: str = "all-services", request_path: str = "") -> str:
    invocation_path = ""
    if request_path:
        invocation_path = request_path.replace("/review-requests/", "/review-invocations/").replace("\\review-requests\\", "\\review-invocations\\")
        if invocation_path.endswith(".md"):
            invocation_path = invocation_path[:-3] + "-invocation.json"
    return f"""# {title}

- Phase: {phase}
- Reviewer: semantic-reviewer
- Review Request: {request_path}
- Developer Agent: <developer-agent-id>
- Reviewer Agent: <independent-reviewer-agent-id>
- Reviewer Session: <reviewer-session-id>
- Reviewer Invocation: {invocation_path or '<reviewer-invocation-json-path>'}
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
- Service design slice: service-designs/{orchestration_plan.service_slug(service)}.md
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
        (run_dir / "confirmations").mkdir(parents=True, exist_ok=True)
        require_repo_path(repo, Path(result["handoff_artifacts"]["review_requests_dir"]), "review requests directory").mkdir(parents=True, exist_ok=True)
        require_repo_path(repo, Path(result["handoff_artifacts"]["reviews_dir"]), "reviews directory").mkdir(parents=True, exist_ok=True)
        require_repo_path(repo, Path(result["handoff_artifacts"]["rework_dir"]), "rework directory").mkdir(parents=True, exist_ok=True)
        require_repo_path(repo, Path(result["handoff_artifacts"]["contracts_dir"]), "contracts directory").mkdir(parents=True, exist_ok=True)
        require_repo_path(repo, Path(result["handoff_artifacts"]["service_designs_dir"]), "service designs directory").mkdir(parents=True, exist_ok=True)
        if args.design_doc:
            result["handoff_artifacts"]["design_doc"] = str(args.design_doc).replace("\\", "/")
        result["handoff_files_created"] = create_handoff_files(repo, result["handoff_artifacts"], result.get("agent_schedule"))
        proposed = require_repo_path(repo, Path(result["handoff_artifacts"]["proposed_memory_updates"]), "proposed memory updates")
        if not proposed.exists():
            proposed.write_text("# Proposed Memory Updates\n\n", encoding="utf-8")
        schedule_path = require_repo_path(repo, Path(result["handoff_artifacts"]["agent_schedule"]), "agent schedule")
        schedule_path.write_text(json.dumps(result["agent_schedule"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        result["agent_schedule_written"] = str(schedule_path)
        kg_artifact = write_kg_status_artifact(
            repo,
            Path(result["handoff_artifacts"]["knowledge_graph_status"]),
            "auto",
            kg_facts,
        )
        result["knowledge_graph_status_written"] = kg_artifact["path"]
        result["knowledge_graph"] = kg_artifact["status"]
        result["agent_run_archive_created"] = str(run_dir)
    if args.write_exec_plan or args.create_archive:
        target = require_repo_path(repo, args.write_exec_plan or Path(result["handoff_artifacts"]["exec_plan"]), "exec plan")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(exec_plan_text(repo, args.design_doc, result), encoding="utf-8")
        result["exec_plan_written"] = str(target)
    if args.create_archive:
        registry_artifacts = dict(result["handoff_artifacts"])
        registry = artifact_registry.build_registry(
            repo,
            result["agent_run_dir"],
            registry_artifacts,
            result.get("selected_mode", ""),
            result.get("selected_services", []),
        )
        registry_path = require_repo_path(repo, Path(result["handoff_artifacts"]["artifact_registry"]), "artifact registry")
        artifact_registry.write_registry(repo, registry_path, registry)
        lifecycle = "SERVICE_DESIGN_REQUIRED" if (
            result.get("selected_mode") == "multi" and len(result.get("selected_services", [])) > 1
        ) else "PLANNED"
        state = run_state.build_state(
            result["agent_run_dir"],
            result.get("selected_mode", ""),
            result.get("slice_services", result.get("selected_services", [])),
            result["handoff_artifacts"]["artifact_registry"],
            lifecycle=lifecycle,
            shared_edit_scopes=result.get("shared_edit_scopes", []),
            shared_edit_scope_owners=result.get("shared_edit_scope_owners", {}),
        )
        state_path = require_repo_path(repo, Path(result["handoff_artifacts"]["run_state"]), "run state")
        run_state.write_state(repo, state_path, state)
        result["artifact_registry_written"] = str(registry_path)
        result["run_state_written"] = str(state_path)
        result["run_state_lifecycle"] = lifecycle
    write_status(args.status_file, result)
    return 0, result


def gate(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    result = implementation_gate.validate_gate_request(
        implementation_gate.GateRequest(
            repo=repo,
            design_doc=args.design_doc,
            kg_status_file=args.kg_status_file,
            phase=args.phase,
            red_test_evidence=args.red_test_evidence,
            coverage_matrix=args.coverage_matrix,
            unit_test_evidence=args.unit_test_evidence,
            business_review=args.business_review,
            memory_updates=args.memory_updates,
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
            review_profile=getattr(args, "review_profile", None) or Path(DEFAULT_REVIEW_PROFILE),
            requirements_archive=getattr(args, "requirements_archive", None),
            require_requirements_archive=(
                getattr(args, "require_requirements_archive", False)
                or (getattr(args, "strict_workflow", False) and args.phase == "completion")
            ),
            changed_files=getattr(args, "changed_files", None),
            test_impact_plan=getattr(args, "test_impact_plan", None),
            base_ref=getattr(args, "base_ref", None),
            checkpoint_mode=getattr(args, "checkpoint_mode", "off"),
            confirmation_dirs=getattr(args, "confirmation_dir", None),
            require_intent=getattr(args, "require_intent", False),
            tdd_mode=getattr(args, "tdd_mode", "auto"),
            workflow_tier=getattr(args, "workflow_tier", "auto"),
            run_state=getattr(args, "run_state", None) or getattr(args, "state", None),
            no_harness_state=getattr(args, "no_harness_state", False),
            harness_state_approval=getattr(args, "harness_state_approval", None),
            require_gitnexus_evidence=getattr(args, "require_gitnexus_evidence", "auto"),
            gitnexus_degradation=getattr(args, "gitnexus_degradation", None),
        )
    )
    if result.get("ready"):
        transition_target = {
            "implementation": "IMPLEMENTED",
            "completion": "VERIFIED",
        }.get(args.phase)
        run_state_path = getattr(args, "run_state", None) or getattr(args, "state", None)
        if transition_target and run_state_path:
            state_file = require_repo_path(repo, run_state_path, "run state")
            status_evidence = state_file.parent / "evidence" / f"{args.phase}-gate.json"
            status_evidence.parent.mkdir(parents=True, exist_ok=True)
            status_payload = dict(result)
            status_payload.setdefault("phase", args.phase)
            status_payload["ready"] = True
            for attr in ("red_test_evidence", "unit_test_evidence", "implementation_manifest"):
                value = getattr(args, attr, None)
                if value:
                    try:
                        status_payload[attr] = str(resolve_repo_path(repo, value).relative_to(repo))
                    except ValueError:
                        status_payload[attr] = str(value)
            status_evidence.write_text(json.dumps(status_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            evidence = status_evidence
            transition = run_state.transition_state(
                repo,
                run_state_path,
                transition_target,
                gate=args.phase,
                gate_status="passed",
                evidence=resolve_repo_path(repo, evidence),
            )
            result["run_state_transition"] = transition
            if not transition["ready"]:
                result["ready"] = False
                result["blocked_reasons"].extend("Run state transition: " + reason for reason in transition["blocked_reasons"])
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result


def verify(args) -> tuple[int, dict]:
    phase_args = without_status_file(args)
    total_started = time.perf_counter()
    prepare_code, prep = timed_phase(args, "prepare", prepare, phase_args)
    clarify_code = 0
    clarify_result = None
    if args.design_doc:
        clarify_code, clarify_result = timed_phase(args, "clarify", clarify, phase_args)
    gate_result = None
    gate_code = 0
    if args.run_gate:
        gate_code, gate_result = timed_phase(args, f"gate:{args.phase}", gate, phase_args)

    maven_result = {"skipped": True}
    maven_started = time.perf_counter()
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
            display_command = ["mvn"] + command[1:]
            try:
                completed = subprocess.run(
                    command,
                    cwd=as_repo(args.repo),
                    text=True,
                    capture_output=True,
                    timeout=DEFAULT_SUBPROCESS_TIMEOUT_SECONDS,
                )
                maven_result = {
                    "skipped": False,
                    "command": " ".join(display_command),
                    "exit_code": completed.returncode,
                    "stdout_tail": completed.stdout[-4000:],
                    "stderr_tail": completed.stderr[-4000:],
                }
            except subprocess.TimeoutExpired as error:
                maven_result = {
                    "skipped": False,
                    "command": " ".join(display_command),
                    "exit_code": 124,
                    "stdout_tail": (error.stdout or "")[-4000:] if isinstance(error.stdout, str) else "",
                    "stderr_tail": f"Maven command timed out after {DEFAULT_SUBPROCESS_TIMEOUT_SECONDS} seconds.",
                }
    trace_event(
        args,
        "maven",
        "finish",
        "skipped" if maven_result.get("skipped") else ("ready" if maven_result.get("exit_code") == 0 else "blocked"),
        int((time.perf_counter() - maven_started) * 1000),
    )
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
            "state": str(getattr(args, "state", "") or getattr(args, "run_state", "") or ""),
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
    trace_failures = getattr(args, "_trace_failures", [])
    if trace_failures:
        result["execution_trace"] = {
            "ready": False,
            "blocked_reasons": trace_failures,
            "warnings": [],
        }
        exit_code = max(exit_code, 2)
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
    trace_event(
        args,
        "verify",
        "finish",
        "ready" if exit_code == 0 else "blocked",
        int((time.perf_counter() - total_started) * 1000),
        [str(args.status_file)] if args.status_file else None,
    )
    final_trace_failures = getattr(args, "_trace_failures", [])
    if final_trace_failures:
        result["execution_trace"] = {
            "ready": False,
            "blocked_reasons": final_trace_failures,
            "warnings": [],
        }
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


def doctor(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    result = harness_doctor.evaluate(repo, getattr(args, "strict", False), getattr(args, "state", None))
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result


def install_project(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    full = bool(getattr(args, "full", False))
    target = "all" if full else args.target
    targets = install_targets(target)
    install_root = Path(args.install_root or Path.home()).resolve()
    source_skill = Path(args.source_skill_dir or SCRIPT_DIR.parent).resolve()
    install_external = bool(getattr(args, "install_external", False) or (full and not getattr(args, "skip_external", False)))
    with_hooks = bool(getattr(args, "with_hooks", False) or full)
    run_doctor = bool(getattr(args, "doctor", False) or full)
    runtime = getattr(args, "runtime", "claude")
    actions: list[dict] = []
    action_results: list[dict] = []
    blockers: list[str] = []
    installed_skills: list[dict] = []

    if not (source_skill / "SKILL.md").exists():
        blockers.append(f"Source skill is missing SKILL.md: {source_skill}")

    skill_targets = [
        {"target": name, "path": str(install_root.joinpath(*INSTALL_TARGETS[name]))}
        for name in targets
    ]
    actions.append({"id": "copy-skill", "description": "Copy e2e-dev-harness into runtime skill directories.", "targets": skill_targets})

    if install_external:
        if not shutil.which("gitnexus"):
            actions.append({"id": "install-gitnexus", "command": "npm install -g gitnexus", "cwd": str(repo)})
        if not shutil.which("graphify"):
            actions.append({"id": "install-graphify", "command": f"{sys.executable} -m pip install --user graphifyy", "cwd": str(repo)})

    if with_hooks:
        actions.append({
            "id": "install-hooks",
            "description": f"Install {runtime} hook configuration into the current project.",
            "command": f"{sys.executable} {SCRIPT_DIR / 'install_hooks.py'} {repo} --runtime {runtime} --json",
            "cwd": str(repo),
        })

    if run_doctor:
        actions.append({
            "id": "doctor",
            "description": "Run e2e-dev-harness doctor against the current project.",
            "command": f"{sys.executable} {Path(__file__).resolve()} doctor {repo} --json",
            "cwd": str(repo),
        })

    result = {
        "schema": "e2e-dev-harness.install.v1",
        "project_root": str(repo),
        "source_skill_dir": str(source_skill),
        "install_root": str(install_root),
        "targets": targets,
        "full": full,
        "runtime": runtime,
        "executed": bool(args.yes),
        "actions": actions,
        "action_results": action_results,
        "installed_skills": installed_skills,
        "ready": not blockers,
        "blocked_reasons": blockers,
        "warnings": [],
    }

    if result["ready"] and args.yes:
        for skill_target in skill_targets:
            copied = copy_skill_tree(source_skill, Path(skill_target["path"]))
            installed_skills.append({"target": skill_target["target"], **copied})
        for action in actions:
            if action["id"] == "copy-skill":
                continue
            if action["id"] == "install-hooks":
                hook_result = install_hooks.install(repo, runtime)
                action_results.append({"action": action["id"], "exit_code": 0 if hook_result["ready"] else 2, "result": hook_result})
            elif action["id"] == "doctor":
                doctor_result = harness_doctor.evaluate(repo)
                action_results.append({"action": action["id"], "exit_code": 0 if doctor_result["ready"] else 2, "result": doctor_result})
            else:
                command = ["npm", "install", "-g", "gitnexus"] if action["id"] == "install-gitnexus" else [sys.executable, "-m", "pip", "install", "--user", "graphifyy"]
                action_results.append({"action": action["id"], **run_install_command(command, repo)})
            if action_results[-1]["exit_code"] != 0:
                result["ready"] = False
                result["blocked_reasons"].append(f"Action failed: {action['id']}")
                break
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result


def pre_code(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    paths = list(args.path or [])
    if args.patch:
        patch_path = resolve_repo_path(repo, args.patch)
        patch_text = patch_path.read_text(encoding="utf-8", errors="replace") if patch_path and patch_path.exists() else ""
        paths.extend(Path(path) for path in phase_guard.paths_from_patch(patch_text))
    if args.command_text:
        paths.extend(Path(path) for path in phase_guard.paths_from_shell_command(args.command_text))
    result = phase_guard.validate_action(
        repo,
        args.tool,
        paths,
        args.lock,
        args.run_dir,
        command_text=args.command_text,
    )
    hook_status = runtime_hook_status(repo)
    result["pre_code"] = True
    result["tool"] = args.tool
    result["paths_checked"] = [str(path) for path in paths]
    result["hook_status"] = hook_status
    if not hook_status["ready"]:
        result["ready"] = False
        result.setdefault("blocked_reasons", []).append(
            "Runtime hook config is present but not enforcing; repair hooks with install_hooks.py or remove the broken runtime hook directory before relying on portable pre-code."
        )
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result


def test_impact(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    if args.validate_plan:
        result = test_impact_plan.validate(repo, args.validate_plan, args.unit_test_evidence)
        write_status(args.status_file, result)
        return (0 if result["ready"] else 2), result
    changed_files = test_impact_plan.parse_changed_files(resolve_repo_path(repo, args.changed_files))
    result = test_impact_plan.build_plan(repo, changed_files, resolve_repo_path(repo, args.dependency_report))
    if args.output:
        output = require_repo_path(repo, args.output, "test impact output")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_status(args.status_file, result)
    return 0, result


def service_design(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    templates_written: list[str] = []
    service_design_dir = getattr(args, "service_design_dir", None)
    emit_templates = getattr(args, "emit_template", None) or []
    if emit_templates:
        target_dir = require_repo_path(repo, service_design_dir or Path("docs/agent-runs/service-designs"), "service design directory")
        target_dir.mkdir(parents=True, exist_ok=True)
        global_design_text = posix(getattr(args, "global_design", ""))
        for service in emit_templates:
            slug = orchestration_plan.service_slug(str(service))
            target = target_dir / f"{slug}.md"
            if not target.exists():
                global_design_path = resolve_repo_path(repo, getattr(args, "global_design", None))
                target.write_text(
                    service_design_template(str(service), global_design_text, optional_text(global_design_path)),
                    encoding="utf-8",
                )
            templates_written.append(posix(target.relative_to(repo)))
        args.service_design_dir = target_dir
    result = service_design_gate.validate(repo, args.global_design, args.service_design_dir, args.service_design)
    if templates_written:
        result["templates_written"] = templates_written
    run_state_path = getattr(args, "run_state", None)
    if run_state_path and result["ready"]:
        dispatch_blockers = service_design_dispatch_blockers(repo, run_state_path)
        if dispatch_blockers:
            result["ready"] = False
            result.setdefault("blocked_reasons", []).extend(dispatch_blockers)
            result["service_design_dispatch"] = {"ready": False, "blocked_reasons": dispatch_blockers}
            write_status(args.status_file, result)
            return 2, result
        transition = run_state.transition_state(
            repo,
            run_state_path,
            "PLANNED",
            gate="service_design",
            gate_status="passed",
            evidence=args.service_design_dir or (args.service_design[0] if args.service_design else None),
        )
        result["run_state_transition"] = transition
        if not transition["ready"]:
            result["ready"] = False
            result["blocked_reasons"].extend("Run state transition: " + reason for reason in transition["blocked_reasons"])
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result


def agent_task(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    lease_seconds = getattr(args, "lease_seconds", agent_scheduler.DEFAULT_LEASE_SECONDS)
    if args.action == "claim":
        result = agent_scheduler.claim(repo, args.schedule, args.task_id or "", args.agent or "agent", args.state, lease_seconds)
    elif args.action == "renew":
        result = agent_scheduler.renew(repo, args.schedule, args.task_id or "", args.agent or "agent", args.state, lease_seconds)
    elif args.action == "reclaim":
        result = agent_scheduler.reclaim(
            repo, args.schedule, args.task_id or "", args.agent or "agent", args.state,
            getattr(args, "force", False), lease_seconds,
        )
    elif args.action == "complete":
        result = agent_scheduler.complete(
            repo,
            args.schedule,
            args.task_id or "",
            args.agent or "agent",
            args.state,
            args.evidence or [],
            allow_local_completion=getattr(args, "allow_local_completion", False),
        )
    else:
        schedule_path = args.schedule if args.schedule.is_absolute() else repo / args.schedule
        schedule = json.loads(schedule_path.read_text(encoding="utf-8")) if schedule_path.exists() else {}
        result = agent_scheduler.validate_schedule(
            schedule,
            args.service or [],
            args.require_claims,
            args.require_completed,
        )
        result["schedule"] = str(schedule_path)
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result


def runtime_capabilities(args) -> tuple[int, dict]:
    result = dispatcher.runtime_capabilities(args.runtime)
    result.update({"ready": True, "blocked_reasons": [], "warnings": []})
    write_status(args.status_file, result)
    return 0, result


def dispatch_next(args) -> tuple[int, dict]:
    return coordinator_flow.dispatch_next(args)


def dispatch_beat(args) -> tuple[int, dict]:
    return coordinator_flow.dispatch_beat(args)


def dispatch_complete(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    result = dispatcher.dispatch_complete(
        repo,
        args.schedule,
        args.state,
        args.task_id,
        args.agent or "agent",
        args.evidence or [],
        manual_recovery=getattr(args, "manual_recovery", False),
    )
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result


def dispatch_ack(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    result = dispatcher.dispatch_ack(
        repo,
        args.state,
        args.task_id,
        args.agent,
        args.worker_handle,
        args.worker_session or "",
    )
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result


def dispatch_status(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    result = dispatcher.dispatch_status(repo, args.schedule, args.state)
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result


def ac_progress(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    result = ac_progress_gate.validate(
        repo,
        args.design_doc,
        args.service_design,
        args.coverage_matrix,
        args.implementation_manifest,
        args.unit_test_evidence,
    )
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result


def next_step(args) -> tuple[int, dict]:
    return coordinator_flow.next_step(args)


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


def add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json-full",
        "--full-json",
        dest="json_full",
        action="store_true",
        help="Print the complete JSON result to stdout.",
    )
    parser.add_argument("--compact-output", action="store_true", help="Print compact coordinator-safe stdout; this is the default.")


def add_full_json_arg(parser: argparse.ArgumentParser) -> None:
    return None


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Create a controlled harness run and starter design artifact.")
    start_parser.add_argument("repo", nargs="?", default=".", type=Path)
    start_parser.add_argument("--feature", required=True)
    start_parser.add_argument("--request", default="")
    start_parser.add_argument("--design-doc", type=Path)
    start_parser.add_argument("--agent-run-dir", type=Path)
    start_parser.add_argument("--run-id")
    start_parser.add_argument("--run-date")
    start_parser.add_argument("--phase-mode", choices=["auto", "manual"], default="auto")
    start_parser.add_argument("--workflow-profile", default="standard")
    start_parser.add_argument("--phase-profile", type=Path)
    start_parser.add_argument("--force", action="store_true")
    start_parser.add_argument("--status-file", type=Path)

    prepare_parser = subparsers.add_parser("prepare", help="Run pre-clarification/pre-planning discovery.")
    add_prepare_args(prepare_parser)

    clarify_parser = subparsers.add_parser("clarify", help="Run the clarification gate.")
    clarify_parser.add_argument("repo", nargs="?", default=".", type=Path)
    clarify_parser.add_argument("--design-doc", required=True, type=Path)
    clarify_parser.set_defaults(require_intent=True, require_user_confirmation=True)
    clarify_parser.add_argument("--require-intent", dest="require_intent", action="store_true")
    clarify_parser.add_argument("--no-require-intent", dest="require_intent", action="store_false")
    clarify_parser.add_argument("--require-user-confirmation", dest="require_user_confirmation", action="store_true")
    clarify_parser.add_argument("--no-require-user-confirmation", dest="require_user_confirmation", action="store_false")
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
    gate_parser.add_argument("--changed-files", type=Path)
    gate_parser.add_argument("--test-impact-plan", type=Path)
    gate_parser.add_argument("--base-ref")
    gate_parser.add_argument("--checkpoint-mode", choices=["off", "advisory", "required"], default="off")
    gate_parser.add_argument("--confirmation-dir", action="append", type=Path)
    gate_parser.add_argument("--require-intent", action="store_true")
    gate_parser.add_argument("--tdd-mode", choices=["off", "advisory", "basic", "strict", "auto"], default="auto")
    gate_parser.add_argument("--workflow-tier", choices=task_tier.TIERS, default="auto")
    gate_parser.add_argument("--rework-dir", action="append", type=Path)
    gate_parser.add_argument("--review-dir", action="append", type=Path)
    gate_parser.add_argument("--review-profile", type=Path, default=Path(DEFAULT_REVIEW_PROFILE))
    gate_parser.add_argument("--handoff-dir", action="append", type=Path)
    gate_parser.add_argument("--contract-dir", action="append", type=Path)
    gate_parser.add_argument("--require-contracts", action="store_true")
    gate_parser.add_argument("--require-handoffs", action="store_true")
    gate_parser.add_argument("--require-semantic-reviews", action="store_true")
    gate_parser.add_argument("--skip-spring-static-check", action="store_true")
    gate_parser.add_argument("--run-state", type=Path)
    gate_parser.add_argument("--no-harness-state", action="store_true")
    gate_parser.add_argument("--harness-state-approval", type=Path)
    gate_parser.add_argument("--require-gitnexus-evidence", choices=["auto", "strict", "off"], default="auto")
    gate_parser.add_argument("--gitnexus-degradation", type=Path)
    gate_parser.add_argument("--status-file", type=Path)
    add_full_json_arg(gate_parser)

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
    verify_parser.add_argument("--changed-files", type=Path)
    verify_parser.add_argument("--test-impact-plan", type=Path)
    verify_parser.add_argument("--base-ref")
    verify_parser.add_argument("--checkpoint-mode", choices=["off", "advisory", "required"], default="off")
    verify_parser.add_argument("--confirmation-dir", action="append", type=Path)
    verify_parser.add_argument("--require-intent", action="store_true")
    verify_parser.add_argument("--tdd-mode", choices=["off", "advisory", "basic", "strict", "auto"], default="auto")
    verify_parser.add_argument("--rework-dir", action="append", type=Path)
    verify_parser.add_argument("--review-dir", action="append", type=Path)
    verify_parser.add_argument("--review-profile", type=Path, default=Path(DEFAULT_REVIEW_PROFILE))
    verify_parser.add_argument("--handoff-dir", action="append", type=Path)
    verify_parser.add_argument("--contract-dir", action="append", type=Path)
    verify_parser.add_argument("--require-contracts", action="store_true")
    verify_parser.add_argument("--require-handoffs", action="store_true")
    verify_parser.add_argument("--require-semantic-reviews", action="store_true")
    verify_parser.add_argument("--skip-spring-static-check", action="store_true")
    verify_parser.add_argument("--run-state", type=Path)
    verify_parser.add_argument("--no-harness-state", action="store_true")
    verify_parser.add_argument("--harness-state-approval", type=Path)
    verify_parser.add_argument("--require-gitnexus-evidence", choices=["auto", "strict", "off"], default="auto")
    verify_parser.add_argument("--gitnexus-degradation", type=Path)
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
    verify_parser.add_argument("--trace-file", type=Path)

    guard_parser = subparsers.add_parser("guard", help="Run strict workflow guard against a verify status artifact.")
    guard_parser.add_argument("repo", nargs="?", default=".", type=Path)
    guard_parser.add_argument("--verify-status", required=True, type=Path)
    guard_parser.add_argument("--strict", action="store_true")
    guard_parser.add_argument("--require-completion", action="store_true")
    guard_parser.add_argument("--approval-file", type=Path)
    guard_parser.add_argument("--status-file", type=Path)

    doctor_parser = subparsers.add_parser("doctor", help="Check install, runtime hooks, and local tool readiness.")
    doctor_parser.add_argument("repo", nargs="?", default=".", type=Path)
    doctor_parser.add_argument("--strict", action="store_true", help="Treat warnings as blockers.")
    doctor_parser.add_argument("--state", type=Path, help="Check consistency for docs/agent-runs/<run>/run-state.json.")
    doctor_parser.add_argument("--json", action="store_true", help="Print JSON output.")
    doctor_parser.add_argument("--status-file", type=Path)

    install_parser = subparsers.add_parser("install", help="Install latest skill copies and project-local hooks for the current project.")
    install_parser.add_argument("repo", nargs="?", default=".", type=Path)
    install_parser.add_argument("--target", choices=["codex", "claude", "agents", "all"], default="codex")
    install_parser.add_argument("--install-root", type=Path, default=Path.home())
    install_parser.add_argument("--source-skill-dir", type=Path)
    install_parser.add_argument("--runtime", choices=["claude", "codex", "gemini", "opencode"], default="claude")
    install_parser.add_argument("--full", action="store_true", help="Preset: --target all --install-external --with-hooks --runtime claude --doctor.")
    install_parser.add_argument("--yes", action="store_true", help="Execute planned writes and install commands.")
    install_parser.add_argument("--install-external", action="store_true")
    install_parser.add_argument("--skip-external", action="store_true")
    install_parser.add_argument("--with-hooks", action="store_true")
    install_parser.add_argument("--doctor", action="store_true")
    install_parser.add_argument("--status-file", type=Path)

    pre_code_parser = subparsers.add_parser("pre-code", help="Check whether a planned code write is allowed by phase lock.")
    pre_code_parser.add_argument("repo", nargs="?", default=".", type=Path)
    pre_code_parser.add_argument("--tool", default="Edit")
    pre_code_parser.add_argument("--path", action="append", type=Path)
    pre_code_parser.add_argument("--patch", type=Path, help="Patch file to inspect for edited paths.")
    pre_code_parser.add_argument("--command-text", default="", help="Shell command text to inspect for write targets.")
    pre_code_parser.add_argument("--lock", type=Path)
    pre_code_parser.add_argument("--run-dir", type=Path)
    pre_code_parser.add_argument("--status-file", type=Path)

    test_impact_parser = subparsers.add_parser("test-impact", help="Create or validate an incremental test impact plan.")
    test_impact_parser.add_argument("repo", nargs="?", default=".", type=Path)
    test_impact_parser.add_argument("--changed-files", type=Path)
    test_impact_parser.add_argument("--dependency-report", type=Path)
    test_impact_parser.add_argument("--output", type=Path)
    test_impact_parser.add_argument("--validate", dest="validate_plan", type=Path)
    test_impact_parser.add_argument("--unit-test-evidence", type=Path)
    test_impact_parser.add_argument("--status-file", type=Path)

    service_design_parser = subparsers.add_parser("service-design", help="Validate service design slices against the global design.")
    service_design_parser.add_argument("repo", nargs="?", default=".", type=Path)
    service_design_parser.add_argument("--global-design", required=True, type=Path)
    service_design_parser.add_argument("--service-design-dir", type=Path)
    service_design_parser.add_argument("--service-design", action="append", type=Path)
    service_design_parser.add_argument("--emit-template", action="append", help="Write a pre-filled service-design template for the given service; can be repeated.")
    service_design_parser.add_argument("--run-state", type=Path)
    service_design_parser.add_argument("--status-file", type=Path)

    agent_task_parser = subparsers.add_parser("agent-task", help="Claim, complete, or validate scheduled agent tasks.")
    agent_task_parser.add_argument("repo", nargs="?", default=".", type=Path)
    agent_task_parser.add_argument("--schedule", required=True, type=Path)
    agent_task_parser.add_argument("--action", choices=["claim", "complete", "validate", "renew", "reclaim"], required=True)
    agent_task_parser.add_argument("--task-id")
    agent_task_parser.add_argument("--agent", default="")
    agent_task_parser.add_argument("--state", type=Path)
    agent_task_parser.add_argument("--service", action="append")
    agent_task_parser.add_argument("--require-claims", action="store_true")
    agent_task_parser.add_argument("--require-completed", action="store_true")
    agent_task_parser.add_argument("--evidence", action="append")
    agent_task_parser.add_argument("--allow-local-completion", action="store_true")
    agent_task_parser.add_argument("--lease-seconds", type=int, default=agent_scheduler.DEFAULT_LEASE_SECONDS)
    agent_task_parser.add_argument("--force", action="store_true", help="Reclaim an active (non-stale) claim.")
    agent_task_parser.add_argument("--status-file", type=Path)

    capabilities_parser = subparsers.add_parser("runtime-capabilities", help="Report runtime multi-agent dispatch capabilities.")
    capabilities_parser.add_argument("repo", nargs="?", default=".", type=Path)
    capabilities_parser.add_argument("--runtime", default="claude-code")
    capabilities_parser.add_argument("--status-file", type=Path)

    dispatch_next_parser = subparsers.add_parser("dispatch-next", help="Claim the next ready scheduled task and create a subagent dispatch packet.")
    dispatch_next_parser.add_argument("repo", nargs="?", default=".", type=Path)
    dispatch_next_parser.add_argument("--schedule", required=True, type=Path)
    dispatch_next_parser.add_argument("--state", required=True, type=Path)
    dispatch_next_parser.add_argument("--runtime", default="claude-code")
    dispatch_next_parser.add_argument("--coordinator-agent", default="coordinator-agent")
    dispatch_next_parser.add_argument("--developer-session", default="coordinator-session")
    dispatch_next_parser.add_argument("--max-files", type=int, default=12)
    dispatch_next_parser.add_argument("--max-chars", type=int, default=120_000)
    dispatch_next_parser.add_argument("--status-file", type=Path)
    add_full_json_arg(dispatch_next_parser)

    dispatch_beat_parser = subparsers.add_parser("dispatch-beat", help="Dispatch a beat wave of ready scheduled tasks.")
    dispatch_beat_parser.add_argument("repo", nargs="?", default=".", type=Path)
    dispatch_beat_parser.add_argument("--schedule", required=True, type=Path)
    dispatch_beat_parser.add_argument("--state", required=True, type=Path)
    dispatch_beat_parser.add_argument("--runtime", default="claude-code")
    dispatch_beat_parser.add_argument("--coordinator-agent", default="coordinator-agent")
    dispatch_beat_parser.add_argument("--developer-session", default="coordinator-session")
    dispatch_beat_parser.add_argument("--max-workers", type=int, default=1)
    dispatch_beat_parser.add_argument("--max-files", type=int, default=12)
    dispatch_beat_parser.add_argument("--max-chars", type=int, default=120_000)
    dispatch_beat_parser.add_argument("--status-file", type=Path)
    add_full_json_arg(dispatch_beat_parser)

    dispatch_complete_parser = subparsers.add_parser("dispatch-complete", help="Complete a dispatched task with scheduled evidence.")
    dispatch_complete_parser.add_argument("repo", nargs="?", default=".", type=Path)
    dispatch_complete_parser.add_argument("--schedule", required=True, type=Path)
    dispatch_complete_parser.add_argument("--state", type=Path)
    dispatch_complete_parser.add_argument("--task-id", required=True)
    dispatch_complete_parser.add_argument("--agent", default="")
    dispatch_complete_parser.add_argument("--evidence", action="append")
    dispatch_complete_parser.add_argument("--manual-recovery", action="store_true")
    dispatch_complete_parser.add_argument("--status-file", type=Path)
    add_full_json_arg(dispatch_complete_parser)

    dispatch_ack_parser = subparsers.add_parser("dispatch-ack", help="Record the runtime worker handle after a spawn request succeeds.")
    dispatch_ack_parser.add_argument("repo", nargs="?", default=".", type=Path)
    dispatch_ack_parser.add_argument("--state", required=True, type=Path)
    dispatch_ack_parser.add_argument("--task-id", required=True)
    dispatch_ack_parser.add_argument("--agent", required=True)
    dispatch_ack_parser.add_argument("--worker-handle", required=True)
    dispatch_ack_parser.add_argument("--worker-session", default="")
    dispatch_ack_parser.add_argument("--status-file", type=Path)
    add_full_json_arg(dispatch_ack_parser)

    dispatch_status_parser = subparsers.add_parser("dispatch-status", help="Summarize dispatch state and open scheduled tasks.")
    dispatch_status_parser.add_argument("repo", nargs="?", default=".", type=Path)
    dispatch_status_parser.add_argument("--schedule", required=True, type=Path)
    dispatch_status_parser.add_argument("--state", type=Path)
    dispatch_status_parser.add_argument("--status-file", type=Path)

    ac_progress_parser = subparsers.add_parser("ac-progress", help="Block R3 review until all assigned ACs have implementation and test evidence.")
    ac_progress_parser.add_argument("repo", nargs="?", default=".", type=Path)
    ac_progress_parser.add_argument("--design-doc", type=Path)
    ac_progress_parser.add_argument("--service-design", type=Path)
    ac_progress_parser.add_argument("--coverage-matrix", required=True, type=Path)
    ac_progress_parser.add_argument("--implementation-manifest", required=True, type=Path)
    ac_progress_parser.add_argument("--unit-test-evidence", required=True, type=Path)
    ac_progress_parser.add_argument("--status-file", type=Path)

    next_parser = subparsers.add_parser("next", help="Show the next allowed harness action from run-state.")
    next_parser.add_argument("repo", nargs="?", default=".", type=Path)
    next_parser.add_argument("--state", required=True, type=Path)
    next_parser.add_argument("--runtime", default="claude-code", help="Runtime used in suggested dispatch commands.")
    next_parser.add_argument("--status-file", type=Path)
    add_full_json_arg(next_parser)

    for output_parser in (
        start_parser,
        prepare_parser,
        clarify_parser,
        plan_parser,
        gate_parser,
        verify_parser,
        guard_parser,
        doctor_parser,
        install_parser,
        pre_code_parser,
        test_impact_parser,
        service_design_parser,
        agent_task_parser,
        capabilities_parser,
        dispatch_next_parser,
        dispatch_beat_parser,
        dispatch_complete_parser,
        dispatch_ack_parser,
        dispatch_status_parser,
        ac_progress_parser,
        next_parser,
    ):
        add_output_args(output_parser)

    args = parser.parse_args()
    try:
        if args.command == "start":
            exit_code, result = start(args)
        elif args.command == "prepare":
            exit_code, result = prepare(args)
        elif args.command == "clarify":
            exit_code, result = clarify(args)
        elif args.command == "plan":
            exit_code, result = plan(args)
        elif args.command == "gate":
            exit_code, result = gate(args)
        elif args.command == "guard":
            exit_code, result = guard(args)
        elif args.command == "doctor":
            exit_code, result = doctor(args)
        elif args.command == "install":
            exit_code, result = install_project(args)
        elif args.command == "pre-code":
            exit_code, result = pre_code(args)
        elif args.command == "test-impact":
            exit_code, result = test_impact(args)
        elif args.command == "service-design":
            exit_code, result = service_design(args)
        elif args.command == "agent-task":
            exit_code, result = agent_task(args)
        elif args.command == "runtime-capabilities":
            exit_code, result = runtime_capabilities(args)
        elif args.command == "dispatch-next":
            exit_code, result = dispatch_next(args)
        elif args.command == "dispatch-beat":
            exit_code, result = dispatch_beat(args)
        elif args.command == "dispatch-complete":
            exit_code, result = dispatch_complete(args)
        elif args.command == "dispatch-ack":
            exit_code, result = dispatch_ack(args)
        elif args.command == "dispatch-status":
            exit_code, result = dispatch_status(args)
        elif args.command == "ac-progress":
            exit_code, result = ac_progress(args)
        elif args.command == "next":
            exit_code, result = next_step(args)
        else:
            exit_code, result = verify(args)
    except (FileNotFoundError, ValueError) as error:
        print(f"e2e-dev-harness error: {error}", file=sys.stderr)
        return 2

    if getattr(args, "json_full", False):
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return exit_code
    repo = as_repo(getattr(args, "repo", Path(".")))
    full_result_path = output_contract.write_full_result(repo, args.command or "verify", result, args)
    coordinator_summary_path = ""
    if args.command == "next":
        summary = session_checkpoint.create_coordinator_summary(
            repo,
            getattr(args, "state"),
            result,
            str(full_result_path),
        )
        coordinator_summary_path = summary.get("coordinator_summary", "")
        result["coordinator_summary_path"] = coordinator_summary_path
    compact = output_contract.compact_payload(
        repo,
        args.command or "verify",
        result,
        full_result_path,
        coordinator_summary_path,
    )
    print(output_contract.render_json(compact))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
