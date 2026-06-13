"""F4: validate an `agent_team_dispatch` evidence artifact.

The audited VERIFIED gate requires the agent-team dispatch chain to be provably
produced rather than write-only. The evidence is the dispatch-invocation JSON that
`cli/commands/dispatch.py` already writes; the worker submits its path like any other
gate key (next -> submit -> next), so a canonically-driven audited run records it.

Accepts a recorded manual-runtime BLOCK (non-empty `blocked`) as well as auto-spawn
`descriptors` — the block itself proves the dispatch step ran and was recorded, so an
audited run dispatched to a manual runtime is not left permanently unsatisfiable.
"""
from __future__ import annotations

import json
from pathlib import Path

DISPATCH_INVOCATION_SCHEMA = "e2e-dev-harness.dispatch-invocation.v1"


def validate_dispatch_invocation(obj, repo_root) -> tuple[bool, str | None]:
    if not isinstance(obj, dict) or obj.get("schema") != DISPATCH_INVOCATION_SCHEMA:
        return False, "bad-schema"
    if not obj.get("phase"):
        return False, "no-phase"
    descriptors = obj.get("descriptors")
    blocked = obj.get("blocked")
    has_desc = isinstance(descriptors, list) and len(descriptors) > 0
    has_block = isinstance(blocked, list) and len(blocked) > 0
    if not (has_desc or has_block):
        return False, "no-descriptors-or-block"
    plan_ref = obj.get("team_plan_path")
    if not plan_ref:
        return False, "no-team-plan-path"
    full = Path(plan_ref)
    if not full.is_absolute():
        full = Path(repo_root) / plan_ref
    if not full.is_file():
        return False, "team-plan-not-found"
    try:
        plan = json.loads(full.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "team-plan-not-json"
    if not isinstance(plan, dict) or not isinstance(plan.get("workers"), list) or not plan["workers"]:
        return False, "team-plan-no-workers"
    return True, None
