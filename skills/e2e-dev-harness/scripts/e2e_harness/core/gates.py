"""Declarative gate evaluation + closure invariant (I2)."""
from __future__ import annotations

from e2e_harness.adapters.evidence import validate
from e2e_harness.core.lifecycle import Phase


def gate_passes(phase: Phase, phase_record: dict | None,
                repo_root=None, *, skip_replay: bool = False) -> tuple[bool, list[str]]:
    rec = phase_record or {}
    # v1 floor: a legacy record whose whole-phase dispatch is FAILED and which
    # carries no per-key ledger still blocks the gate.
    if rec.get("dispatch") == "failed" and not rec.get("failures"):
        return False, ["failed"]
    evidence = rec.get("evidence", {})
    missing: list[str] = []
    for k in phase.exit_gate:
        if k not in evidence:
            missing.append(k)
            continue
        if repo_root is not None:
            ok, _reason = validate.validate_evidence(repo_root, k, evidence[k], skip_replay=skip_replay)
            if not ok:
                missing.append(k)
    # S1/S2: an unresolved per-key failure blocks the gate even when the evidence is
    # present and the phase dispatch later reads DONE — a sibling reviewer's success
    # must not paper over another reviewer's recorded failure.
    for fkey in sorted(rec.get("failures", {})):
        marker = f"failed:{fkey}"
        if marker not in missing:
            missing.append(marker)
    return (not missing, missing)


def gate_closure_ok(spine: list[Phase]) -> tuple[bool, list[str]]:
    produced: set[str] = set()
    required: set[str] = set()
    for p in spine:
        produced.update(p.produces)
        required.update(p.exit_gate)
    unmet = sorted(required - produced)
    return (not unmet, unmet)
