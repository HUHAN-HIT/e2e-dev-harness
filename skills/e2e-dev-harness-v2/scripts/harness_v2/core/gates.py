"""Declarative gate evaluation + closure invariant (I2)."""
from __future__ import annotations

from harness_v2.core.lifecycle import Phase


def gate_passes(phase: Phase, phase_record: dict | None) -> tuple[bool, list[str]]:
    evidence = (phase_record or {}).get("evidence", {})
    missing = [k for k in phase.exit_gate if k not in evidence]
    return (not missing, missing)


def gate_closure_ok(spine: list[Phase]) -> tuple[bool, list[str]]:
    produced: set[str] = set()
    required: set[str] = set()
    for p in spine:
        produced.update(p.produces)
        required.update(p.exit_gate)
    unmet = sorted(required - produced)
    return (not unmet, unmet)
