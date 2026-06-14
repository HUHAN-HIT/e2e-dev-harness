"""Read-only run diagnosis for `doctor --state`.

Computes the first blocking fact of a stuck run without mutating state or
replaying verification. Required evidence keys are derived from the lifecycle
catalog (`exit_gate`), not duplicated constants, and namespaced when the
current phase is module-scoped (`IMPLEMENTED#auth`). `next_legal_command` is
derived from the REAL CLI verb set, never the target-lifecycle diagram.
"""
from __future__ import annotations

import json
from pathlib import Path

from e2e_harness.core import event_log, lifecycle, multitrack, run_state, state_store


def _resolve_blocked_task(state_path: str, blocked_phase: str | None) -> str | None:
    """The worker dispatched for the blocked phase, read from the on-disk
    `agent-team-plan.json` (workers[].id / producer_ids written by `dispatch`).

    This is the honest current-checkout "task id" — phase-derived
    (`IMPLEMENTED-default`, `REVIEWED-r1`, or a module-namespaced `IMPLEMENTED#auth`)
    — NOT a fictional `T0x`. A worker belongs to phase P iff its id == P or starts
    with `P-` (a `-suffix` reviewer/default variant); `IMPLEMENTED#auth` does not
    start with `IMPLEMENTED-`, so a singleton phase never grabs a module worker and
    vice-versa. Returns the first match (sorted, deterministic) or None when no
    artifact names a worker for the phase — no value is invented."""
    if not blocked_phase:
        return None
    plan_path = Path(state_path).parent / "agent-team-plan.json"
    if not plan_path.exists():
        return None
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(plan, dict):
        return None
    workers = plan.get("workers")
    ids = [w["id"] for w in workers
           if isinstance(w, dict) and isinstance(w.get("id"), str)] \
        if isinstance(workers, list) else []
    if not ids:  # fall back to the evidence contract's producer_ids
        contract = plan.get("evidence_contract")
        if isinstance(contract, dict) and isinstance(contract.get("producer_ids"), list):
            ids = [i for i in contract["producer_ids"] if isinstance(i, str)]
    matches = sorted(i for i in ids if i == blocked_phase or i.startswith(blocked_phase + "-"))
    return matches[0] if matches else None


def _required_keys_for_phase(phase_name: str | None) -> list[str]:
    """exit_gate keys for a phase, namespaced when the phase is module-scoped.

    'IMPLEMENTED#auth' -> ['passing_tests#auth', 'test_substance#auth'];
    'IMPLEMENTED'      -> ['passing_tests', 'test_substance'].
    """
    if not phase_name:
        return []
    base = multitrack.base_phase_name(phase_name)   # 'IMPLEMENTED#auth' -> 'IMPLEMENTED'
    mod = multitrack.module_of(phase_name)          # 'IMPLEMENTED#auth' -> 'auth' (None if singleton)
    phase = lifecycle.catalog().get(base)
    if phase is None:
        return []
    return list(phase.exit_gate) if mod is None else [f"{k}#{mod}" for k in phase.exit_gate]


def _control_plane_fault(state: dict, state_path: str, current: str | None) -> dict | None:
    """Slice 3: the front-of-ladder control-plane integrity check that makes the two
    dormant functions (`verify_chain`, `detect_drift`) live. A tampered, drifted, or
    known-write-failed event witness invalidates EVERY downstream diagnosis, so it
    outranks missing-evidence / failed-gate.

    Precedence (highest first): a recorded write failure (the `events.jsonl.write-failed`
    sentinel — a PRECISE cause) > chain tamper / truncation (`verify_chain`) or
    projection drift (`detect_drift`) with no recorded cause. A known write failure
    must not be reported as ambiguous drift.

    Absent log => None: a run created before Phase 1, or `start` before its witness
    was seeded, records nothing — the check self-skips, matching detect_drift's
    not-yet-recorded != truncated rule. Returns the fault dict, or None when clean."""
    events_path = run_state.events_path_for(state_path)
    sentinel = run_state.write_failed_path_for(events_path)
    if sentinel.exists():
        reason = None
        try:
            reason = json.loads(sentinel.read_text(encoding="utf-8")).get("reason")
        except (OSError, ValueError):
            pass
        return {"kind": "event_log_write_failed", "phase": current, "task_id": None,
                "message": reason or f"event witness append failed (see {sentinel.name})"}
    if not events_path.exists():
        return None
    ok, why = event_log.verify_chain(events_path)
    if ok:
        ok, why = state_store.detect_drift(event_log.read_events(events_path), state)
    if not ok:
        return {"kind": "control_plane_drift", "phase": current, "task_id": None,
                "message": why}
    return None


def diagnose_run(state: dict, state_path: str, repo: str = ".") -> dict:
    current = state.get("current_phase")
    # Do NOT trust the SHAPE of the caller-supplied state. A non-dict phases map
    # or phase record would raise; a non-dict `evidence` (e.g. a JSON list) would
    # make `key not in evidence` a list-membership test and could report a false
    # all-clear for a structurally broken state. Coerce malformed shapes to empty
    # so a corrupt state reads as blocked (missing evidence), never as healthy.
    phases = state.get("phases")
    if not isinstance(phases, dict):
        phases = {}
    rec = phases.get(current or "", {})
    if not isinstance(rec, dict):
        rec = {}
    evidence = rec.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    required = _required_keys_for_phase(current)
    missing = [key for key in required if key not in evidence]
    # Mirror the READ-ONLY signals gate_passes blocks on — per-key failure ledger,
    # dispatch-failed floor, and a verification rework rollback — WITHOUT replaying
    # verification (repo_root is never threaded in here). A phase can be gate-blocked
    # with all evidence present (a reviewer recorded a `failed:<key>`), so
    # missing-evidence is NOT the only blocking fact. Precedence: the richest marker
    # first (rework rollback), then absent evidence, then a recorded/legacy failure.
    failures = rec.get("failures")
    failures = failures if isinstance(failures, dict) else {}
    rework = rec.get("rework_required")
    rework = rework if isinstance(rework, dict) else None
    dispatch_failed = rec.get("dispatch") == "failed"
    blocker = rec.get("blocker")
    first = None
    if rework:
        first = {
            "kind": "rework_required",
            "phase": current,
            "task_id": None,
            "message": blocker or rework.get("reason") or f"{current} requires rework",
        }
    elif missing:
        first = {
            "kind": "missing_evidence",
            "phase": current,
            "task_id": None,
            "message": f"{missing[0]} evidence is missing",
        }
    elif failures:
        fkey = sorted(failures)[0]
        first = {
            "kind": "failed_gate",
            "phase": current,
            "task_id": None,
            "message": blocker or failures.get(fkey) or f"{fkey} gate failed",
        }
    elif dispatch_failed:
        first = {
            "kind": "failed_gate",
            "phase": current,
            "task_id": None,
            "message": blocker or f"{current} dispatch failed",
        }
    # F-6: resolve the real blocked task id from the dispatch artifact (the worker
    # the harness dispatched for this phase), instead of returning null. Only when
    # blocked; otherwise nothing is stuck and there is no task to name.
    task_id = _resolve_blocked_task(state_path, current) if first else None
    if first is not None:
        first["task_id"] = task_id
    # next_legal_command is derived from the REAL CLI verb set — prog `e2e-dev-harness`,
    # commands start/next/dispatch/submit/gate/status/doctor/migrate, flags
    # `--state <run-state-path>` / `--repo` (see cli/main.py). It is NOT a target-lifecycle
    # fiction: there is no `dispatch-beat` command and no `--run-dir` flag. A missing-evidence
    # block is cleared by dispatching the blocked phase's worker, i.e. `dispatch`.
    next_cmd = (f"e2e-dev-harness dispatch --state {state_path} --repo {repo}"
                if first else None)
    # Slice 3: a control-plane fault outranks every domain fault — a tampered/drifted
    # witness invalidates the rest of the diagnosis. Its next step is READ-ONLY
    # (re-run doctor --state, inspect the log); recovery of a drifted plane stays
    # operator-gated, never an auto-mutating verb, and names no blocked worker.
    cp_fault = _control_plane_fault(state, state_path, current)
    if cp_fault is not None:
        first = cp_fault
        task_id = None
        next_cmd = f"e2e-dev-harness doctor --state {state_path} --repo {repo}"
    return {
        "schema": "e2e-dev-harness.doctor-state.v1",
        "diagnosis_ready": True,
        "run_blocked": bool(first),
        "run_dir": str(Path(state_path).parent),
        "first_fault": first,
        "blocked_phase": current if first else None,
        "blocked_task": task_id,
        "missing_evidence": missing,
        "next_legal_command": next_cmd,
        "coordinator_may_write_worker_outputs": False,
    }
