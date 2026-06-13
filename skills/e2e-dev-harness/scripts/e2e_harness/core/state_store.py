"""Projection replay: rebuild a run-state-shaped dict from the event log.

This is the read side of the Phase 4 seam — events are authoritative,
`run-state.json` is the *output* of replaying them. The replay is intentionally
narrow (the smallest useful event set) and pure: no I/O, no mutation of the
event log. It is NOT yet wired into the write path; coupling `append_event` into
`run_state.mutate` is a separate, later projection task.
"""
from __future__ import annotations


def replay_events(events: list[dict]) -> dict:
    state: dict = {"phases": {}}
    for event in events:
        etype = event.get("type")
        phase = event.get("phase")
        if etype == "run.started":
            state["run_id"] = event.get("run_id")
        elif etype == "phase.submitted" and phase:
            state["current_phase"] = phase
        elif etype == "gate.passed" and phase:
            state.setdefault("phases", {}).setdefault(phase, {})["dispatch"] = "done"
        elif etype == "gate.failed" and phase:
            rec = state.setdefault("phases", {}).setdefault(phase, {})
            rec["dispatch"] = "failed"
            rec["blocker"] = event.get("reason")
    return state
