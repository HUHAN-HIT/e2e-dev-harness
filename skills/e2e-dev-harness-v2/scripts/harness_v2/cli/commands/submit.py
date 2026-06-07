"""submit: record worker evidence and mark dispatch done."""
from __future__ import annotations

from harness_v2.core import run_state, engine


def run(args) -> tuple[int, dict]:
    state = run_state.load(args.state)
    engine.submit_evidence(state, args.phase, args.key, args.path)
    run_state.save(args.state, state)
    return 0, {"schema": "e2e-dev-harness-v2.submit.v1", "phase": args.phase,
               "key": args.key, "recorded": args.path}
