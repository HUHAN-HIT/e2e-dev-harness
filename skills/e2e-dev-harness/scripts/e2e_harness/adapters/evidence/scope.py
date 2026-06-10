"""VERIFIED-phase scope manifest validation + run-state delivery labelling (②).

Grounding: a delivered *table* claim is only counted if the repo actually
contains a `CREATE TABLE <name>` (the cheapest, highest-signal anti-overclaim
check — jeepay claimed delivery with zero DDL). Services/phases are taken as
declared (git-level grounding is out of scope here). A manifest that declares
COMPLETE while the grounded delivery is a subset is rejected, forcing an honest
PARTIAL; a truthful PARTIAL passes and is recorded on the run-state.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from e2e_harness.core import scope as scope_core


def _all_sql_text(repo_root) -> str:
    chunks = []
    for path in Path(repo_root).rglob("*.sql"):
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(chunks).lower()


def _ddl_present(name: str, sql_lower: str) -> bool:
    pattern = r"create\s+table\s+(?:if\s+not\s+exists\s+)?[`\"']?" + re.escape(name.lower()) + r"\b"
    return re.search(pattern, sql_lower) is not None


def _ground(delivered: dict, repo_root) -> dict:
    grounded = dict(delivered)
    tables = delivered.get("tables") or []
    if tables:
        sql = _all_sql_text(repo_root)
        grounded["tables"] = [t for t in tables if _ddl_present(t, sql)]
    return grounded


def _first_undelivered(undelivered: dict) -> str:
    for cat in scope_core.CATEGORIES:
        if undelivered.get(cat):
            return f"{cat}:{undelivered[cat][0]}"
    return "?"


def _effective(obj, repo_root) -> tuple[str, dict]:
    grounded = _ground(obj.get("delivered", {}), repo_root)
    return scope_core.assess(obj.get("expected", {}), grounded)


def validate_scope_manifest(obj, repo_root) -> tuple[bool, str | None]:
    ok, reason = scope_core.validate_manifest(obj)
    if not ok:
        return False, reason
    status, undelivered = _effective(obj, repo_root)
    if status == "PARTIAL" and obj.get("status") != "PARTIAL":
        # claims COMPLETE (or omits status) on a grounded subset
        return False, f"overclaims-complete:{_first_undelivered(undelivered)}"
    return True, None


def label_delivery(state: dict, repo_root) -> tuple[str | None, dict]:
    """Read the VERIFIED scope manifest and return the grounded (status, undelivered)
    so the caller can record it on the run-state. (None, {}) if no manifest."""
    entry = (state.get("phases", {}).get("VERIFIED", {})
             .get("evidence", {}).get("scope_manifest"))
    if not entry:
        return None, {}
    rel = entry["path"] if isinstance(entry, dict) else entry
    full = Path(rel)
    if not full.is_absolute():
        full = Path(repo_root) / rel
    try:
        obj = json.loads(full.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, {}
    return _effective(obj, repo_root)
