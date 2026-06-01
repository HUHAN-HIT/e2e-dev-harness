#!/usr/bin/env python3
"""Coordinator-only orchestration helpers for e2e-dev-harness."""

from __future__ import annotations

import json
from pathlib import Path

import dispatcher
import install_hooks
import run_state
import session_checkpoint


BLUEPRINT_STEPS = (
    ("CREATED", "clarify", "Fill the design doc; clarification gate needs goals, use cases, acceptance criteria, test design, and resolved open questions."),
    ("CLARIFIED", "plan", "Run plan --create-archive and complete the independent R1 design review."),
    ("SERVICE_DESIGN_REQUIRED", "service-design", "Fill and validate each service-designs/<service>.md (service-design gate); use --emit-template to start."),
    ("PLANNED", "tdd-red", "Dispatch TDD red and R2 review workers; dispatch-complete records evidence before implementation gate."),
    ("RED_READY", "implementation-gate", "Run gate --phase implementation to open production-code writes."),
    ("IMPLEMENTED", "implement-or-complete", "TDD red/green for every assigned AC until ac-progress is ready, then the independent R3 implementation review."),
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
            "Confirm the agent's Restated Intent with the user.",
            "Ask any behavior, API, data, ownership, test, or impact questions that cannot be answered from evidence.",
            "Update the design doc Open Questions section to None only after answers are recorded or explicitly deferred out of scope.",
        ],
        "allowed_before_user_answer": [
            "bounded GitNexus or scanner discovery for evidence",
            "drafting design sections clearly marked pending confirmation",
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
    lists = {
        "CREATED": [
            "Ask the user to confirm Restated Intent and answer unresolved clarification questions.",
            "Run kg_refresh or inspect GitNexus status before repository exploration.",
            "Use GitNexus query/context/impact for bounded impact evidence; use rg/Read only for seed discovery.",
            "Fill docs/design/<feature>.md with clarified requirements and bounded impact facts.",
            f"Run e2e_dev_harness.py clarify --design-doc <design> --run-state {state_path}.",
            "Revise the design doc until the clarification gate passes.",
        ],
        "CLARIFIED": [
            "Use GitNexus evidence to confirm affected services, routes, topics, and dependency impact.",
            "Run e2e_dev_harness.py plan --design-doc <design> --create-archive.",
            "Dispatch or complete the independent R1 design review.",
            "Run e2e_dev_harness.py next before TDD or implementation work.",
        ],
        "SERVICE_DESIGN_REQUIRED": [
            "Use GitNexus context/impact for each service runtime path and dependency boundary.",
            "Fill every service-designs/<service>.md slice with mapped ACs and runtime path.",
            f"Run e2e_dev_harness.py service-design --run-state {state_path}.",
            "Revise service design slices until the service-design gate passes.",
        ],
        "PLANNED": [
            "Run e2e_dev_harness.py dispatch-beat --max-workers <N> to spawn service-local TDD red workers.",
            "Capture red-test evidence and required command output for each affected service.",
            "Dispatch or complete the independent R2 test review.",
            "Run e2e_dev_harness.py next again after TDD red and R2 complete; run-state should advance to RED_READY.",
        ],
        "RED_READY": [
            f"Run e2e_dev_harness.py gate --phase implementation --run-state {state_path}.",
            "Do not edit production files until the implementation gate opens.",
        ],
        "IMPLEMENTED": [
            "Dispatch or claim each code-developer task for its assigned service/module.",
            "Continue TDD red/green/refactor for all assigned ACs in declared scope.",
            "Run e2e_dev_harness.py ac-progress for the active service or global design.",
            "Dispatch or complete R3 only after all assigned ACs pass ac-progress.",
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


def next_action_for_lifecycle(lifecycle: str, state: dict | None = None, runtime: str = "claude-code") -> dict:
    state = state or {}
    actions = {
        "CREATED": {
            "phase": "clarify",
            "command": "Dispatch the bootstrap requirements-clarifier worker; coordinator only relays unresolved user questions and records returned evidence.",
            "allowed_writes": ["docs/design/", "docs/agent-runs/"],
            "blocked_writes": ["production code", "tests outside harness evidence"],
        },
        "CLARIFIED": {
            "phase": "plan",
            "command": "Run e2e_dev_harness.py plan --design-doc <design> --create-archive, then complete R1 review.",
            "allowed_writes": ["docs/agent-runs/", "docs/design/"],
            "blocked_writes": ["production code"],
        },
        "SERVICE_DESIGN_REQUIRED": {
            "phase": "service-design",
            "command": "Fill service-designs/<service>.md for every affected service, validate with e2e_dev_harness.py service-design --run-state <state>, then continue to R1/TDD planning.",
            "allowed_writes": ["docs/agent-runs/", "docs/design/"],
            "blocked_writes": ["production code", "service code-agent dispatch before service-design gate passes"],
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
            "command": "Production code writes are open. Continue TDD red/green until ac-progress is ready for all assigned ACs, then run R3 review and completion gate.",
            "allowed_writes": ["declared production/test scope", "docs/agent-runs/"],
            "blocked_writes": ["undeclared scope drift", "R3 review before all assigned ACs pass ac-progress"],
        },
        "REVIEWED": {
            "phase": "completion",
            "command": "Run completion gate, strict guard, summary, and requirements archive validation.",
            "allowed_writes": ["docs/agent-runs/"],
            "blocked_writes": ["new production changes without rework item"],
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
        lifecycle,
        {
            "phase": "unknown",
            "command": "Inspect run-state.json and repair lifecycle before continuing.",
            "allowed_writes": ["docs/agent-runs/"],
            "blocked_writes": ["production code"],
        },
    )
    if lifecycle == "PLANNED" and state.get("selected_mode") == "multi":
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
    action["required_todo_list"] = required_todo_list_for_lifecycle(lifecycle, state)
    action["todo_policy"] = todo_policy_for_lifecycle(lifecycle, state)
    action["exploration_policy"] = exploration_policy_for_lifecycle(lifecycle)
    action.update(coordinator_action_fields(lifecycle, state, runtime))
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
    result["hook_status"] = hooks
    if forced_waiting:
        result.setdefault("warnings", []).append(
            "Runtime hook is missing or not enforceable; dispatch forced to WAITING_DISPATCH until an isolated worker is acknowledged."
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
        "next": action,
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
