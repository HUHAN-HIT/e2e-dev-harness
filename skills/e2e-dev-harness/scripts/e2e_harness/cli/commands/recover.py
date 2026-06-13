"""recover: approval-gated, auditable control-plane repair (design Phase 3).

`recover --plan` is read-only (recovery-plan.v1). `recover --apply --approval
<path>` performs one narrow, approved repair (recovery-applied.v1) or refuses
(recovery-refused.v1, exit 2) without mutating state. See core.recovery."""
from __future__ import annotations

from e2e_harness.core import recovery, run_state


def run(args) -> tuple[int, dict]:
    if getattr(args, "apply", False):
        try:
            payload = recovery.apply_recovery(
                args.state, getattr(args, "approval", None), getattr(args, "repo", "."))
        except recovery.RecoveryRefused as exc:
            return 2, {"schema": recovery.REFUSED_SCHEMA, "error": str(exc)}
        return 0, payload
    # Default and --plan: read-only diagnosis -> recovery plan, never mutating.
    state = run_state.load(args.state)
    return 0, recovery.plan_recovery(state, args.state, getattr(args, "repo", "."))
