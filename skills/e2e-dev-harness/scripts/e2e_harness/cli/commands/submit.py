"""submit: record worker evidence (or mark failed) and update dispatch."""
from __future__ import annotations

from pathlib import Path

from e2e_harness.core import run_state, engine


def run(args) -> tuple[int, dict]:
    repo_root = Path(args.repo).resolve()
    run_state.mutate(
        args.state,
        lambda state: engine.submit_evidence(
            state, args.phase, args.key, args.path,
            repo_root=repo_root,
            status=getattr(args, "status", "done"),
            reason=getattr(args, "reason", None),
        ),
    )
    return 0, {"schema": "e2e-dev-harness-v2.submit.v1", "phase": args.phase,
               "key": args.key, "recorded": args.path,
               "status": getattr(args, "status", "done")}
