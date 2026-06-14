"""Declarative gate evaluation + closure invariant (I2)."""
from __future__ import annotations

from e2e_harness.adapters.evidence import validate
from e2e_harness.core.lifecycle import Phase


def gate_passes(phase: Phase, phase_record: dict | None,
                repo_root=None, *, skip_replay: bool = False,
                state: dict | None = None) -> tuple[bool, list[str]]:
    # `state` (F-4) is threaded through to validate_evidence so the scope_manifest
    # validator can ground phases/services against the trusted run-state at gate
    # time. None (the default, and every navigation/display caller) keeps the
    # legacy tables-only grounding — no behavior change for those paths.
    rec = phase_record or {}
    # v1 floor: a legacy record whose whole-phase dispatch is FAILED and which
    # carries no per-key ledger still blocks the gate.
    if rec.get("dispatch") == "failed" and not rec.get("failures"):
        return False, ["failed"]
    evidence = rec.get("evidence", {})
    # F2 (Hybrid contract model): judge against the contract stamped when this phase
    # passed, if any, else the live spine gate. A later tightening of phase.exit_gate
    # therefore cannot retroactively fail a phase that legitimately passed under the
    # earlier contract. An empty/absent stamp falls back to the live gate.
    effective_gate = tuple(rec.get("contract", {}).get("exit_gate") or phase.exit_gate)
    missing: list[str] = []
    for k in effective_gate:
        if k not in evidence:
            missing.append(k)
            continue
        if repo_root is not None:
            ok, _reason = validate.validate_evidence(repo_root, k, evidence[k],
                                                     skip_replay=skip_replay, state=state)
            if not ok:
                missing.append(k)
    # PLANNED supplemental impact gate (design). State-aware and pure: only with a
    # threaded run-state, and only for PLANNED, so base-gate unit tests that pass no
    # state legitimately skip it. `blocked` is owned by the CLARIFIED edge, so this
    # never reports it (see impact_gate.planned_missing).
    if state is not None and phase.name == "PLANNED":
        from e2e_harness.core import impact_gate
        missing.extend(impact_gate.planned_missing(state, repo_root, rec))
    # S1/S2: an unresolved per-key failure blocks the gate even when the evidence is
    # present and the phase dispatch later reads DONE — a sibling reviewer's success
    # must not paper over another reviewer's recorded failure.
    for fkey in sorted(rec.get("failures", {})):
        marker = f"failed:{fkey}"
        if marker not in missing:
            missing.append(marker)
    return (not missing, missing)


def all_gates_pass(spine: list[Phase], state: dict, repo_root=None,
                   *, skip_replay: bool = False) -> tuple[bool, list[tuple[str, list[str]]]]:
    """Whole-journey closure (F1): the run is complete iff EVERY phase gate
    currently passes — not merely because the cursor reached the terminal phase.

    Returns ``(all_ok, blockers)`` where ``blockers`` is ``[(phase_name, missing)]``
    in spine order, so ``blockers[0]`` is the earliest still-failing phase. The
    single source of "is the journey closed", shared by the engine (authoritative,
    ``skip_replay=False``) and navigation (display, ``skip_replay=True``). The two
    agree exactly for presence/structured keys; for replay keys they may legitimately
    diverge because navigation deliberately skips the side-effecting replay.

    The contract a phase is judged against is resolved inside ``gate_passes``
    (``rec['contract']['exit_gate']`` snapshot when present, else the live
    ``phase.exit_gate``), so this predicate inherits the snapshot/live policy for
    free and needs no contract parameter of its own.
    """
    phases_rec = state.get("phases", {})
    blockers: list[tuple[str, list[str]]] = []
    for phase in spine:
        ok, missing = gate_passes(phase, phases_rec.get(phase.name, {}),
                                  repo_root, skip_replay=skip_replay, state=state)
        if not ok:
            blockers.append((phase.name, missing))
    return (not blockers, blockers)


def gate_closure_ok(spine: list[Phase]) -> tuple[bool, list[str]]:
    produced: set[str] = set()
    required: set[str] = set()
    for p in spine:
        produced.update(p.produces)
        required.update(p.exit_gate)
    unmet = sorted(required - produced)
    return (not unmet, unmet)
