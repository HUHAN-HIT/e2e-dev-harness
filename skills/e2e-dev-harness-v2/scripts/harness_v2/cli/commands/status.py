"""status: human-readable navigation map (same source as next)."""
from __future__ import annotations

from harness_v2.core import run_state, lifecycle, navigation
from harness_v2 import pipeline


def run(args) -> tuple[int, dict]:
    state = run_state.load(args.state)
    spine = lifecycle.build_spine(pipeline.active_phase_names(state.get("pipeline", "minimal")))
    return 0, {"navigation_map": navigation.navigation_map(spine, state)}
