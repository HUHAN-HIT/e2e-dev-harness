"""next: advance spine or return single blocker + navigation map."""
from __future__ import annotations

from pathlib import Path

from e2e_harness.core import run_state, engine, navigation
from e2e_harness import pipeline


def run(args) -> tuple[int, dict]:
    repo = Path(args.repo).resolve()
    spine = pipeline.spine_for_state(run_state.load(args.state))
    holder: dict = {}

    def _advance(state):
        state["_run_state_path"] = str(args.state)
        holder["res"] = engine.evaluate(spine, state, repo)
        state.pop("_run_state_path", None)

    state = run_state.mutate(args.state, _advance)
    res = holder["res"]
    res["navigation_map"] = navigation.navigation_map(spine, state, repo)
    res["run_state"] = str(args.state)
    return 0, res
