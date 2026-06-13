"""next: advance spine or return single blocker + navigation map."""
from __future__ import annotations

from pathlib import Path

from e2e_harness.core import run_state, engine, navigation
from e2e_harness.adapters.evidence import scope as scope_ev
from e2e_harness.adapters.evidence import clarification
from e2e_harness import pipeline


def run(args) -> tuple[int, dict]:
    repo = Path(args.repo).resolve()
    spine = pipeline.spine_for_state(run_state.load(args.state), repo)
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
    # fix A3: when CLARIFIED is the blocker, name the still-open questions so the
    # re-clarify loop is actionable (ask -> user answers -> resubmit -> advance)
    # instead of an opaque "acceptance_contract missing".
    if res.get("blocked_phase") == "CLARIFIED":
        pending = clarification.pending_from_state(state, repo)
        if pending:
            res["open_questions"] = pending
            ids = ", ".join(q["id"] for q in pending)
            res["blocker"] = f"{len(pending)} open question(s) awaiting user confirmation: {ids}"
    res["navigation_map"] = navigation.navigation_map(spine, state, repo)
    res["run_state"] = str(args.state)
    return 0, res
