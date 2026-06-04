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
import event_log  # noqa: E402
import execution_trace  # noqa: E402
import install_hooks  # noqa: E402
import harness_doctor  # noqa: E402
# Re-exported so tests can patch e2e_dev_harness.implementation_gate (shared module object).
import implementation_gate  # noqa: E402, F401
import kg_refresh  # noqa: E402
import harness_verify  # noqa: E402
import memory_capture  # noqa: E402
import orchestration_plan  # noqa: E402
import output_contract  # noqa: E402
import phase_guard  # noqa: E402
import preflight as preflight_checks  # noqa: E402
import run_state  # noqa: E402
import session_checkpoint  # noqa: E402
import superpowers_probe  # noqa: E402
import task_tier  # noqa: E402
import test_impact_plan  # noqa: E402
import workflow_guard  # noqa: E402
from e2e_harness.cli.commands import agent_task as agent_task_command  # noqa: E402
from e2e_harness.cli.commands import ac_progress as ac_progress_command  # noqa: E402
from e2e_harness.cli.commands import clarify as clarify_command  # noqa: E402
from e2e_harness.cli.commands import dispatch as dispatch_command  # noqa: E402
from e2e_harness.cli.commands import doctor as doctor_command  # noqa: E402
from e2e_harness.cli.commands import gate as gate_command  # noqa: E402
from e2e_harness.cli.commands import guard as guard_command  # noqa: E402
from e2e_harness.cli.commands import install as install_command  # noqa: E402
from e2e_harness.cli.commands import next as next_command  # noqa: E402
from e2e_harness.cli.commands import plan as plan_command  # noqa: E402
from e2e_harness.cli.commands import prepare as prepare_command  # noqa: E402
from e2e_harness.cli.commands import preflight as preflight_command  # noqa: E402
from e2e_harness.cli.commands import pre_code as pre_code_command  # noqa: E402
from e2e_harness.cli.commands import recover as recover_command  # noqa: E402
from e2e_harness.cli.commands import runtime_capabilities as runtime_capabilities_command  # noqa: E402
from e2e_harness.cli.commands import service_design as service_design_command  # noqa: E402
from e2e_harness.cli.commands import start as start_command  # noqa: E402
from e2e_harness.cli.commands import timeline as timeline_command  # noqa: E402
from e2e_harness.cli.commands import test_impact as test_impact_command  # noqa: E402
from e2e_harness.cli.commands import verify as verify_command  # noqa: E402
from e2e_harness.cli.parser import add_output_args  # noqa: E402, F401
from e2e_harness.cli.status import write_status  # noqa: E402, F401


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


def blocked_reason_codes_from_result(result: dict) -> list[str]:
    codes: list[str] = []
    for key in ("blocked_reason_codes", "reason_codes"):
        values = result.get(key)
        if isinstance(values, list):
            for value in values:
                append_unique(codes, str(value).strip())
    blockers = result.get("blockers")
    if isinstance(blockers, list):
        for item in blockers:
            if isinstance(item, dict):
                append_unique(codes, str(item.get("code", "")).strip())
            else:
                append_unique(codes, str(item).strip())
    return codes


def next_command_from_result(result: dict) -> str:
    next_action = result.get("next_action")
    if isinstance(next_action, dict):
        for key in ("dispatch_command", "command", "next_command"):
            value = str(next_action.get(key, "")).strip()
            if value:
                return value
    execution_packet = result.get("execution_packet")
    if isinstance(execution_packet, dict):
        value = str(execution_packet.get("primary_command", "")).strip()
        if value:
            return value
    for key in ("next_command", "recommended_command", "next_beat_hint"):
        value = str(result.get(key, "")).strip()
        if value:
            return value
    return ""


def emit_command_event(repo: Path, command: str, args: argparse.Namespace, result: dict, exit_code: int) -> str:
    state_path = run_state_path_from_args(repo, args, result)
    run_dir = state_path.parent if state_path else repo / ".e2e"
    lifecycle = lifecycle_from_state(repo, args, result) if state_path else str(result.get("lifecycle", "") or "UNKNOWN")
    trace_id = f"{command}-{time.time_ns()}"
    path = event_log.append_command_event(
        run_dir,
        command=command,
        lifecycle=lifecycle,
        status="ok" if exit_code == 0 else "blocked",
        blocked_reason_codes=blocked_reason_codes_from_result(result),
        next_command=next_command_from_result(result),
        trace_id=trace_id,
        run_id=normalize_cli_path(repo, run_dir),
    )
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
    return start_command.design_template(feature, request)


def load_phase_profile(repo: Path, path: Path | None) -> tuple[dict, list[str]]:
    return start_command.load_phase_profile(repo, path)


def workflow_plan_for_start(
    phase_mode: str,
    workflow_profile: str,
    phase_profile: dict | None = None,
    current_lifecycle: str = "CREATED",
) -> dict:
    return start_command.workflow_plan_for_start(phase_mode, workflow_profile, phase_profile, current_lifecycle)


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
    return prepare_command.run_from_args(args)


def start(args) -> tuple[int, dict]:
    return start_command.run_from_args(args)


def clarification_dispatch_blockers(repo: Path, run_state_path: Path | str | None) -> list[str]:
    return preflight_checks.clarification_dispatch_blockers(repo, run_state_path)


def clarification_dispatch_recovery(repo: Path, run_state_path: Path | str | None, blockers: list[str]) -> dict:
    return preflight_checks.clarification_dispatch_recovery(repo, run_state_path, blockers)


def service_design_dispatch_blockers(repo: Path, run_state_path: Path | str | None) -> list[str]:
    return preflight_checks.service_design_dispatch_blockers(repo, run_state_path)


def tdd_red_dispatch_blockers(repo: Path, run_state_path: Path | str | None) -> list[str]:
    return preflight_checks.tdd_red_dispatch_blockers(repo, run_state_path)


def _preflight_checks() -> list[dict]:
    return preflight_checks.preflight_checks()


def aggregate_preflight_blockers(repo: Path, run_state_path: Path | str | None) -> dict:
    return preflight_checks.aggregate_preflight_blockers(repo, run_state_path)


def preflight(args) -> tuple[int, dict]:
    return preflight_command.run_from_args(args)


def clarify(args) -> tuple[int, dict]:
    return clarify_command.run_from_args(args)


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
    return start_command.role_template_text(role)


def create_role_template_files(repo: Path, artifacts: dict) -> list[str]:
    return start_command.create_role_template_files(repo, artifacts)


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
    return service_design_command.service_design_template(
        service,
        global_design,
        global_design_text=global_design_text,
        merged_members=merged_members,
    )


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
    return plan_command.run_from_args(args)


def gate(args) -> tuple[int, dict]:
    return gate_command.run_from_args(args)


def verify(args) -> tuple[int, dict]:
    return verify_command.run_from_args(args)


def guard(args) -> tuple[int, dict]:
    return guard_command.run_from_args(args)


def doctor(args) -> tuple[int, dict]:
    return doctor_command.run_from_args(args)


def recover(args) -> tuple[int, dict]:
    return recover_command.run_from_args(args)


def timeline(args) -> tuple[int, dict]:
    return timeline_command.run_from_args(args)


def install_project(args) -> tuple[int, dict]:
    return install_command.run_from_args(args)


def pre_code(args) -> tuple[int, dict]:
    return pre_code_command.run_from_args(args)


def test_impact(args) -> tuple[int, dict]:
    return test_impact_command.run_from_args(args)


def service_design(args) -> tuple[int, dict]:
    return service_design_command.run_from_args(args)


def agent_task(args) -> tuple[int, dict]:
    return agent_task_command.run_from_args(args)


def runtime_capabilities(args) -> tuple[int, dict]:
    return runtime_capabilities_command.run_from_args(args)


def dispatch_next(args) -> tuple[int, dict]:
    return dispatch_command.run_next_from_args(args)


def dispatch_beat(args) -> tuple[int, dict]:
    return dispatch_command.run_beat_from_args(args)


def dispatch_complete(args) -> tuple[int, dict]:
    return dispatch_command.run_complete_from_args(args)


def dispatch_ack(args) -> tuple[int, dict]:
    return dispatch_command.run_ack_from_args(args)


def dispatch_status(args) -> tuple[int, dict]:
    return dispatch_command.run_status_from_args(args)


def ac_progress(args) -> tuple[int, dict]:
    return ac_progress_command.run_from_args(args)


def next_step(args) -> tuple[int, dict]:
    return next_command.run_from_args(args)


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


def add_full_json_arg(parser: argparse.ArgumentParser) -> None:
    return None


def gate_phase_clarification_recovery(argv: list[str]) -> str:
    if not argv or argv[0] != "gate":
        return ""
    for index, token in enumerate(argv):
        if token == "--phase" and index + 1 < len(argv) and argv[index + 1] == "clarification":
            break
        if token == "--phase=clarification":
            break
    else:
        return ""
    return (
        "error: gate --phase clarification is not a valid CLI command. "
        "Clarification uses the separate 'clarify' subcommand after the design doc is updated. "
        "If run-state is CREATED, run 'e2e_dev_harness.py dispatch-next --schedule "
        "docs/agent-runs/<run>/agent-schedule.json --state docs/agent-runs/<run>/run-state.json' "
        "to dispatch requirements-clarifier first. "
        "Valid gate --phase values are: planning, implementation, completion."
    )


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
    dispatch_complete_parser.add_argument("--recovery-approval", type=Path)
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
    dispatch_status_parser.add_argument("--write-recovery-request", type=Path)
    dispatch_status_parser.add_argument("--task-id")
    dispatch_status_parser.add_argument("--agent", default="")
    dispatch_status_parser.add_argument("--evidence", action="append")
    dispatch_status_parser.add_argument("--status-file", type=Path)

    recover_parser = subparsers.add_parser("recover", help="Create an auditable recovery plan for a stuck run.")
    recover_parser.add_argument("repo", nargs="?", default=".", type=Path)
    recover_parser.add_argument("--state", required=True, type=Path)
    recover_parser.add_argument("--schedule", type=Path)
    recover_parser.add_argument("--task-id")
    recover_parser.add_argument("--agent", default="")
    recover_parser.add_argument("--evidence", action="append")
    recover_parser.add_argument("--status-file", type=Path)

    timeline_parser = subparsers.add_parser("timeline", help="Write a product-grade run timeline report from enterprise events.")
    timeline_parser.add_argument("repo", nargs="?", default=".", type=Path)
    timeline_parser.add_argument("--state", required=True, type=Path)
    timeline_parser.add_argument("--status-file", type=Path)

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

    preflight_parser = subparsers.add_parser(
        "preflight",
        help="Aggregate every applicable gate blocker for the current run-state in one pass.",
    )
    preflight_parser.add_argument("repo", nargs="?", default=".", type=Path)
    preflight_parser.add_argument("--state", required=True, type=Path)
    preflight_parser.add_argument("--status-file", type=Path)

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
        recover_parser,
        timeline_parser,
        ac_progress_parser,
        next_parser,
        preflight_parser,
    ):
        add_output_args(output_parser)

    recovery = gate_phase_clarification_recovery(sys.argv[1:])
    if recovery:
        print(recovery, file=sys.stderr)
        return 2

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
        elif args.command == "recover":
            exit_code, result = recover(args)
        elif args.command == "timeline":
            exit_code, result = timeline(args)
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
        elif args.command == "preflight":
            exit_code, result = preflight(args)
        else:
            exit_code, result = verify(args)
    except (FileNotFoundError, ValueError) as error:
        print(f"e2e-dev-harness error: {error}", file=sys.stderr)
        return 2

    repo = as_repo(getattr(args, "repo", Path(".")))
    if getattr(args, "json_full", False):
        command_event_path = emit_command_event(repo, args.command or "verify", args, result, exit_code)
        if command_event_path:
            result["command_event_path"] = command_event_path
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return exit_code
    command_event_path = emit_command_event(repo, args.command or "verify", args, result, exit_code)
    if command_event_path:
        result["command_event_path"] = command_event_path
    if result.get("coordinator_summary_path"):
        result["coordinator_summary_path"] = normalize_cli_path(repo, result.get("coordinator_summary_path"))
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
    if args.command == "runtime-capabilities":
        for key in ("runtime", "supports_subagent", "supports_task_hook", "supports_isolated_review", "supports_blocking_stop", "dispatch_mode", "spawn_tool"):
            if key in result:
                compact[key] = result[key]
    if args.command == "recover":
        compact["workflow_stage"] = "RECOVER"
        if isinstance(compact.get("summary"), dict):
            compact["summary"]["workflow_stage"] = "RECOVER"
    if args.command == "timeline":
        compact["workflow_stage"] = "TIMELINE"
        if isinstance(compact.get("summary"), dict):
            compact["summary"]["workflow_stage"] = "TIMELINE"
        for key in ("run_id", "event_count", "timeline_count", "latest_event"):
            compact[key] = result.get(key, {} if key == "latest_event" else 0)
    print(output_contract.render_json(compact))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
