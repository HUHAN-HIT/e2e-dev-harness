"""Lifecycle policy facade over the legacy coordinator guidance modules."""

from __future__ import annotations

from pathlib import Path

import lifecycle_policy as _legacy_policy
import phase_guard


def guidance_for_lifecycle(repo: Path | None = None, lock: Path | None = None, lifecycle: str = "") -> dict:
    if repo is not None:
        return phase_guard.guidance_for_lifecycle(repo, lock, lifecycle)
    return {
        "schema": "e2e-dev-harness.lifecycle-policy.v1",
        "lifecycle": lifecycle or "<missing>",
        "todo_policy": _legacy_policy.todo_policy_for_lifecycle(lifecycle),
        "clarification_interaction": _legacy_policy.clarification_interaction_for_lifecycle(lifecycle),
    }


def todo_policy_for_lifecycle(lifecycle: str, state: dict | None = None) -> dict:
    return _legacy_policy.todo_policy_for_lifecycle(lifecycle, state)

