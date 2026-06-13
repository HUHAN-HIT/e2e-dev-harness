"""Derive the CLARIFIED re-clarify blocker from the acceptance contract (fix A3).

Thin I/O sibling of scope.label_delivery: locate the CLARIFIED acceptance
contract on the run-state, load it, and return the still-open questions so the
coordinator can show the user exactly what blocks clarification. Robust to a
missing / unreadable / malformed contract — returns [] rather than raising.
"""
from __future__ import annotations

import json
from pathlib import Path

from e2e_harness.core import acceptance


def pending_from_state(state: dict, repo_root) -> list[dict]:
    """[{id, question}] still-open questions on the CLARIFIED contract, else []."""
    entry = (state.get("phases", {}).get("CLARIFIED", {})
             .get("evidence", {}).get("acceptance_contract"))
    if not entry:
        return []
    rel = entry["path"] if isinstance(entry, dict) else entry
    full = Path(rel)
    if not full.is_absolute():
        full = Path(repo_root) / rel
    try:
        obj = json.loads(full.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return acceptance.pending_questions(obj)
