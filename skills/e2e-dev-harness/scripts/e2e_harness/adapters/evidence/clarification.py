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
from e2e_harness.adapters.evidence import impact as impact_ev


def pending_from_state(state: dict, repo_root) -> list[dict]:
    """[{id, question}] still-open questions: acceptance OQ-* plus blocked-impact IQ-*.

    The re-clarify loop must name everything the user has to answer. A blocked impact
    assessment keeps its IQ-* questions in impact-assessment.json (the acceptance
    schema is unchanged); merge them so a single `next` response is actionable.
    """
    out = _acceptance_pending(state, repo_root)
    out.extend(_impact_pending(state, repo_root))
    return out


def _acceptance_pending(state: dict, repo_root) -> list[dict]:
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


def _impact_pending(state: dict, repo_root) -> list[dict]:
    binding = state.get("impact_assessment")
    if not binding or binding.get("status") != "blocked":
        return []
    rel = binding.get("path")
    if not rel:
        return []
    full = Path(rel)
    if not full.is_absolute():
        full = Path(repo_root) / rel   # binding paths are repo-relative
    try:
        obj = json.loads(full.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return impact_ev.open_questions(obj)
