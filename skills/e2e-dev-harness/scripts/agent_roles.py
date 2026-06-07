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

import json
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
ROLE_ASSET_DIR = SKILL_ROOT / "agent-roles" / "roles"
TEAM_ASSET_DIR = SKILL_ROOT / "agent-roles" / "teams"

# Canonical role definitions. `template` fields are migrated verbatim from the
# legacy `ROLE_TEMPLATE_DETAILS` so `template_text()` renders byte-identical
# role-template files. `skills` is consumed by `agent_plan()` to declare which
# skills a role loads. `subagent_kind` ("reviewer"|"general") documents runtime
# routing intent. `runtime_subagent_type` is the concrete runtime agent alias
# projected into dispatch spawn requests unless a project overrides the phase.
_FALLBACK_ROLE_REGISTRY: dict[str, dict] = {
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
        "runtime_subagent_type": "requirements-clarifier",
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
        "runtime_subagent_type": "use-case-designer",
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
        "runtime_subagent_type": "implementation-planner",
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
        "runtime_subagent_type": "test-case-developer",
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
        "runtime_subagent_type": "code-developer",
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
        "runtime_subagent_type": "semantic-reviewer",
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
        "runtime_subagent_type": "coverage-reviewer",
    },
}


def role_asset_paths(directory: Path | None = None) -> dict[str, Path]:
    """Canonical role key -> declaration file path."""
    root = directory or ROLE_ASSET_DIR
    discovered = {path.stem: path for path in root.glob("*.json")}
    ordered = {
        key: discovered[key]
        for key in _FALLBACK_ROLE_REGISTRY
        if key in discovered
    }
    for key in sorted(set(discovered) - set(ordered)):
        ordered[key] = discovered[key]
    return ordered


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _valid_role_entry(data: dict) -> bool:
    template = data.get("template")
    if not isinstance(template, dict):
        return False
    required = ("boundary", "inputs", "forbidden", "outputs", "done")
    return all(str(template.get(key, "")).strip() for key in required)


def load_role_registry(directory: Path | None = None) -> dict[str, dict]:
    """Load role declarations from assets, falling back to bundled defaults."""
    loaded: dict[str, dict] = {}
    for key, path in role_asset_paths(directory).items():
        entry = _read_json(path)
        if _valid_role_entry(entry):
            loaded[key] = {
                "template": dict(entry["template"]),
                "skills": list(entry.get("skills", []) or []),
                "subagent_kind": str(entry.get("subagent_kind", "general") or "general"),
                "runtime_subagent_type": str(entry.get("runtime_subagent_type", "") or ""),
            }
    if set(loaded) != set(_FALLBACK_ROLE_REGISTRY):
        return {key: dict(value) for key, value in _FALLBACK_ROLE_REGISTRY.items()}
    return loaded


def team_asset_paths(directory: Path | None = None) -> dict[str, Path]:
    """Team preset key -> declaration file path."""
    root = directory or TEAM_ASSET_DIR
    return {path.stem: path for path in sorted(root.glob("*.json"))}


def load_team_registry(directory: Path | None = None) -> dict[str, dict]:
    """Load declarative team presets for schedule construction."""
    loaded: dict[str, dict] = {}
    for key, path in team_asset_paths(directory).items():
        entry = _read_json(path)
        roles = entry.get("roles", [])
        if isinstance(roles, list) and roles:
            loaded[key] = dict(entry)
    return loaded


ROLE_REGISTRY: dict[str, dict] = load_role_registry()
TEAM_REGISTRY: dict[str, dict] = load_team_registry()


def team_preset_key(selected_mode: str) -> str:
    """Team preset key for an orchestration mode, or "" when mode has none."""
    mode = str(selected_mode or "").strip()
    if mode == "bootstrap":
        return "bootstrap"
    if mode == "multi":
        return "multi-service"
    return ""


def team_preset_for_mode(selected_mode: str) -> dict:
    """Declarative team preset for `selected_mode` (fresh copy)."""
    key = team_preset_key(selected_mode)
    if not key:
        return {}
    preset = TEAM_REGISTRY.get(key, {})
    return dict(preset)


# Single source of truth for workflow-phase ordering knowledge. Each phase
# declares its execution `order`, its `role_group`, the canonical role that owns
# it, and the phases it `depends_on`. Insertion order is kept identical to the
# legacy `PHASE_ROLE_GROUPS` literal so the derived table below preserves order;
# the numeric `order` field encodes the real (dependency-respecting) execution
# sequence, which differs from insertion order for the review phases.
PHASE_REGISTRY: dict[str, dict] = {
    "clarify": {"order": 1, "role_group": "design", "canonical_role": "requirements-clarifier", "depends_on": []},
    "design": {"order": 2, "role_group": "design", "canonical_role": "use-case-designer", "depends_on": ["clarify"]},
    "plan": {"order": 4, "role_group": "planning", "canonical_role": "implementation-planner", "depends_on": ["r1-review"]},
    "tdd-red": {"order": 5, "role_group": "test", "canonical_role": "test-case-developer", "depends_on": ["design", "r1-review", "plan"]},
    "implement": {"order": 7, "role_group": "code", "canonical_role": "code-developer", "depends_on": ["tdd-red", "r2-review"]},
    "r1-review": {"order": 3, "role_group": "review", "canonical_role": "semantic-reviewer", "depends_on": ["design"]},
    "r2-review": {"order": 6, "role_group": "review", "canonical_role": "semantic-reviewer", "depends_on": ["tdd-red"]},
    "r3-review": {"order": 8, "role_group": "review", "canonical_role": "semantic-reviewer", "depends_on": ["implement"]},
    "completion": {"order": 9, "role_group": "coverage", "canonical_role": "coverage-reviewer", "depends_on": ["r3-review"]},
}


# Derived: phase -> role group. Both `agent_scheduler` and `orchestration_plan`
# import this; each keeps its own `.get()` default ("" for the scheduler's
# exclusivity check, "coordination" for planning) so behavior is preserved
# exactly. Derived from PHASE_REGISTRY so the grouping cannot drift.
PHASE_ROLE_GROUPS: dict[str, str] = {
    phase: meta["role_group"] for phase, meta in PHASE_REGISTRY.items()
}


# Phase -> (required_skill, required_skill_path, reference_set). Additive and
# optional: phases absent here (coordination, minimal-only bespoke phases) carry
# no capability fields and never block. Gates in scripts remain authoritative.
PHASE_SKILL_CAPABILITIES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "clarify": (
        "e2e-harness-clarification",
        "skills/e2e-harness-clarification/SKILL.md",
        ("clarification-gate", "agent-instructions"),
    ),
    "plan": (
        "e2e-harness-planning",
        "skills/e2e-harness-planning/SKILL.md",
        ("agent-orchestration", "implementation-gates"),
    ),
    "tdd-red": (
        "e2e-harness-tdd-red",
        "skills/e2e-harness-tdd-red/SKILL.md",
        ("tdd-java-spring", "agent-orchestration"),
    ),
    "implement": (
        "e2e-harness-implementation",
        "skills/e2e-harness-implementation/SKILL.md",
        ("tdd-java-spring", "implementation-gates"),
    ),
    "r1-review": (
        "e2e-harness-review",
        "skills/e2e-harness-review/SKILL.md",
        ("review-profiles", "common-review-issues"),
    ),
    "r2-review": (
        "e2e-harness-review",
        "skills/e2e-harness-review/SKILL.md",
        ("review-profiles", "common-review-issues"),
    ),
    "r3-review": (
        "e2e-harness-review",
        "skills/e2e-harness-review/SKILL.md",
        ("review-profiles", "common-review-issues"),
    ),
    "completion": (
        "e2e-harness-completion",
        "skills/e2e-harness-completion/SKILL.md",
        ("implementation-gates", "requirements-archive"),
    ),
}


def phase_required_skill(phase: str) -> str:
    entry = PHASE_SKILL_CAPABILITIES.get(str(phase).strip())
    return entry[0] if entry else ""


def phase_required_skill_path(phase: str) -> str:
    entry = PHASE_SKILL_CAPABILITIES.get(str(phase).strip())
    return entry[1] if entry else ""


def phase_skill_reference_set(phase: str) -> list[str]:
    entry = PHASE_SKILL_CAPABILITIES.get(str(phase).strip())
    return list(entry[2]) if entry else []


def depends_on_for_phase(phase: str) -> list[str]:
    """Phases that must complete before `phase` (fresh copy per call).

    Unknown phases fall back to ``["plan"]`` to match the legacy
    `orchestration_plan.depends_on_for_phase` default.
    """
    meta = PHASE_REGISTRY.get(phase)
    if meta is None:
        return ["plan"]
    return list(meta["depends_on"])


def phase_role_group(phase: str) -> str:
    """Role group for a phase, or "" when the phase is unknown.

    Callers that need a non-empty default read `PHASE_ROLE_GROUPS.get(phase, ...)`
    directly so each keeps its own historical default.
    """
    meta = PHASE_REGISTRY.get(phase)
    return meta["role_group"] if meta is not None else ""


def role_to_phase(role_key: str) -> str:
    """Canonical phase a role owns (lowest `order` it owns), or "" if unknown.

    Reviewer roles own several phases (r1/r2/r3); the canonical one is the
    earliest in execution order. Phase disambiguation that needs the agent name
    (e.g. r1 vs r2 vs r3) stays in `orchestration_plan.phase_for_agent`.
    """
    key = str(role_key or "")
    if not key:
        return ""
    owned = [
        (meta["order"], phase)
        for phase, meta in PHASE_REGISTRY.items()
        if meta["canonical_role"] == key
    ]
    if not owned:
        return ""
    return min(owned)[1]


def phase_subagent_kind(phase: str) -> str:
    """Declared subagent kind of the phase's canonical role ("" if unknown).

    "reviewer" means the phase should route to the project's reviewer subagent;
    "general" keeps it on general-purpose. Routing reads this declaration so the
    `subagent_kind` field is live data, not documentation that a parallel
    hardcoded role-group check could silently contradict.
    """
    meta = PHASE_REGISTRY.get(phase)
    if meta is None:
        return ""
    return str(ROLE_REGISTRY.get(meta["canonical_role"], {}).get("subagent_kind", ""))


def phase_runtime_subagent_type(phase: str) -> str:
    """Concrete runtime subagent type declared by the phase's canonical role."""
    meta = PHASE_REGISTRY.get(phase)
    if meta is None:
        return ""
    return str(ROLE_REGISTRY.get(meta["canonical_role"], {}).get("runtime_subagent_type", ""))


# Single source of truth for lifecycle -> phase gating. `allowed` is the set of
# phases dispatchable at that lifecycle; `satisfied` is the set treated as
# already-complete (suppressing missing-dependency blockers and re-dispatch of
# satisfied phases). Both `agent_scheduler` and `dispatcher` re-bind the derived
# tables below to their module-level names. Not every lifecycle participates in
# both tables, mirroring the legacy literals exactly.
#
# `SERVICE_DESIGN_REQUIRED.satisfied` includes `r1-review` on purpose: it defers
# the R1 design review until service design completes, then `PLANNED` drops it so
# the review runs there. (See harness-role-phase-convergence-plan Step 2.)
LIFECYCLE_REGISTRY: dict[str, dict] = {
    "CREATED": {"allowed": {"clarify"}},
    "CLARIFIED": {"allowed": {"design", "r1-review"}, "satisfied": {"clarify"}},
    "SERVICE_DESIGN_REQUIRED": {
        "allowed": {"design", "r1-review"},
        "satisfied": {"clarify", "design", "r1-review"},
    },
    "PLANNED": {
        "allowed": {"r1-review", "plan", "tdd-red", "r2-review"},
        "satisfied": {"clarify", "design"},
    },
    "RED_READY": {
        "allowed": set(),
        "satisfied": {"clarify", "design", "r1-review", "plan", "tdd-red", "r2-review"},
    },
    "IMPLEMENTED": {
        "allowed": {"implement", "r3-review", "completion"},
        "satisfied": {"clarify", "design", "r1-review", "plan", "tdd-red", "r2-review"},
    },
    "REVIEWED": {
        "allowed": {"completion"},
        "satisfied": {"clarify", "design", "r1-review", "plan", "tdd-red", "r2-review", "implement", "r3-review"},
    },
    "VERIFIED": {
        "satisfied": {"clarify", "design", "r1-review", "plan", "tdd-red", "r2-review", "implement", "r3-review", "completion"},
    },
    "REWORK_REQUIRED": {
        "allowed": {"clarify", "design", "r1-review", "tdd-red", "r2-review", "implement", "r3-review", "completion"},
    },
}


LIFECYCLE_ALLOWED_PHASES: dict[str, set[str]] = {
    lifecycle: meta["allowed"]
    for lifecycle, meta in LIFECYCLE_REGISTRY.items()
    if "allowed" in meta
}
LIFECYCLE_SATISFIED_PHASES: dict[str, set[str]] = {
    lifecycle: meta["satisfied"]
    for lifecycle, meta in LIFECYCLE_REGISTRY.items()
    if "satisfied" in meta
}


# Ordered name->key rules, equivalent to the legacy `role_template_key`
# substring matcher. Each rule: (role_key, include_any, exclude_any). The first
# rule whose include keyword is present (and no exclude keyword is present)
# wins; order is significant.
#
# `code-developer` is matched BEFORE the broad `test` rule so a code-developer
# agent for a service whose slug contains "test" (e.g.
# "code-developer-notification-test") resolves to `code-developer`, not
# `test-case-developer`. The explicit `code-developer` token is unambiguous,
# whereas `test` is an incidental keyword that can appear in a service slug.
# This mirrors the precedence already encoded in
# `orchestration_plan.phase_for_agent` (which checks `code-developer` before
# `test`). `test-case-developer` names contain no `code-developer` token, so
# they still fall through to the `test` rule. See
# tests.LegacyParityTest / tests.ResolveRoleKeyTest.
ROLE_KEY_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("requirements-clarifier", ("requirements", "clarifier"), ()),
    ("use-case-designer", ("use-case", "designer"), ()),
    ("implementation-planner", ("planner",), ()),
    ("code-developer", ("code-developer",), ()),
    ("test-case-developer", ("test",), ("review",)),
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


def _required_worker_skill_section(role: str) -> str:
    """Compact phase-skill capability section appended to a role template.

    Returns "" when the role's phase has no mapped worker skill (additive).
    """
    phase = role_to_phase(role)
    skill = phase_required_skill(phase)
    if not skill:
        return ""
    return (
        "\n## Required Worker Skill\n\n"
        f"- Skill: `{skill}`\n"
        f"- Skill file: `{phase_required_skill_path(phase)}`\n"
        "- Load only this worker skill plus the context pack and listed input files.\n"
        "- Do not inherit coordinator chat context.\n"
    )


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
""" + _required_worker_skill_section(role)


def role_skills(role_key: str) -> list[str]:
    """Skills a canonical role declares it loads (empty list if none)."""
    return list(ROLE_REGISTRY.get(role_key, {}).get("skills", []) or [])
