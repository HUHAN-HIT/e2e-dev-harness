"""Derived whole-journey navigation map (no hand-maintained state)."""
from __future__ import annotations

from e2e_harness.core import gates, dispatch, multitrack
from e2e_harness.core.lifecycle import Phase, catalog

GOAL = "VERIFIED"


def _track_lanes(spine: list[Phase], state: dict, repo_root, *, skip_replay: bool) -> list[dict]:
    """One lane per track: its module phases (status + gate), progress, dispatch,
    and which depends_on tracks still block it. Empty outside a module band."""
    tracks = state.get("tracks")
    if not tracks:
        return []
    chains = multitrack.module_chains(spine)
    done = {mid for mid, t in tracks.items() if t.get("complete")}
    lanes: list[dict] = []
    for mid, track in tracks.items():
        chain = chains.get(mid, [])
        lane_phases = []
        passed = 0
        for phase in chain:
            rec = state.get("phases", {}).get(phase.name, {})
            ok, missing = gates.gate_passes(phase, rec, repo_root, skip_replay=skip_replay)
            if ok:
                passed += 1
                status = "done"
            elif rec.get("dispatch") == dispatch.DispatchStatus.FAILED.value:
                status = "blocked"
            elif phase.name == track.get("current_phase"):
                status = "current"
            else:
                status = "pending"
            lane_phases.append({
                "name": phase.name, "status": status,
                "gate": {"required": len(phase.exit_gate), "missing": missing, "ok": ok},
            })
        lanes.append({
            "module_id": mid,
            "phases": lane_phases,
            "progress": f"{passed}/{len(chain)}",
            "dispatch": track.get("dispatch", "pending"),
            "blocked_by_deps": [d for d in track.get("depends_on", []) if d not in done],
        })
    return lanes


def _phase_status(spine: list[Phase], state: dict, idx: int,
                  repo_root=None, *, skip_replay: bool = True) -> str:
    names = [p.name for p in spine]
    cur = state.get("current_phase", spine[0].name)
    cur_idx = names.index(cur) if cur in names else 0
    phase = spine[idx]
    rec = state.get("phases", {}).get(phase.name, {})
    if idx < cur_idx:
        return "done"
    if idx == cur_idx:
        ok, _ = gates.gate_passes(phase, rec, repo_root, skip_replay=skip_replay)
        if phase.next_phase is None and ok:
            return "done"
        if rec.get("dispatch") == dispatch.DispatchStatus.FAILED.value:
            return "blocked"
        return "current"
    return "pending"


def navigation_map(spine: list[Phase], state: dict, repo_root=None,
                   *, skip_replay: bool = True) -> dict:
    names = [p.name for p in spine]
    cur = state.get("current_phase", spine[0].name)
    cur_idx = names.index(cur) if cur in names else 0

    phases = []
    for i, p in enumerate(spine):
        rec = state.get("phases", {}).get(p.name, {})
        ok, missing = gates.gate_passes(p, rec, repo_root, skip_replay=skip_replay)
        phases.append({
            "name": p.name,
            "status": _phase_status(spine, state, i, repo_root, skip_replay=skip_replay),
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
        "schema": "e2e-dev-harness.navigation-map.v1",
        "goal": GOAL,
        "region": state.get("region", "prologue"),
        "you_are_here": cur,
        "tracks": _track_lanes(spine, state, repo_root, skip_replay=skip_replay),
        "phases": phases,
        "full_catalog": full,
        "progress": f"{done}/{len(spine)}",
        "remaining_gates": remaining_gates,
        "next": nxt,
    }
