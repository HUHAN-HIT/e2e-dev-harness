"""approve-impact-degradation: coordinator records the degradation trust anchor.

Degraded impact evidence is trusted ONLY when state.approvals.impact_degradation
exists and its sha256 matches the artifact's approval hash (design: Degraded
Approval). A worker-authored markdown file is fallback evidence, not the anchor —
this command is the coordinator-owned write that the validator checks against.
"""
from __future__ import annotations

from pathlib import Path

from e2e_harness.core import run_state
from e2e_harness.adapters.evidence import hashing

_REQUIRED_MARKER = "approval: user-approved"


def run(args) -> tuple[int, dict]:
    approval = Path(args.approval)
    if not approval.is_file():
        return 2, {"error": f"approval file not found: {approval}"}
    text = approval.read_text(encoding="utf-8", errors="replace").lower()
    if _REQUIRED_MARKER not in text:
        return 2, {"error": "approval missing required marker: 'Approval: user-approved'"}
    if "reason:" not in text:
        return 2, {"error": "approval missing 'Reason:'"}
    if "fallback evidence:" not in text and "compensating evidence:" not in text:
        return 2, {"error": "approval missing 'Fallback Evidence:'"}

    sha = hashing.sha256_file(approval)

    def _record(state):
        state.setdefault("approvals", {})["impact_degradation"] = {
            "source": "user-approved",
            "approval_path": str(args.approval),
            "sha256": sha,
            "recorded_by": "coordinator",
            "reason": getattr(args, "reason", None) or "",
        }

    run_state.mutate(args.state, _record,
                     events_path=run_state.events_path_if_active(args.state))
    return 0, {"schema": "e2e-dev-harness.impact-degradation-approval.v1",
               "state": str(args.state), "sha256": sha, "recorded_by": "coordinator"}
