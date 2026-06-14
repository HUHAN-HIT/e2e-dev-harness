"""approve-impact-degradation: coordinator records the degradation trust anchor.

Degraded impact evidence is trusted ONLY when state.approvals.impact_degradation
exists and its sha256 matches the artifact's approval hash (design: Degraded
Approval). A worker-authored markdown file is fallback evidence, not the anchor —
this command is the coordinator-owned write that the validator checks against.
"""
from __future__ import annotations

import json
from pathlib import Path

from e2e_harness.core import run_state
from e2e_harness.adapters.evidence import hashing

SCHEMA = "e2e-dev-harness.impact-degradation-approval.v1"


def _nonempty_string_list(value) -> bool:
    return isinstance(value, list) and any(isinstance(v, str) and v.strip() for v in value)


def _load_approval(path: Path) -> tuple[dict | None, str | None]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"approval must be {SCHEMA} JSON: {exc}"
    if not isinstance(obj, dict):
        return None, "approval JSON must be an object"
    if obj.get("schema") != SCHEMA:
        return None, f"approval schema must be {SCHEMA}"
    if obj.get("approval") != "user-approved":
        return None, "approval field must be 'user-approved'"
    if not isinstance(obj.get("reason"), str) or not obj["reason"].strip():
        return None, "approval reason is required"
    if not (_nonempty_string_list(obj.get("fallback_evidence"))
            or _nonempty_string_list(obj.get("compensating_evidence"))):
        return None, "approval requires fallback_evidence or compensating_evidence"
    return obj, None


def run(args) -> tuple[int, dict]:
    approval = Path(args.approval)
    if not approval.is_file():
        return 2, {"error": f"approval file not found: {approval}"}
    approval_obj, error = _load_approval(approval)
    if error:
        return 2, {"error": error}

    sha = hashing.sha256_file(approval)

    def _record(state):
        state.setdefault("approvals", {})["impact_degradation"] = {
            "source": "user-approved",
            "approval_path": str(args.approval),
            "sha256": sha,
            "recorded_by": "coordinator",
            "reason": getattr(args, "reason", None) or approval_obj["reason"],
        }

    run_state.mutate(args.state, _record,
                     events_path=run_state.events_path_if_active(args.state))
    return 0, {"schema": "e2e-dev-harness.impact-degradation-approval.v1",
               "state": str(args.state), "sha256": sha, "recorded_by": "coordinator"}
