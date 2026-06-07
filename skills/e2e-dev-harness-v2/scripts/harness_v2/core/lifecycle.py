"""Declarative phase catalog + spine builder (domain-agnostic)."""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Phase:
    name: str
    worker_role: str
    worker_skill: str
    produces: tuple[str, ...]
    exit_gate: tuple[str, ...]
    next_phase: str | None


_CATALOG: dict[str, Phase] = {
    "CREATED":     Phase("CREATED", "", "", (), (), None),
    "CLARIFIED":   Phase("CLARIFIED", "requirements-clarifier", "e2e-harness-clarification", ("clarification",), ("clarification",), None),
    "PLANNED":     Phase("PLANNED", "implementation-planner", "e2e-harness-planning", ("plan",), ("plan",), None),
    "RED":         Phase("RED", "tdd-red", "e2e-harness-tdd-red", ("failing_tests",), ("failing_tests",), None),
    "IMPLEMENTED": Phase("IMPLEMENTED", "code-developer", "e2e-harness-implementation", ("passing_tests",), ("passing_tests",), None),
    "REVIEWED":    Phase("REVIEWED", "semantic-reviewer", "e2e-harness-review", ("review",), ("review",), None),
    "VERIFIED":    Phase("VERIFIED", "coverage-reviewer", "e2e-harness-completion", ("verification",), ("verification",), None),
}


def catalog() -> dict[str, Phase]:
    return dict(_CATALOG)


def build_spine(phase_names: list[str]) -> list[Phase]:
    spine: list[Phase] = []
    for i, name in enumerate(phase_names):
        base = _CATALOG[name]
        nxt = phase_names[i + 1] if i + 1 < len(phase_names) else None
        spine.append(replace(base, next_phase=nxt))
    return spine
