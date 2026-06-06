"""Typed helpers for the single-file harness control plane."""

from __future__ import annotations

from typing import Any


SCHEMA = "e2e-dev-harness.control-plane.v1"


def default_control_plane(run_id: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "lifecycle": "CREATED",
        "gates": {},
        "phase_lock": {
            "state": "code-write-locked",
            "lifecycle": "CREATED",
            "code_writes_allowed": False,
            "worker_output_writes_allowed": False,
        },
        "tasks": [],
        "dispatches": {},
        "repair_transactions": {},
        "artifacts": {},
        "coordinator": {},
        "projections": {},
        "history": [],
    }
