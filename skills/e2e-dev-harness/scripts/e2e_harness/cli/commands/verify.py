"""Verify command facade."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path


def _legacy_cli():
    return importlib.import_module("e2e_dev_harness")


def run(
    repo: Path,
    design_doc: Path | None = None,
    run_gate: bool = False,
    phase: str = "planning",
    skip_maven: bool = False,
    module: str | None = None,
    strict_workflow: bool = False,
    workflow_tier: str = "auto",
    workflow_approval: Path | None = None,
    harness: bool = False,
    state: Path | None = None,
    run_state: Path | None = None,
    policy: Path | None = None,
    strict_artifacts: bool = False,
    run_completion_gate: bool = False,
    summary_json: Path | None = None,
    summary_md: Path | None = None,
    trace_file: Path | None = None,
    status_file: Path | None = None,
    skip_spring_static_check: bool = False,
    dependency_scan_mode: str = "auto",
    write_dependency_report: bool = True,
    implementation_manifest: Path | None = None,
    require_semantic_reviews: bool = False,
    require_contracts: bool = False,
    require_handoffs: bool = False,
    require_requirements_archive: bool = False,
    **extra,
) -> tuple[int, dict]:
    args = argparse.Namespace(
        repo=repo,
        design_doc=design_doc,
        run_gate=run_gate,
        phase=phase,
        skip_maven=skip_maven,
        module=module,
        strict_workflow=strict_workflow,
        workflow_tier=workflow_tier,
        workflow_approval=workflow_approval,
        harness=harness,
        state=state,
        run_state=run_state,
        policy=policy,
        strict_artifacts=strict_artifacts,
        run_completion_gate=run_completion_gate,
        summary_json=summary_json,
        summary_md=summary_md,
        trace_file=trace_file,
        status_file=status_file,
        skip_spring_static_check=skip_spring_static_check,
        dependency_scan_mode=dependency_scan_mode,
        write_dependency_report=write_dependency_report,
        implementation_manifest=implementation_manifest,
        require_semantic_reviews=require_semantic_reviews,
        require_contracts=require_contracts,
        require_handoffs=require_handoffs,
        require_requirements_archive=require_requirements_archive,
        **extra,
    )
    return run_from_args(args)


def run_from_args(args) -> tuple[int, dict]:
    legacy = _legacy_cli()
    phase_args = legacy.without_status_file(args)
    total_started = legacy.time.perf_counter()
    prepare_code, prep = legacy.timed_phase(args, "prepare", legacy.prepare, phase_args)
    clarify_code = 0
    clarify_result = None
    if getattr(args, "design_doc", None):
        clarify_code, clarify_result = legacy.timed_phase(args, "clarify", legacy.clarify, phase_args)
    gate_result = None
    gate_code = 0
    if getattr(args, "run_gate", False):
        gate_code, gate_result = legacy.timed_phase(args, f"gate:{args.phase}", legacy.gate, phase_args)

    maven_result = {"skipped": True}
    maven_started = legacy.time.perf_counter()
    if not getattr(args, "skip_maven", False):
        module = getattr(args, "module", None)
        command = ["mvn", "test"] if not module else ["mvn", "-pl", module, "-am", "test"]
        maven_executable = legacy.shutil.which("mvn") or legacy.shutil.which("mvn.cmd")
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
                completed = legacy.subprocess.run(
                    command,
                    cwd=legacy.as_repo(args.repo),
                    text=True,
                    capture_output=True,
                    timeout=legacy.DEFAULT_SUBPROCESS_TIMEOUT_SECONDS,
                )
                maven_result = {
                    "skipped": False,
                    "command": " ".join(display_command),
                    "exit_code": completed.returncode,
                    "stdout_tail": completed.stdout[-4000:],
                    "stderr_tail": completed.stderr[-4000:],
                }
            except legacy.subprocess.TimeoutExpired as error:
                maven_result = {
                    "skipped": False,
                    "command": " ".join(display_command),
                    "exit_code": 124,
                    "stdout_tail": (error.stdout or "")[-4000:] if isinstance(error.stdout, str) else "",
                    "stderr_tail": f"Maven command timed out after {legacy.DEFAULT_SUBPROCESS_TIMEOUT_SECONDS} seconds.",
                }
    legacy.trace_event(
        args,
        "maven",
        "finish",
        "skipped" if maven_result.get("skipped") else ("ready" if maven_result.get("exit_code") == 0 else "blocked"),
        int((legacy.time.perf_counter() - maven_started) * 1000),
    )
    result = {
        "workflow": {
            "strict": getattr(args, "strict_workflow", False),
            "tier": getattr(args, "workflow_tier", "auto"),
            "harness": getattr(args, "harness", False),
            "phase": args.phase,
            "run_gate": getattr(args, "run_gate", False),
            "skip_maven": getattr(args, "skip_maven", False),
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
    exit_code = max(
        prepare_code,
        clarify_code,
        gate_code,
        maven_result.get("exit_code", 0) if not getattr(args, "skip_maven", False) else 0,
    )
    trace_failures = getattr(args, "_trace_failures", [])
    if trace_failures:
        result["execution_trace"] = {
            "ready": False,
            "blocked_reasons": trace_failures,
            "warnings": [],
        }
        exit_code = max(exit_code, 2)
    if getattr(args, "strict_workflow", False):
        approval_path = legacy.resolve_repo_path(legacy.as_repo(args.repo), getattr(args, "workflow_approval", None))
        guard_result = legacy.workflow_guard.validate_verify_result(
            result,
            strict=True,
            require_completion=args.phase == "completion",
            approval_text=legacy.optional_text(approval_path),
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
            repo = legacy.as_repo(args.repo)
            harness_result = legacy.harness_verify.validate(
                repo,
                state_path,
                getattr(args, "policy", None),
                getattr(args, "strict_artifacts", False),
                getattr(args, "run_completion_gate", False),
            )
            summary = legacy.harness_verify.write_summary_outputs(
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
    legacy.trace_event(
        args,
        "verify",
        "finish",
        "ready" if exit_code == 0 else "blocked",
        int((legacy.time.perf_counter() - total_started) * 1000),
        [str(args.status_file)] if getattr(args, "status_file", None) else None,
    )
    final_trace_failures = getattr(args, "_trace_failures", [])
    if final_trace_failures:
        result["execution_trace"] = {
            "ready": False,
            "blocked_reasons": final_trace_failures,
            "warnings": [],
        }
        exit_code = max(exit_code, 2)
    legacy.write_status(getattr(args, "status_file", None), result)
    return exit_code, result
