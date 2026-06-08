"""next: advance spine or return single blocker + navigation map."""
from __future__ import annotations

from pathlib import Path

from harness_v2.core import run_state, engine, navigation
from harness_v2 import pipeline


def run(args) -> tuple[int, dict]:
    repo = Path(args.repo).resolve()
    state = run_state.load(args.state)
    state["_run_state_path"] = str(args.state)
    spine = pipeline.spine_for_state(state)
    res = engine.evaluate(spine, state, repo)
    state.pop("_run_state_path", None)
    run_state.save(args.state, state)
    res["navigation_map"] = navigation.navigation_map(spine, state, repo)
    res["run_state"] = str(args.state)
    return 0, res
