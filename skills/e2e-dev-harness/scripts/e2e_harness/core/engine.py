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


def _by_name(spine: list[Phase]) -> dict[str, Phase]:
    return {p.name: p for p in spine}


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
