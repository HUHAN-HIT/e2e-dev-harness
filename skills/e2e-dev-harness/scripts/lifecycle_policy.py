"""Single source for lifecycle-scoped coordinator and hook guidance."""

from __future__ import annotations

import ask_user_bridge
import run_state


TODO_RULE = (
    "TodoList must describe only the current lifecycle phase; do not include future "
    "implementation/code tasks before the implementation gate."
)


def clarification_requests() -> list[dict]:
    return [
        {
            "id": "confirm_restated_intent",
            "header": "Intent",
            "question": "Confirm or revise the requirements-clarifier worker's Restated Intent.",
            "options": [
                {
                    "label": "Confirm (Recommended)",
                    "description": "Use when the worker's Restated Intent matches the user's goal.",
                },
                {
                    "label": "Revise",
                    "description": "Use when the user needs to correct scope, behavior, or wording.",
                },
                {
                    "label": "Keep blocked",
                    "description": "Use when the user cannot confirm intent yet.",
                },
            ],
            "provenance_required": "Record confirmed-by: user @<date/session/artifact> in Restated Intent.",
        },
        {
            "id": "resolve_open_questions",
            "header": "Questions",
            "question": "Answer, defer, or keep blocked on unresolved Open Questions returned by the worker.",
            "options": [
                {
                    "label": "Answer now (Recommended)",
                    "description": "Use when the user can close the returned Open Questions now.",
                },
                {
                    "label": "Defer out of scope",
                    "description": "Use when the user explicitly excludes the question from this implementation.",
                },
                {
                    "label": "Keep blocked",
                    "description": "Use when planning and implementation should wait.",
                },
            ],
            "provenance_required": "Record confirmed-by: user @<date/session/artifact> in Open Questions.",
        },
    ]


def clarification_interaction_for_lifecycle(lifecycle: str) -> dict:
    active = lifecycle == "CREATED"
    requests = clarification_requests() if active else []
    return {
        "schema": "e2e-dev-harness.clarification-interaction.v1",
        "interaction_required": active,
        "must_wait_for_user_answer": active,
        "questions_to_ask_user": [
            "Relay the requirements-clarifier worker's Restated Intent confirmation request to the user.",
            "Relay only unresolved behavior, API, data, ownership, test, or impact questions returned by the worker.",
            "Record the worker's returned evidence paths after answers are captured.",
        ] if active else [],
        "ask_user_schema": "codex.request_user_input.v1",
        "ask_user_requests": requests,
        "runtime_action": ask_user_bridge.request_user_input_action(requests),
        "allowed_before_user_answer": [
            "dispatching the requirements-clarifier worker",
            "recording dispatcher-generated context pack, invocation, and worker handle paths",
        ] if active else [],
        "blocked_until_resolved": [
            "planning",
            "TDD",
            "production-code edits",
            "review dispatch that depends on clarified behavior",
        ] if active else [],
    }


def _minimal_todo_list_for_lifecycle(lifecycle: str) -> list[str]:
    state_path = "docs/agent-runs/<run>/run-state.json"
    lists = {
        "CREATED": [
            "Dispatch a single worker to complete clarify, plan, implement, and test in one pass; do not re-dispatch per phase and do not run an independent reviewer dispatch.",
            "Relay only unresolved Restated Intent or Open Questions from the worker to the user.",
            f"Advance run-state ({state_path}) through its states for run-state integrity; minimal tier does not require per-state worker hand-back cycles.",
        ],
        "VERIFIED": [
            "Enforce only the load-bearing gates (clarification, test-evidence, task-alignment, run-state) at the VERIFIED exit and report evidence paths.",
        ],
    }
    return lists.get(
        lifecycle,
        [
            "Continue the single worker's one pass (clarify, plan, implement, test); coordinator runs only control-plane finish and next, with no independent reviewer dispatch.",
            f"Run e2e_dev_harness.py next --state {state_path} to advance; enforce only the load-bearing 4 gates at the VERIFIED exit.",
        ],
    )


def required_todo_list_for_lifecycle(lifecycle: str, state: dict | None = None, tier: str = "standard") -> list[str]:
    if str(tier).strip().lower() == "minimal":
        return _minimal_todo_list_for_lifecycle(lifecycle)
    state_path = "docs/agent-runs/<run>/run-state.json"
    schedule_path = "docs/agent-runs/<run>/agent-schedule.json"
    lists = {
        "CREATED": [
            f"Run e2e_dev_harness.py dispatch-beat --max-workers 1 --schedule {schedule_path} --state {state_path} to dispatch requirements-clarifier.",
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
            "direct_tools_allowed_for": [
                "design-doc requirements analysis",
                "Restated Intent",
                "Open Questions",
            ],
            "direct_tools_blocked_for": [
                "code Read/Grep/Glob",
                "GitNexus impact evidence",
                "implementation planning",
            ],
            "required_for": ["requirements clarification", "Restated Intent", "impact evidence", "design doc updates"],
            "fallback": "Run dispatch-beat --max-workers 1 for the requirements-clarifier worker; coordinator may only relay returned questions and evidence paths.",
            "lifecycle": lifecycle,
        }
    return {
        "schema": "e2e-dev-harness.exploration-policy.v1",
        "preferred": "gitnexus",
        "direct_tools_allowed_for": ["seed discovery", "small quoted evidence after GitNexus points to a file"],
        "direct_tools_blocked_for": [],
        "required_for": ["impact analysis", "call path tracing", "cross-service dependencies", "route/topic/contract ownership"],
        "fallback": "If GitNexus is unavailable, write degradation evidence before treating rg/Read findings as workflow evidence.",
        "lifecycle": lifecycle or "<missing>",
    }


def todo_policy_for_lifecycle(lifecycle: str, state: dict | None = None) -> dict:
    return {
        "schema": "e2e-dev-harness.todo-policy.v1",
        "mode": "phase-scoped",
        "lifecycle": lifecycle or "<missing>",
        "rule": TODO_RULE,
        "required_todo_list": required_todo_list_for_lifecycle(lifecycle, state, run_state.workflow_tier(state)),
        "exploration_policy": exploration_policy_for_lifecycle(lifecycle),
    }
