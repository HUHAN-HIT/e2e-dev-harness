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


def _nonempty_str(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


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
    return True, None


def ids(obj) -> list[str]:
    """Acceptance ids in declared order (no validation; call after validate)."""
    return [item["id"] for item in obj.get("items", []) if isinstance(item, dict) and "id" in item]
