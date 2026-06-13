"""Read-only run diagnosis for `doctor --state`.

Computes the first blocking fact of a stuck run without mutating state or
replaying verification. Required evidence keys are derived from the lifecycle
catalog (`exit_gate`), not duplicated constants, and namespaced when the
current phase is module-scoped (`IMPLEMENTED#auth`). `next_legal_command` is
derived from the REAL CLI verb set, never the target-lifecycle diagram.
"""
from __future__ import annotations

from pathlib import Path

from e2e_harness.core import lifecycle, multitrack


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
    # next_legal_command is derived from the REAL CLI verb set — prog `e2e-dev-harness`,
    # commands start/next/dispatch/submit/gate/status/doctor/migrate, flags
    # `--state <run-state-path>` / `--repo` (see cli/main.py). It is NOT a target-lifecycle
    # fiction: there is no `dispatch-beat` command and no `--run-dir` flag. A missing-evidence
    # block is cleared by dispatching the blocked phase's worker, i.e. `dispatch`.
    next_cmd = (f"e2e-dev-harness dispatch --state {state_path} --repo {repo}"
                if first else None)
    return {
        "schema": "e2e-dev-harness.doctor-state.v1",
        "diagnosis_ready": True,
        "run_blocked": bool(first),
        "run_dir": str(Path(state_path).parent),
        "first_fault": first,
        "blocked_phase": current if first else None,
        "blocked_task": None,
        "missing_evidence": missing,
        "next_legal_command": next_cmd,
        "coordinator_may_write_worker_outputs": False,
    }
