"""submit: record worker evidence (or mark failed) and update dispatch."""
from __future__ import annotations

from pathlib import Path

from harness_v2.core import run_state, engine


def run(args) -> tuple[int, dict]:
    state = run_state.load(args.state)
    engine.submit_evidence(
        state, args.phase, args.key, args.path,
        repo_root=Path(args.repo).resolve(),
        status=getattr(args, "status", "done"),
        reason=getattr(args, "reason", None),
    )
    run_state.save(args.state, state)
    return 0, {"schema": "e2e-dev-harness-v2.submit.v1", "phase": args.phase,
               "key": args.key, "recorded": args.path,
               "status": getattr(args, "status", "done")}
