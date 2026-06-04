"""Orchestrator facade over coordinator flow."""

from __future__ import annotations

import coordinator_flow


def next_step(args) -> tuple[int, dict]:
    return coordinator_flow.next_step(args)
