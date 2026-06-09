"""Single dispatch status enum + pointer worker packet."""
from __future__ import annotations

from enum import Enum

from e2e_harness.core.lifecycle import Phase

PACKET_SCHEMA = "e2e-dev-harness.worker-packet.v1"


class DispatchStatus(str, Enum):
    """Canonical single dispatch lifecycle (design §3) — the one enum that replaces
    M1's 6+ overlapping states:

        pending -> dispatched -> running -> done   (+ failed)

    Not every state is written by the current coordinator flow, by design:
    - PENDING is the *implicit* initial state — a phase with no dispatch record yet.
    - DISPATCHED is set by the `dispatch` verb; DONE/FAILED by `submit`.
    - RUNNING is reserved for runtime adapters that can observe a worker mid-flight
      (the pointer model doesn't track that yet; wired when a runtime adapter lands).

    These are protocol vocabulary, not dead code — kept so the lifecycle stays
    complete and forward-compatible.
    """

    PENDING = "pending"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


def worker_packet(phase: Phase, run_state_path: str,
                  extra_context: list[str] | None = None) -> dict:
    return {
        "schema": PACKET_SCHEMA,
        "role": phase.worker_role,
        "skill": phase.worker_skill,
        "context_paths": [run_state_path, *(extra_context or [])],
        "expected_outputs": list(phase.produces),
    }
