"""Declarative gate evaluation + closure invariant (I2)."""
from __future__ import annotations

from harness_v2.adapters.evidence import validate
from harness_v2.core.lifecycle import Phase


def gate_passes(phase: Phase, phase_record: dict | None,
                repo_root=None) -> tuple[bool, list[str]]:
    evidence = (phase_record or {}).get("evidence", {})
    missing: list[str] = []
    for k in phase.exit_gate:
        if k not in evidence:
            missing.append(k)
            continue
        if repo_root is not None:
            ok, _reason = validate.validate_evidence(repo_root, k, evidence[k])
            if not ok:
                missing.append(k)
    return (not missing, missing)


def gate_closure_ok(spine: list[Phase]) -> tuple[bool, list[str]]:
    produced: set[str] = set()
    required: set[str] = set()
    for p in spine:
        produced.update(p.produces)
        required.update(p.exit_gate)
    unmet = sorted(required - produced)
    return (not unmet, unmet)
