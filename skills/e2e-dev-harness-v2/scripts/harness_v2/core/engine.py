"""Engine: terminating advance (I1) + evidence submission."""
from __future__ import annotations

from harness_v2.core import gates, dispatch
from harness_v2.core.lifecycle import Phase


def _phase_record(state: dict, name: str) -> dict:
    return state.setdefault("phases", {}).setdefault(name, {})


def submit_evidence(state: dict, phase_name: str, key: str, path: str) -> None:
    rec = _phase_record(state, phase_name)
    rec.setdefault("evidence", {})[key] = path
    rec["dispatch"] = dispatch.DispatchStatus.DONE.value


def _by_name(spine: list[Phase]) -> dict[str, Phase]:
    return {p.name: p for p in spine}


def evaluate(spine: list[Phase], state: dict) -> dict:
    """Advance current_phase past every gate that already passes; stop at first
    blocker or terminal. Terminates: each pass advances >=0 phases along a finite
    spine then blocks or completes."""
    by_name = _by_name(spine)
    name = state.get("current_phase", spine[0].name)
    while True:
        phase = by_name[name]
        rec = state.get("phases", {}).get(name, {})
        ok, missing = gates.gate_passes(phase, rec)
        if not ok:
            state["current_phase"] = name
            return {
                "complete": False,
                "blocked_phase": name,
                "missing_evidence": missing,
                "next_action": dispatch.worker_packet(phase, state.get("_run_state_path", "")),
            }
        if phase.next_phase is None:
            state["current_phase"] = name
            return {"complete": True, "blocked_phase": None, "missing_evidence": [], "next_action": {}}
        name = phase.next_phase
