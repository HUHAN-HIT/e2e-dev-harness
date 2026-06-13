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


def _services_of_completed(mplan, completed: set[str]) -> set[str]:
    """Union of `scope.services` declared by the modules whose chain completed —
    the trusted ground truth for a delivered-service claim."""
    out: set[str] = set()
    mods = (mplan.get("modules") or []) if isinstance(mplan, dict) else []
    for m in mods:
        if isinstance(m, dict) and m.get("id") in completed:
            for s in (m.get("scope") or {}).get("services") or []:
                if isinstance(s, str):
                    out.add(s)
    return out


def _ground_with_state(obj, repo_root, state: dict) -> tuple[str, dict]:
    """Grounding when the trusted run-state is available (F-4 gate-time + Task-2
    completion-time, unified). On top of the tables DDL check, ground delivered
    `phases` (module ids) against the modules whose `REVIEWED#<id>` chain completed,
    and `services` against those completed modules' declared `scope.services`. A
    safe no-op for runs with no module plan (no module chains), so singleton runs
    are grounded exactly as the legacy tables-only path."""
    # Local imports avoid an engine<->adapters import cycle (mirrors engine.py).
    from e2e_harness import pipeline
    from e2e_harness.core import multitrack

    spine = pipeline.spine_for_state(state, repo_root)
    delivered = dict(obj.get("delivered", {}))
    if multitrack.module_chains(spine):  # multi-module run: phases ARE module ids
        completed = multitrack.completed_modules(spine, state)
        phases = delivered.get("phases") or []
        if phases:
            delivered["phases"] = [p for p in phases if p in completed]
        services = delivered.get("services") or []
        if services:
            mplan = pipeline._module_plan_from_state(state, repo_root)
            declared = _services_of_completed(mplan, completed)
            delivered["services"] = [s for s in services if s in declared]
    return scope_core.assess(obj.get("expected", {}), _ground(delivered, repo_root))


def validate_scope_manifest(obj, repo_root, state: dict | None = None) -> tuple[bool, str | None]:
    """VERIFIED scope-manifest gate. With `state` threaded in (F-4), `phases` and
    `services` are grounded against the trusted run-state's completed modules, so a
    phases/services overclaim is rejected AT THE GATE — not merely downgraded at
    completion. With `state=None` (every legacy caller, e.g. navigation display)
    the validator stays tables-only, a documented but now-narrowed weakening."""
    ok, reason = scope_core.validate_manifest(obj)
    if not ok:
        return False, reason
    status, undelivered = (_ground_with_state(obj, repo_root, state)
                           if state is not None else _effective(obj, repo_root))
    if status == "PARTIAL" and obj.get("status") != "PARTIAL":
        # claims COMPLETE (or omits status) on a grounded subset
        return False, f"overclaims-complete:{_first_undelivered(undelivered)}"
    return True, None


def label_delivery(state: dict, repo_root) -> tuple[str | None, dict]:
    """Read the VERIFIED scope manifest and return the grounded (status, undelivered)
    so the caller can record it on the run-state. (None, {}) if no manifest.

    Delegates to `_ground_with_state`, so completion-time labelling uses the SAME
    phases + services + tables grounding as the gate now does — keeping the recorded
    delivery verdict consistent with what the gate accepted."""
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
    return _ground_with_state(obj, repo_root, state)
