"""status: human-readable navigation map (same source as next)."""
from __future__ import annotations

from pathlib import Path

from e2e_harness.core import run_state, navigation
from e2e_harness import pipeline


def run(args) -> tuple[int, dict]:
    state = run_state.load(args.state)
    repo = Path(args.repo).resolve()
    spine = pipeline.spine_for_state(state, repo)
    return 0, {"navigation_map": navigation.navigation_map(spine, state, repo)}
