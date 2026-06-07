"""dispatch: emit one pointer worker packet for the current phase."""
from __future__ import annotations

from harness_v2.core import run_state, dispatch
from harness_v2 import pipeline


def run(args) -> tuple[int, dict]:
    state = run_state.load(args.state)
    spine = pipeline.build_spine(state.get("pipeline", "minimal"))
    name = state.get("current_phase")
    phase = next((p for p in spine if p.name == name), None)
    if phase is None or not phase.worker_skill:
        return 2, {"error": f"no dispatchable worker at phase {name}"}
    rec = state.setdefault("phases", {}).setdefault(name, {})
    rec["dispatch"] = dispatch.DispatchStatus.DISPATCHED.value
    run_state.save(args.state, state)
    return 0, dispatch.worker_packet(phase, str(args.state))
