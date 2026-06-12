"""Engine: terminating advance (I1) + evidence submission."""
from __future__ import annotations

from pathlib import Path

from e2e_harness.adapters.evidence import hashing
from e2e_harness.core import gates, dispatch
from e2e_harness.core.lifecycle import Phase


def _phase_record(state: dict, name: str) -> dict:
    return state.setdefault("phases", {}).setdefault(name, {})


def submit_evidence(state: dict, phase_name: str, key: str, path: str, *,
                    repo_root=None, status: str = "done", reason: str | None = None) -> None:
    rec = _phase_record(state, phase_name)
    if status == "failed":
        # Per-key failure ledger (S1/S2): a failed key is recorded under its own
        # name (or "_phase" for a whole-phase failure) so a *different* reviewer's
        # later `done` cannot erase this failure signal. dispatch/blocker are still
        # set for v1 back-compat (rework routing + the `failed` result flag).
        rec.setdefault("failures", {})[key or "_phase"] = reason or ""
        rec["dispatch"] = dispatch.DispatchStatus.FAILED.value
        if reason:
            rec["blocker"] = reason
        return
    entry: dict = {"path": path}
    if repo_root is not None and path:
        candidate = Path(path)
        full = candidate if candidate.is_absolute() else Path(repo_root) / candidate
        if full.is_file():
            entry["sha256"] = hashing.sha256_file(full)
            entry["bytes"] = full.stat().st_size
    rec.setdefault("evidence", {})[key] = entry
    rec["dispatch"] = dispatch.DispatchStatus.DONE.value
    rec.pop("blocker", None)
    # Clear THIS key's failure (genuine rework) plus any whole-phase failure that a
    # successful re-drive resolves; other keys' failures stay intact (S1).
    failures = rec.get("failures")
    if failures:
        failures.pop(key, None)
        failures.pop("_phase", None)
        if not failures:
            rec.pop("failures", None)


def _by_name(spine: list[Phase]) -> dict[str, Phase]:
    return {p.name: p for p in spine}


def _rework_target(spine: list[Phase], failed_phase: str) -> Phase | None:
    names = [p.name for p in spine]
    if failed_phase not in names:
        return None
    failed_idx = names.index(failed_phase)
    for phase in reversed(spine[:failed_idx]):
        if phase.allows_code_write:
            return phase
    if failed_idx > 0:
        return spine[failed_idx - 1]
    return None


def _all_gate_evidence_submitted(phase: Phase, rec: dict) -> bool:
    evidence = rec.get("evidence", {})
    return bool(phase.exit_gate) and all(key in evidence for key in phase.exit_gate)


def _verification_rework_needed(phase: Phase, rec: dict, missing: list[str]) -> bool:
    if phase.name != "VERIFIED" or not missing:
        return False
    if rec.get("dispatch") == dispatch.DispatchStatus.FAILED.value:
        return True
    return _all_gate_evidence_submitted(phase, rec)


def _route_verification_rework(
    spine: list[Phase],
    state: dict,
    source: Phase,
    missing: list[str],
    reason: str,
) -> dict | None:
    target = _rework_target(spine, source.name)
    if target is None:
        return None
    target_rec = _phase_record(state, target.name)
    existing = target_rec.get("evidence", {})
    if existing:
        target_rec["superseded_evidence"] = dict(existing)
    target_rec["evidence"] = {}
    target_rec["dispatch"] = dispatch.DispatchStatus.FAILED.value
    target_rec["blocker"] = reason
    target_rec["rework_required"] = {
        "from_phase": source.name,
        "missing_evidence": list(missing),
        "reason": reason,
    }
    state["current_phase"] = target.name
    return {
        "complete": False,
        "blocked_phase": target.name,
        "missing_evidence": ["rework_required"],
        "next_action": dispatch.worker_packet(target, state.get("_run_state_path", "")),
        "rework_required": True,
        "rework_from_phase": source.name,
        "verification_missing_evidence": list(missing),
        "blocker": reason,
    }


def evaluate(spine: list[Phase], state: dict, repo_root=None) -> dict:
    """Advance current_phase past every gate that already passes; stop at first
    blocker or terminal. Terminates: each pass advances >=0 phases along a finite
    spine then blocks or completes."""
    by_name = _by_name(spine)
    name = state.get("current_phase", spine[0].name)
    while True:
        phase = by_name[name]
        rec = state.get("phases", {}).get(name, {})
        ok, missing = gates.gate_passes(phase, rec, repo_root)
        if not ok:
            if _verification_rework_needed(phase, rec, missing):
                reason = rec.get("blocker") or f"verification gate failed: {', '.join(missing)}"
                routed = _route_verification_rework(spine, state, phase, missing, reason)
                if routed is not None:
                    return routed
            state["current_phase"] = name
            result = {
                "complete": False,
                "blocked_phase": name,
                "missing_evidence": missing,
                "next_action": dispatch.worker_packet(phase, state.get("_run_state_path", "")),
            }
            if rec.get("dispatch") == dispatch.DispatchStatus.FAILED.value:
                result["failed"] = True
                result["blocker"] = rec.get("blocker")
            return result
        if phase.next_phase is None:
            state["current_phase"] = name
            return {"complete": True, "blocked_phase": None, "missing_evidence": [], "next_action": {}}
        name = phase.next_phase
