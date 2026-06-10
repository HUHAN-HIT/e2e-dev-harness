"""Scope manifest — design scope vs delivered scope (link ②).

A tier or worker must not silently shrink a multi-service design into a
skeleton and still call it VERIFIED. The manifest declares the expected scope
and the delivered scope across three categories; assess() reports whether the
delivery is COMPLETE or a PARTIAL subset and exactly what is missing.

Pure: no I/O. Repo grounding (e.g. a declared table really has a CREATE TABLE)
and run-state labelling live in adapters/evidence/scope.py.
"""
from __future__ import annotations

SCHEMA = "e2e-dev-harness.scope-manifest.v1"
CATEGORIES = ("services", "tables", "phases")


def _valid_scope(block) -> str | None:
    if not isinstance(block, dict):
        return "not-dict"
    for cat in CATEGORIES:
        value = block.get(cat)
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            return cat
    return None


def validate_manifest(obj) -> tuple[bool, str | None]:
    if not isinstance(obj, dict):
        return False, "not-object"
    if obj.get("schema") != SCHEMA:
        return False, "bad-schema"
    for role in ("expected", "delivered"):
        bad = _valid_scope(obj.get(role))
        if bad == "not-dict":
            return False, f"bad-{role}"
        if bad is not None:
            return False, f"bad-scope:{role}.{bad}"
    return True, None


def assess(expected: dict, delivered: dict) -> tuple[str, dict]:
    """Return (status, undelivered). status is PARTIAL if any expected scope item
    is missing from delivered, else COMPLETE."""
    undelivered: dict[str, list[str]] = {}
    for cat in CATEGORIES:
        have = set(delivered.get(cat, []) or [])
        undelivered[cat] = [x for x in (expected.get(cat, []) or []) if x not in have]
    status = "COMPLETE" if not any(undelivered.values()) else "PARTIAL"
    return status, undelivered
