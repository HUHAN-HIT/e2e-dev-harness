"""Dispatch status read model.

This module classifies legacy and current dispatch strings without changing the
stored compatibility facts. Older states remain visible for diagnostics; callers
consume categories when deciding active/completion behavior.
"""

from __future__ import annotations

from dataclasses import dataclass


ACTIVE_STATUSES = {
    "awaiting_runtime_spawn",
    "waiting_dispatch",
    "worker_running",
    "worker_running_unverified",
    "worker_dispatched",
    "dispatched",
}
AWAITING_WORKER_PROOF_STATUSES = {
    "awaiting_runtime_spawn",
    "waiting_dispatch",
    "worker_dispatched",
    "dispatched",
}
LEGACY_UNVERIFIED_STATUSES = {"worker_running_unverified"}
RUNNING_STATUSES = {"worker_running"}
COMPLETED_STATUSES = {"worker_completed", "completed"}


@dataclass(frozen=True)
class DispatchFacts:
    status: str
    category: str
    active: bool
    awaiting_worker_proof: bool
    running: bool
    completed: bool
    legacy_unverified: bool


def classify(status: object, metadata: dict | None = None) -> DispatchFacts:
    value = str(status or "").strip().lower()
    meta = metadata or {}
    legacy_unverified = value in LEGACY_UNVERIFIED_STATUSES or str(meta.get("spawn_confirmed_by", "")).strip() == "phase_guard"
    awaiting_worker_proof = value in AWAITING_WORKER_PROOF_STATUSES
    running = value in RUNNING_STATUSES
    completed = value in COMPLETED_STATUSES
    active = value in ACTIVE_STATUSES
    if awaiting_worker_proof:
        category = "waiting"
    elif legacy_unverified:
        category = "legacy_unverified"
    elif running:
        category = "running"
    elif completed:
        category = "completed"
    elif value:
        category = "other"
    else:
        category = "missing"
    return DispatchFacts(
        status=value,
        category=category,
        active=active,
        awaiting_worker_proof=awaiting_worker_proof,
        running=running,
        completed=completed,
        legacy_unverified=legacy_unverified,
    )
