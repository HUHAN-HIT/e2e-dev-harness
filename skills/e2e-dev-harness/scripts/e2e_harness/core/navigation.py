"""Derived whole-journey navigation map (no hand-maintained state)."""
from __future__ import annotations

from harness_v2.core import gates, dispatch
from harness_v2.core.lifecycle import Phase, catalog

GOAL = "VERIFIED"


def _phase_status(spine: list[Phase], state: dict, idx: int, repo_root=None) -> str:
    names = [p.name for p in spine]
    cur = state.get("current_phase", spine[0].name)
    cur_idx = names.index(cur) if cur in names else 0
    phase = spine[idx]
    rec = state.get("phases", {}).get(phase.name, {})
    if idx < cur_idx:
        return "done"
    if idx == cur_idx:
        ok, _ = gates.gate_passes(phase, rec, repo_root)
        if phase.next_phase is None and ok:
            return "done"
        if rec.get("dispatch") == dispatch.DispatchStatus.FAILED.value:
            return "blocked"
        return "current"
    return "pending"


def navigation_map(spine: list[Phase], state: dict, repo_root=None) -> dict:
    names = [p.name for p in spine]
    cur = state.get("current_phase", spine[0].name)
    cur_idx = names.index(cur) if cur in names else 0

    phases = []
    for i, p in enumerate(spine):
        rec = state.get("phases", {}).get(p.name, {})
        ok, missing = gates.gate_passes(p, rec, repo_root)
        phases.append({
            "name": p.name,
            "status": _phase_status(spine, state, i, repo_root),
            "gate": {"required": len(p.exit_gate), "missing": missing, "ok": ok},
        })

    active = {p.name for p in spine}
    full = []
    for name in catalog():
        if name in active:
            st = next(x["status"] for x in phases if x["name"] == name)
        else:
            st = "skipped"
        full.append({"name": name, "status": st})

    done = sum(1 for p in phases if p["status"] == "done")
    remaining_gates = sum(len(p["gate"]["missing"]) for i, p in enumerate(phases) if i >= cur_idx)

    complete = done == len(spine)
    nxt = None
    if not complete:
        cur_phase = spine[cur_idx]
        nxt = {"phase": cur_phase.name, "action": f"dispatch {cur_phase.worker_skill}"}

    return {
        "schema": "e2e-dev-harness-v2.navigation-map.v1",
        "goal": GOAL,
        "you_are_here": cur,
        "phases": phases,
        "full_catalog": full,
        "progress": f"{done}/{len(spine)}",
        "remaining_gates": remaining_gates,
        "next": nxt,
    }
