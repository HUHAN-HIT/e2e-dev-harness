#!/usr/bin/env python3
"""Declarative agent-role registry: single source of truth for role definitions.

This module consolidates what used to be scattered across `start.py`
(`ROLE_TEMPLATE_DETAILS`), `orchestration_plan.py` (`role_template_key`,
`role_group_for_phase`), and `agent_scheduler.py` (`PHASE_ROLE_GROUPS`). It is
*planning data only* — it never spawns, schedules, or terminates agents, so the
harness keeps its runtime-portability invariant. Consumers read from here so a
role's template body, name->key resolution, phase grouping, declared skills, and
subagent routing all stay in one place.

The seven keys below are the canonical roles. Agent names produced by
`orchestration_plan.agent_plan()` (e.g. `code-developer-order-service`,
`single-reviewer-r1-design`) resolve back to a canonical key via
`resolve_role_key()`.
"""

from __future__ import annotations

# Canonical role definitions. `template` fields are migrated verbatim from the
# legacy `ROLE_TEMPLATE_DETAILS` so `template_text()` renders byte-identical
# role-template files. `skills` is consumed by `agent_plan()` to declare which
# skills a role loads. `subagent_kind` ("reviewer"|"general") documents runtime
# routing intent.
ROLE_REGISTRY: dict[str, dict] = {
    "requirements-clarifier": {
        "template": {
            "boundary": "Clarify user intent, scope, ACs, unresolved questions, and bounded impact summary. Do not design tests or write code.",
            "inputs": "User request, project instructions, dependency/impact summaries, prior approved requirement facts.",
            "forbidden": "Production/test code edits, implementation planning, review approval, and speculative scope expansion.",
            "outputs": "Ready requirements handoff, impact summary rows, resolved/open question status, proposed memory updates.",
            "done": "All behavior/API/data/test-impacting questions are resolved or explicitly blocked, and downstream assumptions are stated.",
        },
        "skills": [],
        "subagent_kind": "general",
    },
    "use-case-designer": {
        "template": {
            "boundary": "Map ACs to use cases, failure paths, contracts, data effects, and service/module slices. Do not write tests or code.",
            "inputs": "Ready requirements handoff, impact summary, dependency report, project patterns.",
            "forbidden": "Changing accepted scope, production/test code edits, and approving own design.",
            "outputs": "Ready use-case handoff, service/use-case mapping, contract candidates, downstream assumptions.",
            "done": "Every AC maps to at least one use case or a documented deferral with owner and approval need.",
        },
        "skills": [],
        "subagent_kind": "general",
    },
    "implementation-planner": {
        "template": {
            "boundary": "Refine the implementation plan and dispatch sequence after R1 approval. Do not write tests or production code.",
            "inputs": "Ready requirements/use-case handoffs, R1 design review, impact summary, dependency report, project patterns.",
            "forbidden": "Approving own design, writing R1/R2/R3 reports, changing accepted scope, test edits, and production code edits.",
            "outputs": "Dispatch-ready exec plan evidence, open rework routing, service/code handoff assumptions.",
            "done": "TDD and implementation tasks have bounded inputs, ordered dependencies, and unresolved R1 findings are routed to rework.",
        },
        "skills": [],
        "subagent_kind": "general",
    },
    "test-case-developer": {
        "template": {
            "boundary": "Create test strategy, first red tests, contract tests, and test-impact commands. Do not modify production code.",
            "inputs": "Ready requirements and use-case handoffs, service design slices, TDD references.",
            "forbidden": "Production code edits, green implementation, semantic review approval, and changing AC scope.",
            "outputs": "Ready test handoff, red-test evidence path, test-impact plan, test command matrix.",
            "done": "A meaningful red test exists, fails for the expected reason, and R2 has enough evidence to review.",
        },
        "skills": ["superpowers:test-driven-development"],
        "subagent_kind": "general",
    },
    "code-developer": {
        "template": {
            "boundary": "Implement only assigned ACs and service/module scope using red-green-refactor. Do not alter requirements or review outputs.",
            "inputs": "Ready design/test handoffs, approved R2, service plan, service design slice, failing test evidence.",
            "forbidden": "Writing R1/R2/R3 reports, expanding scope, editing unclaimed services, or skipping AC progress.",
            "outputs": "Implementation handoff, implementation manifest, unit-test command JSON, coverage matrix, business review notes.",
            "done": "All assigned ACs have concrete code refs and passing tests; no undeclared file or behavior drift remains.",
        },
        "skills": [],
        "subagent_kind": "general",
    },
    "semantic-reviewer": {
        "template": {
            "boundary": "Review one phase from request-scoped inputs only. Do not write code or patch artifacts under review.",
            "inputs": "Review request, context pack, role handoffs, design/test/code evidence allowed by the request.",
            "forbidden": "Inherited developer chat context, self-review, production/test code edits, and consolidated after-the-fact review.",
            "outputs": "R1/R2/R3 review report, reviewer invocation JSON, blocking findings or rework items.",
            "done": "Review report has request hash, concrete session isolation proof, checked profile items, and status.",
        },
        "skills": [],
        "subagent_kind": "reviewer",
    },
    "coverage-reviewer": {
        "template": {
            "boundary": "Verify end-to-end AC coverage and archive outcomes. Do not patch implementation directly.",
            "inputs": "All ready role handoffs, semantic reviews, manifests, coverage matrix, command evidence, rework items.",
            "forbidden": "Closing gaps by editing code, ignoring failed commands, or archiving unresolved rework as complete.",
            "outputs": "Final coverage/business review, requirements archive, run summary, residual risk list.",
            "done": "Every AC maps to use case, tests, code refs, business review, accepted review status, and closed rework.",
        },
        "skills": [],
        "subagent_kind": "reviewer",
    },
}


# Single source of truth for phase -> role group. Both `agent_scheduler` and
# `orchestration_plan` import this; each keeps its own `.get()` default
# ("" for the scheduler's exclusivity check, "coordination" for planning) so
# behavior is preserved exactly.
PHASE_ROLE_GROUPS: dict[str, str] = {
    "clarify": "design",
    "design": "design",
    "plan": "planning",
    "tdd-red": "test",
    "implement": "code",
    "r1-review": "review",
    "r2-review": "review",
    "r3-review": "review",
    "completion": "coverage",
}


# Ordered name->key rules, equivalent to the legacy `role_template_key`
# substring matcher. Each rule: (role_key, include_any, exclude_any). The first
# rule whose include keyword is present (and no exclude keyword is present)
# wins; order is significant.
ROLE_KEY_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("requirements-clarifier", ("requirements", "clarifier"), ()),
    ("use-case-designer", ("use-case", "designer"), ()),
    ("implementation-planner", ("planner",), ()),
    ("test-case-developer", ("test",), ("review",)),
    ("code-developer", ("code-developer",), ()),
    ("coverage-reviewer", ("coverage",), ()),
    ("semantic-reviewer", ("reviewer", "review"), ()),
)


def resolve_role_key(agent_name: str) -> str:
    """Resolve a full agent name to its canonical role key.

    Reproduces the legacy `orchestration_plan.role_template_key` semantics:
    ordered substring matching, with the `test`/`review` exclusion, and "" for
    no match.
    """
    name = str(agent_name or "")
    for role_key, include_any, exclude_any in ROLE_KEY_RULES:
        if any(token in name for token in include_any) and not any(
            token in name for token in exclude_any
        ):
            return role_key
    return ""


def template_text(role: str) -> str:
    """Render the role-template markdown for a canonical role key.

    Unknown keys fall back to the `code-developer` body (legacy behavior), but
    the title still echoes the requested role name.
    """
    detail = ROLE_REGISTRY.get(role, ROLE_REGISTRY["code-developer"])["template"]
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


def role_skills(role_key: str) -> list[str]:
    """Skills a canonical role declares it loads (empty list if none)."""
    return list(ROLE_REGISTRY.get(role_key, {}).get("skills", []) or [])
