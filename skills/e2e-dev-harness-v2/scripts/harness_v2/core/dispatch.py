"""Single dispatch status enum + pointer worker packet."""
from __future__ import annotations

from enum import Enum

from harness_v2.core.lifecycle import Phase

PACKET_SCHEMA = "e2e-dev-harness-v2.worker-packet.v1"


class DispatchStatus(str, Enum):
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
