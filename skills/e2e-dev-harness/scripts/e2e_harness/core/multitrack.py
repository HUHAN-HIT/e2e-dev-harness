"""Multi-track spine expansion (取向②, fix B2).

A monolithic feature spine runs one RED -> IMPLEMENTED -> REVIEWED for the whole
request. For a multi-module plan that collapses N functional modules into a
single track. `expand` instead gives **each module its own dev lifecycle**,
chained in dependency (topological) order, with the singleton phases
(CREATED/CLARIFIED/PLANNED before, VERIFIED after) framing the band:

    PLANNED -> RED#auth -> IMPLEMENTED#auth -> REVIEWED#auth
            -> RED#billing -> IMPLEMENTED#billing -> REVIEWED#billing -> VERIFIED

Evidence keys are namespaced per module (`passing_tests#auth`) so each module's
gate is judged on its own artifacts. A <2-module plan is the existing single
track (returned unchanged) — simple runs pay nothing. Pure: no I/O.

The expansion is a topologically *flattened* schedule: the engine still advances
one phase per `next`, and depends_on is honoured by ordering. Genuine parallel
execution of independent modules is layered on top by the agent-team
module-fanout (B3), which is the architecture's designated parallelism seam.
"""
from __future__ import annotations

from dataclasses import replace

from e2e_harness.core import module_plan
from e2e_harness.core.lifecycle import Phase

# The per-module development band — phases that belong to one module's lifecycle.
# CREATED/CLARIFIED/PLANNED/VERIFIED are whole-run singletons and never split.
MODULE_SCOPED = ("RED", "IMPLEMENTED", "REVIEWED")

_SEP = "#"


def base_phase_name(name: str) -> str:
    """'IMPLEMENTED#auth' -> 'IMPLEMENTED'; 'VERIFIED' -> 'VERIFIED'."""
    return name.split(_SEP, 1)[0]


def module_of(name: str) -> str | None:
    """'IMPLEMENTED#auth' -> 'auth'; 'VERIFIED' -> None."""
    return name.split(_SEP, 1)[1] if _SEP in name else None


def base_key(key: str) -> str:
    """'passing_tests#auth' -> 'passing_tests'; 'passing_tests' -> 'passing_tests'."""
    return key.split(_SEP, 1)[0]


def _namespaced_phase(phase: Phase, mid: str) -> Phase:
    ns = lambda keys: tuple(f"{k}{_SEP}{mid}" for k in keys)
    return Phase(
        name=f"{phase.name}{_SEP}{mid}",
        worker_role=phase.worker_role,
        worker_skill=phase.worker_skill,
        produces=ns(phase.produces),
        exit_gate=ns(phase.exit_gate),
        next_phase=None,  # set during rechain
        allows_code_write=phase.allows_code_write,
    )


def expand(base_spine: list[Phase], mplan: dict) -> list[Phase]:
    """Return a spine with the module-scoped band split per module (topo order).

    Unchanged base spine when the plan has fewer than two modules or the spine
    has no module-scoped phases.
    """
    modules = module_plan.topological_order(mplan)
    if len(modules) < 2:
        return list(base_spine)
    idxs = [i for i, p in enumerate(base_spine) if p.name in MODULE_SCOPED]
    if not idxs:
        return list(base_spine)
    start, end = idxs[0], idxs[-1] + 1
    band = base_spine[start:end]
    prefix = base_spine[:start]
    suffix = base_spine[end:]

    blocks: list[Phase] = []
    for mid in modules:
        for phase in band:
            blocks.append(_namespaced_phase(phase, mid))

    merged = list(prefix) + blocks + list(suffix)
    rechained: list[Phase] = []
    for i, phase in enumerate(merged):
        nxt = merged[i + 1].name if i + 1 < len(merged) else None
        rechained.append(replace(phase, next_phase=nxt))
    return rechained


def ready_frontier(spine: list[Phase], state: dict, mplan: dict) -> list[Phase]:
    """Module-phase instances ready to dispatch *in parallel* (the B3 mechanism).

    A module's chain may begin once every module it depends_on is fully complete;
    within a startable but incomplete module the frontier entry is its first
    unsatisfied phase. Independent modules therefore surface together — even at
    different base phases — which is exactly the set an agent-team can fan out
    concurrently while still honouring the dependency graph.

    'satisfied' == every exit_gate key of the phase is present in run-state
    evidence: the same schedulability signal the engine advances on (cheap, no
    repo I/O — full artifact validation stays the gate's job).
    """
    def _evidence(name: str) -> dict:
        return state.get("phases", {}).get(name, {}).get("evidence", {})

    def _satisfied(phase: Phase) -> bool:
        return all(key in _evidence(phase.name) for key in phase.exit_gate)

    chains: dict[str, list[Phase]] = {}
    order: list[str] = []
    for phase in spine:
        mid = module_of(phase.name)
        if mid is None:
            continue
        if mid not in chains:
            chains[mid] = []
            order.append(mid)
        chains[mid].append(phase)

    deps = {m["id"]: set(m.get("depends_on", []))
            for m in mplan.get("modules", []) if isinstance(m, dict) and "id" in m}

    def _module_complete(mid: str) -> bool:
        return all(_satisfied(p) for p in chains.get(mid, []))

    frontier: list[Phase] = []
    for mid in order:
        if _module_complete(mid):
            continue
        if not all(_module_complete(dep) for dep in deps.get(mid, set())):
            continue  # a dependency isn't done yet -> this module can't start
        nxt = next((p for p in chains[mid] if not _satisfied(p)), None)
        if nxt is not None:
            frontier.append(nxt)
    return frontier


# --- First-class tracks (方案 B): ledger materialization + projection ----------
# These are pure: (spine, plan) -> data. The engine fills cursors from evidence;
# these helpers never touch the repo.

BAND_RANK = {"RED": 0, "IMPLEMENTED": 1, "REVIEWED": 2}


def module_chains(spine: list[Phase]) -> dict[str, list[Phase]]:
    """mid -> its ordered sub-spine of module-scoped phases, in spine (topo) order.
    Non-module (singleton) phases are ignored."""
    chains: dict[str, list[Phase]] = {}
    order: list[str] = []
    for phase in spine:
        mid = module_of(phase.name)
        if mid is None:
            continue
        if mid not in chains:
            chains[mid] = []
            order.append(mid)
        chains[mid].append(phase)
    return {mid: chains[mid] for mid in order}


def fork_tracks(spine: list[Phase], mplan: dict | None = None) -> dict:
    """Materialize the per-module track ledger at fork time. Each track carries
    its module id, its first phase as the initial cursor, a 'pending' dispatch,
    its declared depends_on, and complete=False. Track order follows the expanded
    spine (already topological).

    `mplan` supplies the real depends_on edges. When it is absent the band
    serializes (module i depends on module i-1), reproducing the legacy flattened
    walk so plan-less callers are unchanged.
    """
    chains = module_chains(spine)
    mids = list(chains)
    if mplan is not None:
        deps = {m["id"]: list(m.get("depends_on", []))
                for m in mplan.get("modules", []) if isinstance(m, dict) and "id" in m}
    else:
        deps = {mid: ([mids[i - 1]] if i > 0 else []) for i, mid in enumerate(mids)}
    tracks: dict = {}
    for mid in mids:
        tracks[mid] = {
            "module_id": mid,
            "current_phase": chains[mid][0].name,
            "dispatch": "pending",
            "depends_on": deps.get(mid, []),
            "complete": False,
        }
    return tracks


def active_track_ids(tracks: dict) -> list[str]:
    """Track ids that may run now: not complete and every depends_on track
    complete. Preserves the tracks-dict (topological) order."""
    done = {mid for mid, t in tracks.items() if t.get("complete")}
    out: list[str] = []
    for mid, t in tracks.items():
        if t.get("complete"):
            continue
        if all(dep in done for dep in t.get("depends_on", [])):
            out.append(mid)
    return out


def project_leading_phase(tracks: dict, region: str, singleton_phase: str | None) -> str | None:
    """Derived `current_phase` (the back-compat 'leading cursor').

    prologue/epilogue -> the singleton phase name. module_band -> the namespaced
    cursor of the least-advanced *active* track (fewest phases passed); ties broken
    by track (topological) order. When no track is active but some are incomplete,
    the least-advanced incomplete track leads. Deterministic — pure function of the
    ledger.
    """
    if region != "module_band":
        return singleton_phase
    pool = active_track_ids(tracks) or [mid for mid, t in tracks.items() if not t.get("complete")]
    if not pool:
        return singleton_phase
    order = list(tracks)

    def _key(mid: str):
        rank = BAND_RANK.get(base_phase_name(tracks[mid]["current_phase"]), 99)
        return (rank, order.index(mid))

    return tracks[min(pool, key=_key)]["current_phase"]
