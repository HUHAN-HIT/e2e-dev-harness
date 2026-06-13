"""submit: record worker evidence (or mark failed) and update dispatch."""
from __future__ import annotations

from pathlib import Path

from e2e_harness.core import run_state, engine
from e2e_harness import pipeline


def run(args) -> tuple[int, dict]:
    repo_root = Path(args.repo).resolve()
    # F2 (Hybrid): resolve the phase's live exit_gate so a gate-completing submit
    # stamps the contract-in-force at pass time. An unknown phase yields no gate ->
    # no stamp (safe; legacy behavior).
    spine = pipeline.spine_for_state(run_state.load(args.state), repo_root)
    phase = next((p for p in spine if p.name == args.phase), None)
    exit_gate = phase.exit_gate if phase is not None else None
    run_state.mutate(
        args.state,
        lambda state: engine.submit_evidence(
            state, args.phase, args.key, args.path,
            repo_root=repo_root,
            status=getattr(args, "status", "done"),
            reason=getattr(args, "reason", None),
            exit_gate=exit_gate,
        ),
    )
    return 0, {"schema": "e2e-dev-harness.submit.v1", "phase": args.phase,
               "key": args.key, "recorded": args.path,
               "status": getattr(args, "status", "done")}
