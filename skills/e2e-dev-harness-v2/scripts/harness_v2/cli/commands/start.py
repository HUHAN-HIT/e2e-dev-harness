"""start: create the one run-state."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from harness_v2.core import run_state


def run(args) -> tuple[int, dict]:
    repo = Path(args.repo).resolve()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + args.feature
    rel = Path("docs/agent-runs") / run_id / "run-state.json"
    path = repo / rel
    st = run_state.new_run_state(run_id, args.feature, args.request,
                                 tier=args.tier, pipeline=args.tier)
    run_state.save(path, st)
    return 0, {"schema": "e2e-dev-harness-v2.start.v1", "run_id": run_id,
               "run_state": str(path), "current_phase": "CREATED", "tier": args.tier}
