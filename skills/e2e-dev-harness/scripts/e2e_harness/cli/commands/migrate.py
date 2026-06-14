"""migrate: back-fill per-phase contract stamps for a legacy run (Hybrid model).

Hybrid policy (F2): a run that passed a phase under an earlier, looser contract is
NOT retroactively invalidated when the live gate is later tightened. `migrate`
records, for each phase that no longer satisfies the live gate but carries a
non-empty subset of its evidence, a contract stamp = the intersection of the live
exit_gate with the evidence actually present. Phases that still satisfy the live
gate need no stamp; a phase with zero overlap is reported `skipped_empty` and is
NEVER stamped with `[]` (an empty stamp would silently revert to the live gate).

Read-only-except-stamp: it adds only `phases[*].contract`, an additive field under
run-state schema v1 — no schema bump, no evidence rewrite.
"""
from __future__ import annotations

from pathlib import Path

from e2e_harness.core import run_state
from e2e_harness import pipeline


def run(args) -> tuple[int, dict]:
    repo_root = Path(getattr(args, "repo", ".") or ".").resolve()
    spine = pipeline.spine_for_state(run_state.load(args.state), repo_root)
    stamped: list[dict] = []
    skipped_empty: list[str] = []

    def _mig(state: dict) -> None:
        phases = state.get("phases", {})
        for phase in spine:
            rec = phases.get(phase.name)
            if not rec or "contract" in rec:
                continue
            present = [k for k in phase.exit_gate if k in rec.get("evidence", {})]
            if len(present) == len(phase.exit_gate):
                continue  # already satisfies the live gate -> no stamp needed
            if not present:
                skipped_empty.append(phase.name)
                continue
            rec["contract"] = {"exit_gate": present}
            stamped.append({"phase": phase.name, "exit_gate": present})

    # Slice 1: extend the chain iff this run has one (started with emission on).
    run_state.mutate(args.state, _mig,
                     events_path=run_state.events_path_if_active(args.state))
    return 0, {
        "schema": "e2e-dev-harness.migrate.v1",
        "state": str(args.state),
        "stamped": stamped,
        "skipped_empty": skipped_empty,
    }
