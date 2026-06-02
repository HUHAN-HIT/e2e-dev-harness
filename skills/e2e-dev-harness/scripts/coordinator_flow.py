#!/usr/bin/env python3
"""Coordinator-only orchestration helpers for e2e-dev-harness."""

from __future__ import annotations

import json
from pathlib import Path

import dispatcher
import install_hooks
import run_state
import session_checkpoint
from output_contract import workflow_stage_for_lifecycle


BLUEPRINT_STEPS = (
    ("CREATED", "clarify", "Dispatch requirements-clarifier; relay Restated Intent/Open Questions and record evidence paths."),
    ("CLARIFIED", "r1-design-review", "Generate the archive only if missing, then dispatch the independent R1 design review."),
    ("SERVICE_DESIGN_REQUIRED", "service-design", "Dispatch service-design workers and validate returned service-design slices."),
    ("PLANNED", "plan-tdd-red-r2", "Dispatch implementation-planner, TDD red, and R2 review workers before implementation gate."),
    ("RED_READY", "implementation-gate", "Run gate --phase implementation to open production-code writes."),
    ("IMPLEMENTED", "implement-or-complete", "Dispatch code-developer work until ac-progress is ready, then dispatch independent R3 review."),
    ("REVIEWED", "completion", "Run the completion gate, strict guard, run summary, and requirements archive."),
    ("VERIFIED", "archive", "Refresh the registry, archive requirements, and report evidence."),
)


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


def load_run_state(repo: Path, state_path: Path) -> dict:
    path = state_path if state_path.is_absolute() else repo / state_path
    return json.loads(path.read_text(encoding="utf-8"))


def dispatch_context_budget_gate(repo: Path, state_path: Path) -> dict:
    state_file = require_repo_path(repo, state_path, "run state")
    if not state_file.exists():
        return {
            "ready": False,
            "blocked_reasons": [f"Run state not found: {state_file}"],
            "warnings": [],
            "coordinator_context_budget": {},
            "session_checkpoint": {},
        }
    state = load_run_state(repo, state_file)
    budget = session_checkpoint.context_budget(state_file, state)
    checkpoint = session_checkpoint.validate(repo, state_file)
    blocked: list[str] = []
    if budget.get("handoff_recommended") and not checkpoint["ready"]:
        blocked.append(
            "Session checkpoint required: coordinator context budget is exceeded; run e2e_dev_harness.py next "
            "to create a fresh checkpoint before dispatching more workers."
        )
        blocked.extend("Session checkpoint: " + reason for reason in checkpoint["blocked_reasons"])
    return {
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": session_checkpoint.budget_warnings(budget),
        "coordinator_context_budget": budget,
        "session_checkpoint": checkpoint,
    }


def load_workflow_plan(repo: Path, state: dict) -> dict | None:
    value = str(state.get("workflow_plan", "")).strip()
    if not value:
        return None
    path = resolve_repo_path(repo, Path(value))
    if not path or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def runtime_hook_status(repo: Path) -> dict:
    checked: list[dict] = []
    project_claude_dir = repo / ".claude"
    project_opencode_dir = repo / ".opencode"
    claude_targets = [
        ("project", project_claude_dir / "settings.json"),
        ("user", Path.home() / ".claude" / "settings.json"),
    ]
    if project_claude_dir.exists():
        for scope, target in claude_targets:
            if not target.parent.exists():
                continue
            result = install_hooks.validate_config(target, repo)
            result["runtime"] = "claude"
            result["scope"] = scope
            checked.append(result)
            if result["ready"]:
                if scope == "user" and checked and checked[0].get("scope") == "project" and not checked[0]["ready"]:
                    result["warnings"] = result.get("warnings", []) + [
                        "Project Claude hook config is not ready; user-level Claude hook config is enforcing phase_guard.py."
                    ]
                    result["project_hook_status"] = checked[0]
                return result
    if project_opencode_dir.exists():
        opencode_target = project_opencode_dir / "plugins" / "e2e-dev-harness.js"
        result = install_hooks.validate_config(opencode_target, repo)
        result["runtime"] = "opencode"
        result["scope"] = "project"
        checked.append(result)
        if result["ready"]:
            return result
    if checked:
        return {
            "ready": False,
            "blocked_reasons": [
                f"{item['scope']} {item.get('runtime', 'runtime')} hook: {reason}"
                for item in checked
                for reason in item.get("blocked_reasons", [])
            ],
            "warnings": [],
            "runtime": ",".join(sorted({str(item.get("runtime", "runtime")) for item in checked})),
            "target": ", ".join(str(item.get("target", "")) for item in checked),
            "checked": checked,
        }
    if not project_claude_dir.exists() and not project_opencode_dir.exists():
        return {
            "ready": True,
            "blocked_reasons": [],
            "warnings": [
                "No runtime hook directory detected; use e2e_dev_harness.py pre-code before code edits when hooks are unavailable."
            ],
            "runtime": "generic",
            "target": "",
        }
    return {
        "ready": False,
        "blocked_reasons": [
            "Runtime hook config not found or unreadable."
        ],
        "warnings": [],
        "runtime": "runtime",
        "target": "",
    }


def clarification_interaction_contract() -> dict:
    return {
        "schema": "e2e-dev-harness.clarification-interaction.v1",
        "interaction_required": True,
        "must_wait_for_user_answer": True,
        "questions_to_ask_user": [
            "Relay the requirements-clarifier worker's Restated Intent confirmation request to the user.",
            "Relay only unresolved behavior, API, data, ownership, test, or impact questions returned by the worker.",
            "Record the worker's returned evidence paths after answers are captured.",
        ],
        "allowed_before_user_answer": [
            "dispatching the requirements-clarifier worker",
            "recording dispatcher-generated context pack, invocation, and worker handle paths",
        ],
        "blocked_until_resolved": [
            "planning",
            "TDD",
            "production-code edits",
            "review dispatch that depends on clarified behavior",
        ],
    }


def required_todo_list_for_lifecycle(lifecycle: str, state: dict | None = None) -> list[str]:
    state = state or {}
    state_path = "docs/agent-runs/<run>/run-state.json"
    schedule_path = "docs/agent-runs/<run>/agent-schedule.json"
    lists = {
        "CREATED": [
            f"Run e2e_dev_harness.py dispatch-next --schedule {schedule_path} --state {state_path} to dispatch requirements-clarifier.",
            "Spawn or acknowledge only the dispatcher-generated requirements-clarifier worker.",
            "Do not perform clarification, GitNexus, rg/Read, design-doc, plan, TDD, or review work in coordinator chat.",
            "Relay unresolved Restated Intent or Open Questions from the worker to the user.",
            "Record returned requirements handoff evidence paths, then run dispatch-complete and next.",
        ],
        "CLARIFIED": [
            "Run plan --create-archive only as a control-plane schedule/archive generation step when the full schedule is missing.",
            "Run dispatch-beat/dispatch-next to spawn the independent R1 design-review worker.",
            "Record dispatch-ack and dispatch-complete for R1 evidence, then run next.",
            "Do not perform design, impact analysis, R1 review, TDD, or implementation work in coordinator chat.",
        ],
        "SERVICE_DESIGN_REQUIRED": [
            "Run dispatch-beat/dispatch-next to spawn service-design workers for each required slice.",
            f"Run e2e_dev_harness.py service-design --run-state {state_path} after worker evidence is returned.",
            "Record dispatch-complete for service-design evidence, then run next.",
            "Do not write service-design slices or dependency/runtime-path analysis in coordinator chat.",
        ],
        "PLANNED": [
            "Run dispatch-beat/dispatch-next for the next scheduled worker in order: unfinished R1, implementation-planner, TDD red, then R2.",
            "Record dispatch-ack and dispatch-complete with returned plan/red-test/R2 evidence paths.",
            "Run next after each dispatch wave; run-state should advance to RED_READY only after plan, TDD red, and R2 evidence.",
            "Do not write plans, tests, reviews, or implementation code in coordinator chat.",
        ],
        "RED_READY": [
            f"Run e2e_dev_harness.py gate --phase implementation --run-state {state_path}.",
            "Do not edit production files until the implementation gate opens.",
        ],
        "IMPLEMENTED": [
            "Run dispatch-beat/dispatch-next to spawn code-developer workers for assigned service/module scope.",
            "Record dispatch-complete with green-test, implementation-manifest, and coverage evidence paths.",
            "Run ac-progress after worker evidence; dispatch R3 and coverage only after all assigned ACs pass.",
            "Do not write production/test code, R3 review, or coverage artifacts in coordinator chat.",
        ],
        "REVIEWED": [
            "Run the completion gate and strict guard.",
            "Write run summary and requirements archive evidence.",
            "Resolve any rework before reporting completion.",
        ],
        "VERIFIED": [
            "Refresh artifact registry and requirements archive.",
            "Report final evidence paths and residual risks.",
        ],
        "REWORK_REQUIRED": [
            "Read the rework item return_phase.",
            "Return to the earliest required phase before editing files.",
            "Close rework with evidence before continuing.",
        ],
    }
    return lists.get(
        lifecycle,
        [
            "Inspect run-state.json and repair the lifecycle.",
            f"Run e2e_dev_harness.py next --state {state_path} after repair.",
        ],
    )


def exploration_policy_for_lifecycle(lifecycle: str) -> dict:
    if lifecycle == "CREATED":
        return {
            "schema": "e2e-dev-harness.exploration-policy.v1",
            "preferred": "dispatcher",
            "direct_tools_allowed_for": [],
            "required_for": ["requirements clarification", "Restated Intent", "impact evidence", "design doc updates"],
            "fallback": "Run dispatch-next for the requirements-clarifier worker; coordinator may only relay returned questions and evidence paths.",
            "lifecycle": lifecycle,
        }
    return {
        "schema": "e2e-dev-harness.exploration-policy.v1",
        "preferred": "gitnexus",
        "direct_tools_allowed_for": ["seed discovery", "small quoted evidence after GitNexus points to a file"],
        "required_for": ["impact analysis", "call path tracing", "cross-service dependencies", "route/topic/contract ownership"],
        "fallback": "If GitNexus is unavailable, write degradation evidence before treating rg/Read findings as workflow evidence.",
        "lifecycle": lifecycle or "<missing>",
    }


def todo_policy_for_lifecycle(lifecycle: str, state: dict | None = None) -> dict:
    return {
        "schema": "e2e-dev-harness.todo-policy.v1",
        "mode": "phase-scoped",
        "lifecycle": lifecycle or "<missing>",
        "rule": "TodoList must describe only the current lifecycle phase; do not include future implementation/code tasks before the implementation gate.",
        "required_todo_list": required_todo_list_for_lifecycle(lifecycle, state),
        "exploration_policy": exploration_policy_for_lifecycle(lifecycle),
    }


def run_dir_for_state(state: dict | None = None) -> str:
    state = state or {}
    run_id = str(state.get("run_id") or "").strip().replace("\\", "/").strip("/")
    if not run_id:
        return "docs/agent-runs/<run>"
    if run_id.startswith("docs/agent-runs/"):
        return run_id
    return f"docs/agent-runs/{run_id}"


def coordinator_action_fields(lifecycle: str, state: dict | None = None, runtime: str = "claude-code") -> dict:
    state = state or {}
    dispatch_runtime = dispatcher.normalize_runtime(runtime)
    run_dir = run_dir_for_state(state)
    schedule = f"{run_dir}/agent-schedule.json"
    state_path = f"{run_dir}/run-state.json"
    base = {
        "coordinator_mode": "coordinator-only",
        "dispatch_runtime": dispatch_runtime,
        "dispatch_command": "",
        "forbidden_local_actions": [
            "do dispatched worker work locally in the coordinator chat",
            "paste full worker context into the coordinator chat",
            "mark scheduled tasks complete without dispatcher confirmation",
        ],
    }
    by_lifecycle = {
        "CREATED": {
            "orchestration_action": "dispatch_worker",
            "dispatch_command": (
                "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-next . "
                f"--schedule {schedule} --state {state_path} --runtime {dispatch_runtime}"
            ),
            "expected_worker": "requirements-clarifier",
            "forbidden_local_actions": base["forbidden_local_actions"] + [
                "perform clarification work locally instead of dispatching requirements-clarifier",
                "start planning, TDD, or review before clarification worker evidence is complete",
            ],
        },
        "CLARIFIED": {
            "orchestration_action": "dispatch_worker",
            "dispatch_command": (
                "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-beat . "
                f"--schedule {schedule} --state {state_path} --runtime {dispatch_runtime} --max-workers 2"
            ),
            "forbidden_local_actions": base["forbidden_local_actions"] + [
                "perform design or R1 review locally instead of dispatching scheduled workers",
            ],
        },
        "SERVICE_DESIGN_REQUIRED": {
            "orchestration_action": "dispatch_worker",
            "dispatch_command": (
                "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-beat . "
                f"--schedule {schedule} --state {state_path} --runtime {dispatch_runtime} --max-workers 2"
            ),
            "forbidden_local_actions": base["forbidden_local_actions"] + [
                "write service design slices locally unless acting as the dispatched worker",
            ],
        },
        "PLANNED": {
            "orchestration_action": "dispatch_worker",
            "dispatch_command": (
                "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-beat . "
                f"--schedule {schedule} --state {state_path} --runtime {dispatch_runtime} --max-workers 2"
            ),
            "forbidden_local_actions": base["forbidden_local_actions"] + [
                "write the red test locally in coordinator context",
                "perform R2 review locally in coordinator context",
                "dispatch code-developer before RED_READY and implementation gate",
            ],
        },
        "RED_READY": {
            "orchestration_action": "run_gate",
            "dispatch_command": (
                "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py gate . "
                f"--phase implementation --run-state {state_path}"
            ),
            "forbidden_local_actions": base["forbidden_local_actions"] + [
                "dispatch any implementation worker before the implementation gate passes",
                "write production code before lifecycle IMPLEMENTED",
            ],
        },
        "IMPLEMENTED": {
            "orchestration_action": "dispatch_worker",
            "dispatch_command": (
                "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-beat . "
                f"--schedule {schedule} --state {state_path} --runtime {dispatch_runtime} --max-workers 4"
            ),
            "forbidden_local_actions": base["forbidden_local_actions"] + [
                "perform code-developer, R3, or coverage work locally in coordinator context",
            ],
        },
        "REVIEWED": {
            "orchestration_action": "run_gate",
            "dispatch_command": (
                "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py gate . "
                f"--phase completion --run-state {state_path}"
            ),
            "forbidden_local_actions": base["forbidden_local_actions"] + [
                "claim completion before scheduled workers and reviews are closed",
            ],
        },
        "VERIFIED": {
            "orchestration_action": "complete",
            "dispatch_command": "",
            "forbidden_local_actions": base["forbidden_local_actions"],
        },
        "WAITING_DISPATCH": {
            "orchestration_action": "wait_for_worker",
            "dispatch_command": (
                "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-ack . "
                f"--state {state_path} --task-id <task-id> --agent <agent> "
                "--worker-handle <runtime-worker-id>"
            ),
            "forbidden_local_actions": base["forbidden_local_actions"] + [
                "complete the task before a fresh worker is acknowledged",
            ],
        },
    }
    selected = by_lifecycle.get(lifecycle, {"orchestration_action": "ask_user"})
    return {**base, **selected}


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


ACTIVE_DISPATCH_STATUSES = {
    "awaiting_runtime_spawn",
    "waiting_dispatch",
    "worker_dispatched",
    "dispatched",
    "worker_running",
}


def has_active_dispatch(state: dict) -> bool:
    dispatch = state.get("dispatch") if isinstance(state.get("dispatch"), dict) else {}
    dispatches = state.get("dispatches") if isinstance(state.get("dispatches"), dict) else {}
    if str(dispatch.get("status", "")).lower() in ACTIVE_DISPATCH_STATUSES:
        return True
    return any(
        str(item.get("status", "")).lower() in ACTIVE_DISPATCH_STATUSES
        for item in dispatches.values()
        if isinstance(item, dict)
    )


def execution_packet_for_lifecycle(
    lifecycle: str,
    state: dict | None = None,
    runtime: str = "claude-code",
    action: dict | None = None,
) -> dict:
    state = state or {}
    action = action or next_action_for_lifecycle(lifecycle, state, runtime)
    run_dir = run_dir_for_state(state)
    primary_command = str(action.get("dispatch_command") or action.get("command") or "")
    base_evidence_paths = {
        "run_state": f"{run_dir}/run-state.json",
        "agent_schedule": f"{run_dir}/agent-schedule.json",
        "phase_lock": f"{run_dir}/.phase-lock",
        "red_test_evidence": f"{run_dir}/evidence/red-test.txt",
        "green_test_evidence": f"{run_dir}/evidence/green-test.json",
        "coverage_matrix": f"{run_dir}/evidence/coverage-matrix.md",
        "implementation_manifest": f"{run_dir}/evidence/implementation-manifest.md",
        "requirements_archive": f"{run_dir}/requirements-archive.md",
        "strict_guard": f"{run_dir}/evidence/strict-guard.json",
    }
    by_lifecycle = {
        "CREATED": {
            "objective": "Clarify intent and scope through the bootstrap requirements worker before planning.",
            "required_actions": [
                "Dispatch the requirements-clarifier worker or record manual isolated dispatch.",
                "Relay only unresolved user questions back to the coordinator chat.",
                "Run the clarification gate after the design doc is updated.",
            ],
            "required_evidence": [
                "confirmed Restated Intent and closed Open Questions in the design doc",
                "clarification gate result",
                "requirements handoff or manual dispatch evidence",
            ],
            "completion_checks": [
                "run-state lifecycle becomes CLARIFIED",
                "no planning, TDD, or code work starts before clarification passes",
            ],
            "next_gate": "clarification",
        },
        "CLARIFIED": {
            "objective": "Get independent R1 design review evidence ready before implementation planning.",
            "required_actions": [
                "Run plan --create-archive only as control-plane schedule/archive generation when missing.",
                "Dispatch the independent R1 design-review worker.",
                "Refresh next before TDD work starts.",
            ],
            "required_evidence": [
                "agent-run archive with artifact registry and schedule",
                "GitNexus or approved dependency/impact evidence",
                "R1 design review report and invocation proof",
            ],
            "completion_checks": [
                "run-state lifecycle becomes PLANNED or SERVICE_DESIGN_REQUIRED",
                "R1 review blockers are routed to rework before TDD",
            ],
            "next_gate": "planning",
        },
        "SERVICE_DESIGN_REQUIRED": {
            "objective": "Complete service-local design slices before TDD or code dispatch.",
            "required_actions": [
                "Dispatch service-design workers for every service-designs/<service>.md slice.",
                "Validate returned slices with the service-design gate.",
                "Refresh next after the service-design gate passes.",
            ],
            "required_evidence": [
                "mapped AC rows for every affected service",
                "service-local runtime path and dependency boundary",
                "service-design gate result",
            ],
            "completion_checks": [
                "run-state lifecycle becomes PLANNED",
                "no service code-agent dispatch happens before service-design passes",
            ],
            "next_gate": "service_design",
        },
        "PLANNED": {
            "objective": "Dispatch implementation-planner, TDD red, and independent R2 review before implementation opens.",
            "required_actions": [
                "Run dispatch-beat for the next ready scheduled workers: unfinished R1, implementation-planner, TDD red, then R2.",
                "Record returned plan/red-test/R2 evidence paths through dispatch-complete.",
                "Run next again after dispatch-complete updates the run-state.",
            ],
            "required_evidence": [
                "red-test evidence for the first failing behavior",
                "R2 test review report and invocation proof",
                "dispatch-complete evidence for scheduled TDD/R2 tasks",
            ],
            "completion_checks": [
                "run-state lifecycle becomes RED_READY",
                "no code-developer worker is dispatched before the implementation gate",
            ],
            "next_gate": "tdd_red",
        },
        "RED_READY": {
            "objective": "Open implementation only through the implementation gate.",
            "required_actions": [
                "Run the implementation gate with run-state and red/R2 evidence.",
                "Refresh next after the gate updates run-state and phase lock.",
            ],
            "required_evidence": [
                "red-test evidence",
                "R2 test review evidence",
                "passing implementation gate status evidence",
            ],
            "completion_checks": [
                "run-state lifecycle becomes IMPLEMENTED",
                "phase lock reports code-write-open only after the gate passes",
            ],
            "next_gate": "implementation",
        },
        "IMPLEMENTED": {
            "objective": "Finish all assigned ACs through dispatched implementation, AC progress, and R3 review.",
            "required_actions": [
                "Dispatch each code-developer task for its service/module.",
                "Record returned green-test, manifest, and coverage evidence paths.",
                "Run ac-progress before R3, then dispatch or complete R3.",
            ],
            "required_evidence": [
                "green unit-test command evidence",
                "implementation manifest rows with concrete code refs",
                "coverage matrix and business review",
                "R3 implementation review report and invocation proof",
            ],
            "completion_checks": [
                "all assigned ACs pass ac-progress",
                "run-state lifecycle becomes REVIEWED or VERIFIED after required reviews/gates",
            ],
            "next_gate": "ac_progress",
        },
        "REVIEWED": {
            "objective": "Prove completion with completion gate, strict guard, and requirements archive.",
            "required_actions": [
                "Run the completion gate with coverage, manifest, tests, reviews, and archive evidence.",
                "Run strict guard and write run summaries.",
                "Resolve or explicitly approve any rework before reporting completion.",
            ],
            "required_evidence": [
                "completion gate result",
                "strict guard result",
                "requirements archive",
                "run summary JSON and Markdown",
            ],
            "completion_checks": [
                "run-state lifecycle becomes VERIFIED",
                "no open rework remains without approved deferral",
            ],
            "next_gate": "completion",
        },
        "WAITING_DISPATCH": {
            "objective": "Preserve agent isolation while waiting for runtime worker acknowledgement.",
            "required_actions": [
                "Record the runtime worker handle with dispatch-ack.",
                "Keep coordinator chat limited to task id, agent id, worker handle, context-pack path, and evidence paths.",
                "Run dispatch-status or next after acknowledgement to resume the lifecycle.",
            ],
            "required_evidence": [
                "worker acknowledgement with runtime worker handle",
                "dispatch invocation JSON or manual dispatch packet",
                "context pack path for the dispatched task",
            ],
            "completion_checks": [
                "dispatch status becomes worker_running",
                "the scheduled task is not completed before worker evidence exists",
            ],
            "next_gate": "dispatch_ack",
        },
        "REWORK_REQUIRED": {
            "objective": "Route findings back to the earliest required phase before more implementation changes.",
            "required_actions": [
                "Read each rework item return_phase and affected scope.",
                "Return to the routed phase before editing files.",
                "Close rework only as Status: verified or approved deferred with evidence.",
            ],
            "required_evidence": [
                "rework item with return_phase, affected services, and exit criteria",
                "verification evidence proving the rework item is closed",
                "updated gate/review evidence for the routed phase",
            ],
            "completion_checks": [
                "all blocking rework items are verified or explicitly approved deferred",
                "new changes stay inside the routed rework scope",
            ],
            "next_gate": "rework",
        },
        "VERIFIED": {
            "objective": "Archive final evidence and report residual risks.",
            "required_actions": [
                "Refresh artifact registry.",
                "Report final evidence paths and residual risks.",
            ],
            "required_evidence": [
                "fresh artifact registry",
                "requirements archive",
                "final evidence report",
            ],
            "completion_checks": [
                "no new implementation changes are introduced after verification",
            ],
            "next_gate": "archive",
        },
    }
    detail_lifecycle = "WAITING_DISPATCH" if action.get("phase") == "waiting-dispatch" else lifecycle
    details = by_lifecycle.get(
        detail_lifecycle,
        {
            "objective": "Repair or inspect the run-state lifecycle before continuing.",
            "required_actions": ["Run next after repairing run-state."],
            "required_evidence": ["valid run-state and phase lock"],
            "completion_checks": ["lifecycle is recognized by the harness"],
            "next_gate": "unknown",
        },
    )
    forbidden = _unique_strings(
        list(action.get("forbidden_local_actions", []))
        + [f"write {item}" for item in action.get("blocked_writes", [])]
    )
    return {
        "schema": "e2e-dev-harness.execution-packet.v1",
        "lifecycle": lifecycle or "<missing>",
        "phase": action.get("phase", ""),
        "objective": details["objective"],
        "primary_command": primary_command,
        "required_actions": details["required_actions"],
        "required_evidence": details["required_evidence"],
        "evidence_paths": base_evidence_paths,
        "forbidden_actions": forbidden,
        "completion_checks": details["completion_checks"],
        "next_gate": details["next_gate"],
    }


def next_action_for_lifecycle(lifecycle: str, state: dict | None = None, runtime: str = "claude-code") -> dict:
    state = state or {}
    action_lifecycle = "WAITING_DISPATCH" if lifecycle != "WAITING_DISPATCH" and has_active_dispatch(state) else lifecycle
    actions = {
        "CREATED": {
            "phase": "clarify",
            "command": "Dispatch the bootstrap requirements-clarifier worker; coordinator only relays unresolved user questions and records returned evidence.",
            "allowed_writes": ["docs/design/", "docs/agent-runs/"],
            "blocked_writes": ["production code", "tests outside harness evidence"],
        },
        "CLARIFIED": {
            "phase": "r1-design-review",
            "command": "Generate the full schedule/archive only if missing, then dispatch independent R1 design-review workers.",
            "allowed_writes": ["docs/agent-runs/", "docs/design/"],
            "blocked_writes": ["production code", "R1/design/impact work in coordinator chat"],
        },
        "SERVICE_DESIGN_REQUIRED": {
            "phase": "service-design",
            "command": "Dispatch service-design workers, then validate returned slices with e2e_dev_harness.py service-design --run-state <state>.",
            "allowed_writes": ["docs/agent-runs/", "docs/design/"],
            "blocked_writes": ["production code", "service design slice work in coordinator chat", "service code-agent dispatch before service-design gate passes"],
        },
        "PLANNED": {
            "phase": "tdd-red",
            "command": "Dispatch TDD red and R2 review workers, then run the implementation gate after dispatch-complete transitions to RED_READY.",
            "allowed_writes": ["test files for red evidence", "docs/agent-runs/"],
            "blocked_writes": ["production code until implementation gate passes"],
        },
        "RED_READY": {
            "phase": "implementation-gate",
            "command": "Run gate --phase implementation with red evidence and run-state to open implementation.",
            "allowed_writes": ["docs/agent-runs/"],
            "blocked_writes": ["production code until implementation gate passes"],
        },
        "IMPLEMENTED": {
            "phase": "implement-or-complete",
            "command": "Dispatch code-developer workers for TDD green, run ac-progress on returned evidence, then dispatch R3 review and completion gate.",
            "allowed_writes": ["declared production/test scope", "docs/agent-runs/"],
            "blocked_writes": ["coordinator-local production/test code edits", "undeclared scope drift", "R3 review before all assigned ACs pass ac-progress"],
        },
        "REVIEWED": {
            "phase": "completion",
            "command": "Run completion gate, strict guard, summary, and requirements archive validation.",
            "allowed_writes": ["docs/agent-runs/"],
            "blocked_writes": ["new production changes without rework item"],
        },
        "WAITING_DISPATCH": {
            "phase": "waiting-dispatch",
            "command": "A worker dispatch is pending acknowledgement; record the worker handle with dispatch-ack before completion.",
            "allowed_writes": ["docs/agent-runs/dispatches/", "docs/agent-runs/context-packs/"],
            "blocked_writes": ["task completion before worker acknowledgement", "local coordinator work for the dispatched task"],
        },
        "REWORK_REQUIRED": {
            "phase": "rework",
            "command": "Follow rework item return_phase; do not patch directly outside the routed phase.",
            "allowed_writes": ["rework-routed scope only"],
            "blocked_writes": ["unrouted production changes"],
        },
        "VERIFIED": {
            "phase": "archive",
            "command": "Refresh registry, archive requirements, and report evidence.",
            "allowed_writes": ["docs/agent-runs/", "memory updates with approval"],
            "blocked_writes": ["new implementation changes"],
        },
    }
    action = actions.get(
        action_lifecycle,
        {
            "phase": "unknown",
            "command": "Inspect run-state.json and repair lifecycle before continuing.",
            "allowed_writes": ["docs/agent-runs/"],
            "blocked_writes": ["production code"],
        },
    )
    if action_lifecycle == "PLANNED" and state.get("selected_mode") == "multi":
        action = dict(action)
        action["command"] = (
            "Run dispatch-beat --max-workers <N> to spawn service-local TDD red workers, then dispatch/complete R2 review. After run-state reaches RED_READY, "
            "run gate --phase implementation; dispatch code-developer workers only after IMPLEMENTED."
        )
        action["blocked_writes"] = [
            "production code until implementation gate passes",
            "code-developer claim/dispatch before RED_READY and implementation gate",
        ]
    action = dict(action)
    action["workflow_stage"] = workflow_stage_for_lifecycle(lifecycle)
    action["required_todo_list"] = required_todo_list_for_lifecycle(action_lifecycle, state)
    action["todo_policy"] = todo_policy_for_lifecycle(action_lifecycle, state)
    action["exploration_policy"] = exploration_policy_for_lifecycle(action_lifecycle)
    action.update(coordinator_action_fields(action_lifecycle, state, runtime))
    if lifecycle == "CREATED":
        action["clarification_interaction"] = clarification_interaction_contract()
    return action


def workflow_overview_for(lifecycle: str, state: dict | None = None) -> dict:
    state = state or {}
    order = [item[0] for item in BLUEPRINT_STEPS]
    current_index = order.index(lifecycle) if lifecycle in order else -1
    steps: list[dict] = []
    for index, (step_lifecycle, phase, summary) in enumerate(BLUEPRINT_STEPS):
        steps.append(
            {
                "lifecycle": step_lifecycle,
                "phase": phase,
                "gate_summary": summary,
                "current": step_lifecycle == lifecycle,
                "completed": current_index >= 0 and index < current_index,
                "pending": current_index == -1 or index > current_index,
                "gate_status": (state.get("gates", {}) or {}).get(phase, ""),
            }
        )
    return {
        "schema": "e2e-dev-harness.workflow-overview.v1",
        "current_lifecycle": lifecycle,
        "selected_mode": state.get("selected_mode", ""),
        "steps": steps,
    }


def _dispatch_with_hook_guard(args, beat: bool) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    budget_gate = dispatch_context_budget_gate(repo, args.state)
    if not budget_gate["ready"]:
        hooks = runtime_hook_status(repo)
        result = {
            "repo": str(repo),
            "ready": False,
            "blocked_reasons": budget_gate["blocked_reasons"],
            "warnings": budget_gate["warnings"],
            "hook_status": hooks,
            "coordinator_context_budget": budget_gate["coordinator_context_budget"],
            "session_checkpoint": budget_gate["session_checkpoint"],
            "next_required": {
                "command": f"python skills/e2e-dev-harness/scripts/e2e_dev_harness.py next . --state {args.state}",
                "reason": "refresh session checkpoint before dispatch",
            },
        }
        write_status(args.status_file, result)
        return 2, result
    hooks = runtime_hook_status(repo)
    runtime = args.runtime
    forced_waiting = hooks.get("runtime") == "generic" or not hooks.get("ready", False)
    if forced_waiting:
        runtime = "manual"
    if beat:
        result = dispatcher.dispatch_beat(
            repo,
            args.schedule,
            args.state,
            runtime=runtime,
            coordinator_agent=args.coordinator_agent,
            developer_session=args.developer_session,
            max_workers=args.max_workers,
            max_files=args.max_files,
            max_chars=args.max_chars,
        )
    else:
        result = dispatcher.dispatch_next(
            repo,
            args.schedule,
            args.state,
            runtime=runtime,
            coordinator_agent=args.coordinator_agent,
            developer_session=args.developer_session,
            max_files=args.max_files,
            max_chars=args.max_chars,
        )
    result["coordinator_context_budget"] = budget_gate["coordinator_context_budget"]
    result["session_checkpoint"] = budget_gate["session_checkpoint"]
    result["hook_status"] = hooks
    if forced_waiting:
        result.setdefault("warnings", []).append(
            "Runtime hook is missing or not enforceable; dispatch is held in waiting_dispatch until an isolated worker is acknowledged."
        )
        summary = session_checkpoint.create_coordinator_summary(repo, args.state, result)
        result["coordinator_summary_path"] = summary.get("coordinator_summary", "")
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result


def dispatch_next(args) -> tuple[int, dict]:
    return _dispatch_with_hook_guard(args, beat=False)


def dispatch_beat(args) -> tuple[int, dict]:
    return _dispatch_with_hook_guard(args, beat=True)


def next_step(args) -> tuple[int, dict]:
    repo = as_repo(args.repo)
    state_path = require_repo_path(repo, args.state, "run state")
    if not state_path.exists():
        result = {
            "repo": str(repo),
            "ready": False,
            "blocked_reasons": [f"Run state not found: {state_path}. Run e2e_dev_harness.py start first."],
            "warnings": [],
        }
        write_status(args.status_file, result)
        return 2, result
    state = load_run_state(repo, state_path)
    lifecycle = str(state.get("lifecycle", ""))
    runtime = getattr(args, "runtime", "claude-code")
    action = next_action_for_lifecycle(lifecycle, state, runtime)
    execution_packet = execution_packet_for_lifecycle(lifecycle, state, runtime, action)
    workflow_plan = load_workflow_plan(repo, state)
    hooks = runtime_hook_status(repo)
    blocked = [] if hooks["ready"] else [
        "Runtime hook is not ready; install hooks or use e2e_dev_harness.py pre-code before any code edit."
    ]
    result = {
        "repo": str(repo),
        "ready": not blocked,
        "run_state": str(state_path),
        "phase_lock": str(state_path.parent / run_state.PHASE_LOCK),
        "hook_status": hooks,
        "lifecycle": lifecycle,
        "workflow_stage": action.get("workflow_stage", workflow_stage_for_lifecycle(lifecycle)),
        "next": action,
        "execution_packet": execution_packet,
        "todo_policy": action["todo_policy"],
        "required_todo_list": action["required_todo_list"],
        "exploration_policy": action["exploration_policy"],
        "workflow_overview": workflow_overview_for(lifecycle, state),
        "workflow_plan": workflow_plan,
        "phase_mode": state.get("phase_mode", ""),
        "workflow_profile": state.get("workflow_profile", ""),
        "gates": state.get("gates", {}),
        "blocked_reasons": blocked,
        "warnings": hooks.get("warnings", []) if hooks["ready"] else [],
    }
    checkpoint = session_checkpoint.create(repo, state_path, action)
    result["session_checkpoint"] = checkpoint
    result["coordinator_context_budget"] = checkpoint.get("context_budget", {})
    for warning in checkpoint.get("warnings", []):
        if warning not in result["warnings"]:
            result["warnings"].append(warning)
    if not checkpoint["ready"]:
        result["ready"] = False
        result["blocked_reasons"].extend("Session checkpoint: " + reason for reason in checkpoint["blocked_reasons"])
    summary = session_checkpoint.create_coordinator_summary(repo, state_path, result)
    result["coordinator_summary_path"] = summary.get("coordinator_summary", "")
    result["coordinator_summary"] = summary
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result
