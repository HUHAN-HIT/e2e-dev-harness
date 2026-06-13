"""Module plan — machine-readable functional-module slicing (link ④, fix B1).

PLANNED turns the clarified requirement into N functional modules so the engine
can run RED->IMPLEMENTED->REVIEWED per module and schedule them in dependency
order (progressive parallel development) instead of one monolithic track.

Contract shape:

    {
      "schema": "e2e-dev-harness.module-plan.v1",
      "modules": [
        {"id": "auth", "name": "Auth service",
         "depends_on": [], "acceptance_ids": ["AC-001"],
         "scope": {"services": ["auth"], "tables": ["users"]}}   # scope optional
      ]
    }

Pure: structure in, (ok, reason) out. Dependency closure and acyclicity are part
of validity — a plan that references a missing or cyclic dependency cannot be
scheduled, so it is rejected here rather than blowing up the engine later.
"""
from __future__ import annotations

import re

SCHEMA = "e2e-dev-harness.module-plan.v1"
_MOD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_AC_ID = re.compile(r"^AC-\d{3,}$")


def _nonempty_str(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _validate_module(mod) -> tuple[str | None, str | None]:
    """Per-module structure. Returns (module_id, defect); defect None == ok."""
    if not isinstance(mod, dict):
        return None, "bad-module"
    mid = mod.get("id")
    if not isinstance(mid, str) or not _MOD_ID.match(mid):
        return None, f"bad-module-id:{mid!r}"
    if not _nonempty_str(mod.get("name")):
        return mid, f"empty-name:{mid}"
    deps = mod.get("depends_on", [])
    if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
        return mid, f"bad-depends-on:{mid}"
    acs = mod.get("acceptance_ids", [])
    if not isinstance(acs, list):
        return mid, f"bad-acceptance-ids:{mid}"
    for aid in acs:
        if not isinstance(aid, str) or not _AC_ID.match(aid):
            return mid, f"bad-acceptance-id:{mid}:{aid!r}"
    # FAN1: optional named shared resources (migrations sequence, lockfile, codegen
    # sink, shared schema). The scheduler withholds fan-out for modules that share
    # one. Each must be a non-empty string.
    groups = mod.get("conflict_groups", [])
    if not isinstance(groups, list) or not all(_nonempty_str(g) for g in groups):
        return mid, f"bad-conflict-groups:{mid}"
    return mid, None


def _first_cycle_node(ids: list[str], deps: dict[str, list[str]]) -> str | None:
    """First declared id that cannot be topologically emitted (== part of a cycle)."""
    emitted: set[str] = set()
    remaining = list(ids)
    while remaining:
        progressed = False
        for mid in list(remaining):
            if all(d in emitted for d in deps[mid]):
                emitted.add(mid)
                remaining.remove(mid)
                progressed = True
                break
        if not progressed:
            return next(m for m in ids if m in remaining)
    return None


def validate_module_plan(obj) -> tuple[bool, str | None]:
    """Return (ok, reason). reason is a stable code naming the first defect."""
    if not isinstance(obj, dict):
        return False, "not-object"
    if obj.get("schema") != SCHEMA:
        return False, "bad-schema"
    modules = obj.get("modules")
    if not isinstance(modules, list) or not modules:
        return False, "no-modules"

    ids: list[str] = []
    seen: set[str] = set()
    deps: dict[str, list[str]] = {}
    for mod in modules:
        mid, defect = _validate_module(mod)
        if defect is not None:
            return False, defect
        if mid in seen:
            return False, f"duplicate-module-id:{mid}"
        seen.add(mid)
        ids.append(mid)
        deps[mid] = list(mod.get("depends_on", []))

    for mid in ids:
        for dep in deps[mid]:
            if dep == mid:
                return False, f"self-dep:{mid}"
            if dep not in seen:
                return False, f"unknown-dep:{mid}->{dep}"

    cyc = _first_cycle_node(ids, deps)
    if cyc is not None:
        return False, f"cycle:{cyc}"
    return True, None


def module_ids(obj) -> list[str]:
    """Module ids in declared order (no validation; call after validate)."""
    return [m["id"] for m in obj.get("modules", []) if isinstance(m, dict) and "id" in m]


def expected_scope(obj) -> dict:
    """Derive the VERIFIED expected scope from the module plan (link ②+④, fix B4).

    services/tables are the union of every module's declared scope; phases are the
    module ids — so the scope-manifest PARTIAL backstop automatically flags any
    module (or its services/tables) that VERIFIED failed to deliver. Pure.
    """
    services: list[str] = []
    tables: list[str] = []
    for mod in obj.get("modules", []):
        if not isinstance(mod, dict):
            continue
        sc = mod.get("scope") or {}
        services.extend(sc.get("services", []) or [])
        tables.extend(sc.get("tables", []) or [])
    return {
        "services": sorted(set(services)),
        "tables": sorted(set(tables)),
        "phases": module_ids(obj),
    }


def topological_order(obj) -> list[str]:
    """Module ids in dependency order; independent modules keep declared order.

    Assumes a validated (acyclic) plan. Stable: re-scans from the declared order
    after each emission so siblings come out as authored, giving a deterministic
    progressive schedule.
    """
    ids = module_ids(obj)
    deps = {m["id"]: list(m.get("depends_on", []))
            for m in obj.get("modules", []) if isinstance(m, dict) and "id" in m}
    emitted: list[str] = []
    emitted_set: set[str] = set()
    remaining = list(ids)
    while remaining:
        for mid in list(remaining):
            if all(d in emitted_set for d in deps.get(mid, [])):
                emitted.append(mid)
                emitted_set.add(mid)
                remaining.remove(mid)
                break
        else:  # no module became ready -> unexpected cycle (validate should catch)
            break
    return emitted
