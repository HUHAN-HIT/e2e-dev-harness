"""Approval-gated control-plane recovery (design Phase 3).

`recover` is a two-step, auditable repair path — NOT a gate bypass:

    plan_recovery(state, state_path, repo)                  -> recovery-plan.v1   (READ-ONLY)
    apply_recovery(state_path, approval_path, repo, events) -> recovery-applied.v1

It is the ONLY path that may flip `coordinator_may_write_worker_outputs` to True,
and only under an explicit approval that grants it. Concretely it does exactly
ONE narrow repair: register a genuine, human-supplied worker artifact (named by
the approval) through the SAME sanctioned write path as `submit`, so the gate
still governs completion. It therefore honors every Phase-3 prohibition:

- it cannot mark a phase complete without trusted proof — the artifact is real,
  hashed, and still faces the gate on the next `next`/`gate`;
- it refuses to turn a MISSING artifact into a passing state (the file must exist);
- it does not collapse PARTIAL into COMPLETE (it never touches scope labeling);
- it does not bypass evidence validators (`submit_evidence(repo_root=...)` hashes
  and the gate re-validates);
- it records input/output hashes of `run-state.json` and writes a
  recovery.approved / recovery.applied audit trail to the tamper-evident log.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from e2e_harness.core import engine, event_log, run_state, state_diagnosis

PLAN_SCHEMA = "e2e-dev-harness.recovery-plan.v1"
APPLIED_SCHEMA = "e2e-dev-harness.recovery-applied.v1"
APPROVAL_SCHEMA = "e2e-dev-harness.recovery-approval.v1"
REFUSED_SCHEMA = "e2e-dev-harness.recovery-refused.v1"


class RecoveryRefused(Exception):
    """A recovery apply was refused: no/invalid approval, or it would fabricate
    a passing state from a missing artifact."""


def _sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sibling_events_path(state_path: str | Path) -> Path:
    return Path(state_path).parent / "events.jsonl"


def plan_recovery(state: dict, state_path: str, repo: str = ".") -> dict:
    """READ-ONLY recovery plan derived from the read-only run diagnosis. Names the
    first blocking fact and the narrow repair that would clear it, but authorizes
    nothing — `requires_approval` is True and `coordinator_may_write_worker_outputs`
    stays False (matching doctor-state.v1). Must not mutate state or emit events."""
    diag = state_diagnosis.diagnose_run(state, state_path, repo)
    blocked = bool(diag["run_blocked"])
    repair = None
    if blocked:
        repair = {
            "kind": "supply_missing_evidence",
            "phase": diag["blocked_phase"],
            "evidence_keys": list(diag["missing_evidence"]),
        }
    return {
        "schema": PLAN_SCHEMA,
        "run_dir": diag["run_dir"],
        "recoverable": blocked,
        "blocked_phase": diag["blocked_phase"],
        "first_fault": diag["first_fault"],
        "proposed_repair": repair,
        "requires_approval": blocked,
        "coordinator_may_write_worker_outputs": False,
        "input_hashes": {"run_state": _sha256_file(state_path)},
    }


def _load_approval(approval_path: str | None) -> dict:
    if not approval_path:
        raise RecoveryRefused("recover --apply requires --approval <path>")
    try:
        obj = json.loads(Path(approval_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecoveryRefused(f"approval unreadable: {exc}") from exc
    if not isinstance(obj, dict) or not obj.get("approved"):
        raise RecoveryRefused("approval is not granted (approved != true)")
    if not obj.get("coordinator_may_write_worker_outputs"):
        raise RecoveryRefused(
            "approval does not grant coordinator_may_write_worker_outputs")
    if not (obj.get("phase") and obj.get("key") and obj.get("evidence_path")):
        raise RecoveryRefused("approval must name phase, key and evidence_path")
    return obj


def apply_recovery(state_path: str, approval_path: str | None, repo: str = ".",
                   events_path: str | Path | None = None) -> dict:
    """Perform the ONE narrow, approved repair and record an audit trail.

    Refuses (RecoveryRefused) when there is no approval, the approval does not
    grant the worker-output write, or the named evidence file is missing. Records
    input/output run-state hashes and appends recovery.approved/applied to the
    tamper-evident event log."""
    approval = _load_approval(approval_path)
    repo_root = Path(repo).resolve()
    phase, key, rel = approval["phase"], approval["key"], approval["evidence_path"]
    full = Path(rel)
    if not full.is_absolute():
        full = repo_root / rel
    if not full.is_file():
        # Hard refusal: recovery must never turn a MISSING artifact into a pass.
        raise RecoveryRefused(f"approved evidence file is missing: {rel}")

    if events_path is None:
        events_path = _sibling_events_path(state_path)

    input_hash = _sha256_file(state_path)
    event_log.append_event(events_path, {
        "type": "recovery.approved", "phase": phase, "key": key,
        "approver": approval.get("approver"), "reason": approval.get("reason"),
        "evidence_path": rel, "input_hashes": {"run_state": input_hash},
    })

    # Resolve the phase's live exit_gate so a gate-completing recovery submit
    # stamps the contract-in-force (mirrors submit.py); unknown phase -> no stamp.
    from e2e_harness import pipeline  # local import: pipeline imports core, not vice-versa
    spine = pipeline.spine_for_state(run_state.load(state_path), repo_root)
    target = next((p for p in spine if p.name == phase), None)
    exit_gate = target.exit_gate if target is not None else None
    run_state.mutate(
        state_path,
        lambda st: engine.submit_evidence(st, phase, key, rel, repo_root=repo_root,
                                          exit_gate=exit_gate),
        events_path=events_path,
    )

    output_hash = _sha256_file(state_path)
    event_log.append_event(events_path, {
        "type": "recovery.applied", "phase": phase, "key": key,
        "input_hashes": {"run_state": input_hash},
        "output_hashes": {"run_state": output_hash},
    })
    return {
        "schema": APPLIED_SCHEMA,
        "run_dir": str(Path(state_path).parent),
        "applied_repair": {"kind": "supply_missing_evidence", "phase": phase,
                           "key": key, "evidence_path": rel},
        "coordinator_may_write_worker_outputs": True,
        "input_hashes": {"run_state": input_hash},
        "output_hashes": {"run_state": output_hash},
    }
