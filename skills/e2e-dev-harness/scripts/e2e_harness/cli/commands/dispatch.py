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

    # P1: single default (codex), consistent with the seam/argparse default.
    runtime_name = getattr(args, "runtime", None) or "codex"
    adapter = runtime.get_adapter(runtime_name)
    caps = adapter.capabilities()

    # Surface the self-describing domain block (if any) to the worker. Backend
    # runs carry no domain block ⇒ extra=[] ⇒ packet is unchanged (parity).
    extra: list[str] = []
    dom = state.get("domain")
    if dom:
        extra = [f"domain:{dom['name']} test_runner:{dom['test_runner']} "
                 f"review_profile:{dom['review_profile']}"]
    packet = dispatch.worker_packet(phase, str(args.state), extra_context=extra)
    # The dispatcher talks only to the adapter interface. The coordinator still
    # performs the real tool call; this stays a pure control plane.
    packet["worker_descriptor"] = adapter.spawn(packet)

    # (c): a runtime that cannot auto-spawn must NOT be marked DISPATCHED — that
    # would let the coordinator self-deal. Surface an explicit block and leave
    # the phase in its implicit PENDING state (no WAITING_DISPATCH enum member;
    # that overlapping state was deliberately removed in the 2026-06-07 redesign).
    if not caps.can_auto_spawn:
        packet["dispatch_blocked"] = {
            "reason": "manual_runtime_requires_human_dispatch",
            "runtime": caps.name,
            "next_action": "human dispatches the worker, then `submit` its evidence",
        }
        return 3, packet

    def _mark_dispatched(s):
        rec = s.setdefault("phases", {}).setdefault(s.get("current_phase"), {})
        rec["dispatch"] = dispatch.DispatchStatus.DISPATCHED.value

    run_state.mutate(args.state, _mark_dispatched)
    return 0, packet
