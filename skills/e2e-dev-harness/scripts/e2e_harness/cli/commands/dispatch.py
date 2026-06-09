"""dispatch: emit one pointer worker packet for the current phase."""
from __future__ import annotations

from e2e_harness.core import run_state, dispatch
from e2e_harness import pipeline
from e2e_harness.adapters import runtime


def run(args) -> tuple[int, dict]:
    state = run_state.load(args.state)
    spine = pipeline.spine_for_state(state)
    name = state.get("current_phase")
    phase = next((p for p in spine if p.name == name), None)
    if phase is None or not phase.worker_skill:
        return 2, {"error": f"no dispatchable worker at phase {name}"}
    def _mark_dispatched(s):
        rec = s.setdefault("phases", {}).setdefault(s.get("current_phase"), {})
        rec["dispatch"] = dispatch.DispatchStatus.DISPATCHED.value

    state = run_state.mutate(args.state, _mark_dispatched)
    # Surface the self-describing domain block (if any) to the worker. Backend
    # runs carry no domain block ⇒ extra=[] ⇒ packet is unchanged (parity).
    extra: list[str] = []
    dom = state.get("domain")
    if dom:
        extra = [f"domain:{dom['name']} test_runner:{dom['test_runner']} "
                 f"review_profile:{dom['review_profile']}"]
    packet = dispatch.worker_packet(phase, str(args.state), extra_context=extra)
    # Additive (方案1): translate the pointer packet into a runtime launch
    # descriptor. The coordinator performs the real tool call; this stays a
    # pure control plane.
    packet["worker_descriptor"] = runtime.spawn_worker(
        packet, getattr(args, "runtime", "claude-code"))
    return 0, packet
