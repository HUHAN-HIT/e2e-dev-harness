"""next: advance spine or return single blocker + navigation map."""
from __future__ import annotations

from pathlib import Path

from e2e_harness.core import run_state, engine, navigation
from e2e_harness.adapters.evidence import scope as scope_ev
from e2e_harness import pipeline


def run(args) -> tuple[int, dict]:
    repo = Path(args.repo).resolve()
    spine = pipeline.spine_for_state(run_state.load(args.state))
    holder: dict = {}

    def _advance(state):
        state["_run_state_path"] = str(args.state)
        res = engine.evaluate(spine, state, repo)
        holder["res"] = res
        # link ②: on completion, label the run COMPLETE vs PARTIAL from the
        # grounded scope manifest so a subset delivery is never a silent VERIFIED.
        if res.get("complete"):
            status, undelivered = scope_ev.label_delivery(state, repo)
            if status is not None:
                state["delivery"] = status
                state["undelivered"] = undelivered
                res["delivery"] = status
                res["undelivered"] = undelivered
        state.pop("_run_state_path", None)

    state = run_state.mutate(args.state, _advance)
    res = holder["res"]
    res["navigation_map"] = navigation.navigation_map(spine, state, repo)
    res["run_state"] = str(args.state)
    return 0, res
