"""Start command facade."""

from __future__ import annotations

import json
from pathlib import Path

import artifact_registry
import coordinator_flow
import orchestration_plan
import run_state
from e2e_harness.cli.status import write_status


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


def _as_repo(path: Path) -> Path:
    repo = Path(path).resolve()
    if not repo.exists():
        raise FileNotFoundError(f"Repo not found: {repo}")
    return repo


def _resolve_repo_path(repo: Path, path: Path | None) -> Path | None:
    if not path:
        return None
    path = Path(path)
    return path if path.is_absolute() else repo / path


def _require_repo_path(repo: Path, path: Path | None, label: str) -> Path:
    resolved = _resolve_repo_path(repo, path)
    if resolved is None:
        raise ValueError(f"{label} path is required.")
    return resolved


def _posix_relative(path: Path, repo: Path) -> str:
    return str(path.relative_to(repo)).replace("\\", "/")


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
        resolved = _require_repo_path(repo, path, "phase profile")
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
    for lifecycle, phase, summary in coordinator_flow.BLUEPRINT_STEPS:
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
        path = _require_repo_path(repo, Path(relative_path), f"{role} role template")
        path.parent.mkdir(parents=True, exist_ok=True)
        text = role_template_text(role)
        if not path.exists() or path.read_text(encoding="utf-8", errors="replace") != text:
            path.write_text(text, encoding="utf-8")
            created.append(str(path))
    return created


def run(
    repo: Path,
    feature: str | None = None,
    request: str | None = None,
    design_doc: Path | None = None,
    agent_run_dir: Path | None = None,
    run_id: str | None = None,
    run_date: str | None = None,
    phase_mode: str = "auto",
    workflow_profile: str = "standard",
    phase_profile: Path | None = None,
    force: bool = False,
    status_file: Path | None = None,
) -> tuple[int, dict]:
    repo = _as_repo(repo)
    feature = feature or "feature"
    phase_mode = phase_mode or "auto"
    workflow_profile = workflow_profile or "standard"
    loaded_phase_profile, profile_blockers = load_phase_profile(repo, phase_profile)
    if profile_blockers:
        result = {
            "repo": str(repo),
            "ready": False,
            "blocked_reasons": profile_blockers,
            "warnings": [],
        }
        write_status(status_file, result)
        return 2, result

    slug = orchestration_plan.safe_slug(feature)
    run_id = run_id or orchestration_plan.default_run_id(slug, run_date)
    run_dir = _require_repo_path(repo, agent_run_dir or Path(f"docs/agent-runs/{run_id}"), "agent run directory")
    design_path = _require_repo_path(repo, design_doc or Path(f"docs/design/{slug}.md"), "design document")
    artifacts = orchestration_plan.artifacts(slug, _posix_relative(run_dir, repo), run_date, [])
    artifacts["design_doc"] = _posix_relative(design_path, repo)

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence").mkdir(parents=True, exist_ok=True)
    (run_dir / "confirmations").mkdir(parents=True, exist_ok=True)
    design_path.parent.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    if design_path.exists() and not force:
        design_created = False
    else:
        design_path.write_text(design_template(feature, request or ""), encoding="utf-8")
        design_created = True
        created.append(str(design_path))

    created.extend(create_role_template_files(repo, artifacts))

    workflow_plan = workflow_plan_for_start(phase_mode, workflow_profile, loaded_phase_profile, "CREATED")
    workflow_plan_path = _require_repo_path(repo, Path(artifacts["workflow_plan"]), "workflow plan")
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
    schedule_path = _require_repo_path(repo, Path(artifacts["agent_schedule"]), "agent schedule")
    schedule_path.write_text(json.dumps(schedule, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    created.append(str(schedule_path))

    registry = artifact_registry.build_registry(repo, artifacts["agent_run_dir"], artifacts, "bootstrap", [])
    registry_path = _require_repo_path(repo, Path(artifacts["artifact_registry"]), "artifact registry")
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
    state_path = _require_repo_path(repo, Path(artifacts["run_state"]), "run state")
    run_state.write_state(repo, state_path, state)
    created.append(str(state_path))

    lock_path = state_path.parent / run_state.PHASE_LOCK
    hooks = coordinator_flow.runtime_hook_status(repo)
    warnings = [] if design_created else ["Design document already existed; use --force to rewrite the starter template."]
    if hooks["ready"]:
        warnings += hooks.get("warnings", [])
    else:
        warnings += ["Runtime hook is not ready; install hooks or use pre-code before editing code."]
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
        "next": coordinator_flow.next_action_for_lifecycle("CREATED", state),
        "blocked_reasons": [],
        "warnings": warnings,
    }
    write_status(status_file, result)
    return 0, result


def run_from_args(args) -> tuple[int, dict]:
    return run(
        getattr(args, "repo"),
        feature=getattr(args, "feature", None),
        request=getattr(args, "request", None),
        design_doc=getattr(args, "design_doc", None),
        agent_run_dir=getattr(args, "agent_run_dir", None),
        run_id=getattr(args, "run_id", None),
        run_date=getattr(args, "run_date", None),
        phase_mode=getattr(args, "phase_mode", "auto"),
        workflow_profile=getattr(args, "workflow_profile", "standard"),
        phase_profile=getattr(args, "phase_profile", None),
        force=getattr(args, "force", False),
        status_file=getattr(args, "status_file", None),
    )
