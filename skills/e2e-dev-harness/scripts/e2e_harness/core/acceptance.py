"""Acceptance contract — machine-checkable acceptance criteria (link ①).

The CLARIFIED phase must emit a structured contract, not prose checkboxes, so
downstream tests and gates can reference each criterion by a stable id. This
module is pure: it validates the contract structure and exposes its ids.

Contract shape:

    {
      "schema": "e2e-dev-harness.acceptance-contract.v1",
      "items": [
        {"id": "AC-001", "criterion": "<human criterion>",
         "observable_behavior": "<what a passing test would observe>"}
      ]
    }
"""
from __future__ import annotations

import re

SCHEMA = "e2e-dev-harness.acceptance-contract.v1"
_ID = re.compile(r"^AC-\d{3,}$")
_OQ_ID = re.compile(r"^OQ-\d{3,}$")
_OQ_STATUS = frozenset({"open", "resolved", "deferred"})


def _nonempty_str(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _validate_open_questions(items) -> str | None:
    """Structure check for the optional open_questions ledger (link ①, fix A1).

    Absent ledger == no open questions (back-compat). When present it must be a
    list of {id, question, status} where a resolved/deferred entry also carries a
    non-empty resolution. Returns the first defect code or None.
    """
    if not isinstance(items, list):
        return "bad-open-questions"
    seen: set[str] = set()
    for q in items:
        if not isinstance(q, dict):
            return "bad-open-question"
        ident = q.get("id")
        if not isinstance(ident, str) or not _OQ_ID.match(ident):
            return f"bad-oq-id:{ident!r}"
        if ident in seen:
            return f"duplicate-oq-id:{ident}"
        seen.add(ident)
        if not _nonempty_str(q.get("question")):
            return f"empty-oq-question:{ident}"
        status = q.get("status")
        if status not in _OQ_STATUS:
            return f"bad-oq-status:{ident}"
        if status in ("resolved", "deferred") and not _nonempty_str(q.get("resolution")):
            return f"missing-oq-resolution:{ident}"
    return None


def validate_contract(obj) -> tuple[bool, str | None]:
    """Return (ok, reason). reason is a stable code naming the first defect."""
    if not isinstance(obj, dict):
        return False, "not-object"
    if obj.get("schema") != SCHEMA:
        return False, "bad-schema"
    items = obj.get("items")
    if not isinstance(items, list) or not items:
        return False, "no-items"
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            return False, "bad-item"
        ident = item.get("id")
        if not isinstance(ident, str) or not _ID.match(ident):
            return False, f"bad-id:{ident!r}"
        if ident in seen:
            return False, f"duplicate-id:{ident}"
        seen.add(ident)
        if not _nonempty_str(item.get("criterion")):
            return False, f"empty-criterion:{ident}"
        if not _nonempty_str(item.get("observable_behavior")):
            return False, f"empty-observable:{ident}"
    if "open_questions" in obj:
        defect = _validate_open_questions(obj["open_questions"])
        if defect is not None:
            return False, defect
    return True, None


def ids(obj) -> list[str]:
    """Acceptance ids in declared order (no validation; call after validate)."""
    return [item["id"] for item in obj.get("items", []) if isinstance(item, dict) and "id" in item]


def unresolved_questions(obj) -> list[str]:
    """Open-question ids still in status 'open', in declared order.

    Pure gate signal for the CLARIFIED phase (fix A2): a non-empty result means
    clarification is not complete. Absent/empty ledger -> [] (nothing unresolved).
    """
    questions = obj.get("open_questions") if isinstance(obj, dict) else None
    if not isinstance(questions, list):
        return []
    return [q["id"] for q in questions
            if isinstance(q, dict) and q.get("status") == "open" and isinstance(q.get("id"), str)]


def pending_questions(obj) -> list[dict]:
    """[{id, question}] for every still-open question, in declared order.

    Human-facing companion to unresolved_questions (fix A3): the coordinator
    shows these so the re-clarify loop names exactly what the user must answer.
    """
    questions = obj.get("open_questions") if isinstance(obj, dict) else None
    if not isinstance(questions, list):
        return []
    out: list[dict] = []
    for q in questions:
        if isinstance(q, dict) and q.get("status") == "open" and isinstance(q.get("id"), str):
            out.append({"id": q["id"], "question": q.get("question", "")})
    return out
