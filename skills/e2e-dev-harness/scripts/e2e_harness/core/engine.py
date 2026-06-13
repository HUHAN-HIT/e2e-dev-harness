"""Engine: terminating advance (I1) + evidence submission."""
from __future__ import annotations

from pathlib import Path

from e2e_harness.adapters.evidence import hashing
from e2e_harness.core import gates, dispatch, multitrack
from e2e_harness.core.lifecycle import Phase


def _phase_record(state: dict, name: str) -> dict:
    return state.setdefault("phases", {}).setdefault(name, {})


def submit_evidence(state: dict, phase_name: str, key: str, path: str, *,
                    repo_root=None, status: str = "done", reason: str | None = None,
                    exit_gate: tuple[str, ...] | None = None,
                    worker_id: str | None = None) -> None:
    # OWN1 namespace ownership guard (defense-in-depth, NOT an authorization
    # boundary): for module-scoped phases the phase, evidence key and (when supplied)
    # worker id must agree on the `#module` namespace, so an `IMPLEMENTED#auth` worker
    # cannot satisfy `IMPLEMENTED#billing`. worker_id is self-supplied today, so this
    # only stops accidental mislabeling; a trusted binding needs dispatch-time
    # producer_ids (a later task). Singleton phases (no `#`) are unaffected.
    phase_module = multitrack.module_of(phase_name)
    key_module = multitrack.module_of(key) if key else None
    worker_module = multitrack.module_of(worker_id) if worker_id else None
    if phase_module and key_module and phase_module != key_module:
        raise ValueError("phase-key-module-mismatch")
    if phase_module and worker_module and phase_module != worker_module:
        raise ValueError("worker-module-mismatch")
    rec = _phase_record(state, phase_name)
    if status == "failed":
        # Per-key failure ledger (S1/S2): a failed key is recorded under its own
        # name (or "_phase" for a whole-phase failure) so a *different* reviewer's
        # later `done` cannot erase this failure signal. dispatch/blocker are still
        # set for v1 back-compat (rework routing + the `failed` result flag).
        rec.setdefault("failures", {})[key or "_phase"] = reason or ""
        rec["dispatch"] = dispatch.DispatchStatus.FAILED.value
        if reason:
            rec["blocker"] = reason
        return
    entry: dict = {"path": path}
    if repo_root is not None and path:
        candidate = Path(path)
        full = candidate if candidate.is_absolute() else Path(repo_root) / candidate
        if full.is_file():
            entry["sha256"] = hashing.sha256_file(full)
            entry["bytes"] = full.stat().st_size
    rec.setdefault("evidence", {})[key] = entry
    rec["dispatch"] = dispatch.DispatchStatus.DONE.value
    rec.pop("blocker", None)
    # Clear THIS key's failure (genuine rework) plus any whole-phase failure that a
    # successful re-drive resolves; other keys' failures stay intact (S1).
    failures = rec.get("failures")
    if failures:
        failures.pop(key, None)
        failures.pop("_phase", None)
        if not failures:
            rec.pop("failures", None)
    # F3: a successful re-drive resolves a prior verification rollback — clear the
    # rework bookkeeping so a later reader cannot mistake this converged phase for one
    # still awaiting rework. Cleared on the first keyed done; the gate still governs
    # whether the phase is actually complete.
    rec.pop("superseded_evidence", None)
    rec.pop("rework_required", None)
    # F2 (Hybrid contract model): once this submit completes the phase gate, stamp
    # the contract in force at pass time so a later tightening cannot retroactively
    # invalidate this phase. Idempotent (never overwrites an existing stamp). Absent
    # exit_gate => no stamp, so every legacy positional caller is byte-identical.
    if exit_gate and "contract" not in rec:
        if all(k in rec.get("evidence", {}) for k in exit_gate):
            rec["contract"] = {"exit_gate": list(exit_gate)}


def _by_name(spine: list[Phase]) -> dict[str, Phase]:
    return {p.name: p for p in spine}


def _rework_target(spine: list[Phase], failed_phase: str) -> Phase | None:
    names = [p.name for p in spine]
    if failed_phase not in names:
        return None
    failed_idx = names.index(failed_phase)
    for phase in reversed(spine[:failed_idx]):
        if phase.allows_code_write:
            return phase
    if failed_idx > 0:
        return spine[failed_idx - 1]
    return None


def _all_gate_evidence_submitted(phase: Phase, rec: dict) -> bool:
    evidence = rec.get("evidence", {})
    return bool(phase.exit_gate) and all(key in evidence for key in phase.exit_gate)


def _verification_rework_needed(phase: Phase, rec: dict, missing: list[str]) -> bool:
    if phase.name != "VERIFIED" or not missing:
        return False
    if rec.get("dispatch") == dispatch.DispatchStatus.FAILED.value:
        return True
    return _all_gate_evidence_submitted(phase, rec)


def _route_verification_rework(
    spine: list[Phase],
    state: dict,
    source: Phase,
    missing: list[str],
    reason: str,
) -> dict | None:
    target = _rework_target(spine, source.name)
    if target is None:
        return None
    target_rec = _phase_record(state, target.name)
    existing = target_rec.get("evidence", {})
    if existing:
        target_rec["superseded_evidence"] = dict(existing)
    target_rec["evidence"] = {}
    target_rec["dispatch"] = dispatch.DispatchStatus.FAILED.value
    target_rec["blocker"] = reason
    target_rec["rework_required"] = {
        "from_phase": source.name,
        "missing_evidence": list(missing),
        "reason": reason,
    }
    state["current_phase"] = target.name
    return {
        "complete": False,
        "blocked_phase": target.name,
        "missing_evidence": ["rework_required"],
        "next_action": dispatch.worker_packet(target, state.get("_run_state_path", "")),
        "rework_required": True,
        "rework_from_phase": source.name,
        "verification_missing_evidence": list(missing),
        "blocker": reason,
    }


def _region_of(state: dict) -> str:
    """Current fork-join region. Defaults to 'prologue' so legacy/single-track
    runs (which never set `region`) behave exactly as before."""
    return state.get("region", "prologue")


def evaluate(spine: list[Phase], state: dict, repo_root=None) -> dict:
    """Region-aware terminating advance. prologue/epilogue use the single-cursor
    walk; module_band advances each independent track to its own blocker. Each
    pass advances >=0 phases along a finite spine then blocks or completes."""
    region = _region_of(state)
    if region == "module_band":
        return _evaluate_band(spine, state, repo_root)
    return _evaluate_singleton(spine, state, repo_root)


def _evaluate_singleton(spine: list[Phase], state: dict, repo_root=None) -> dict:
    """Single-cursor walk: advance current_phase past every gate that already
    passes; stop at first blocker or terminal. Used for prologue and epilogue."""
    by_name = _by_name(spine)
    name = state.get("current_phase", spine[0].name)
    while True:
        phase = by_name[name]
        rec = state.get("phases", {}).get(name, {})
        ok, missing = gates.gate_passes(phase, rec, repo_root)
        if not ok:
            if _verification_rework_needed(phase, rec, missing):
                reason = rec.get("blocker") or f"verification gate failed: {', '.join(missing)}"
                if state.get("tracks"):
                    routed = _route_band_verification_rework(spine, state, missing, reason, repo_root)
                else:
                    routed = _route_verification_rework(spine, state, phase, missing, reason)
                if routed is not None:
                    return routed
            state["current_phase"] = name
            result = {
                "complete": False,
                "blocked_phase": name,
                "missing_evidence": missing,
                "next_action": dispatch.worker_packet(phase, state.get("_run_state_path", "")),
            }
            if rec.get("dispatch") == dispatch.DispatchStatus.FAILED.value:
                result["failed"] = True
                result["blocker"] = rec.get("blocker")
            return result
        if phase.next_phase is None:
            # F1: completion is an all-gates invariant, not a cursor terminal.
            # A predecessor whose gate regressed after it passed (e.g. a contract
            # tightened later) must re-block the run rather than ride this terminal
            # cursor to a false complete. Re-check the whole spine and, on a
            # regression, route the cursor back to the EARLIEST still-failing phase
            # (the same backward-cursor idiom the block path below already uses).
            all_ok, blockers = gates.all_gates_pass(spine, state, repo_root)
            if all_ok:
                state["current_phase"] = name
                return {"complete": True, "blocked_phase": None, "missing_evidence": [], "next_action": {}}
            first_name, first_missing = blockers[0]
            state["current_phase"] = first_name
            first_phase = by_name[first_name]
            result = {
                "complete": False,
                "blocked_phase": first_name,
                "missing_evidence": first_missing,
                "next_action": dispatch.worker_packet(first_phase, state.get("_run_state_path", "")),
            }
            first_rec = state.get("phases", {}).get(first_name, {})
            if first_rec.get("dispatch") == dispatch.DispatchStatus.FAILED.value:
                result["failed"] = True
                result["blocker"] = first_rec.get("blocker")
            return result
        nxt = phase.next_phase
        # Fork point: stepping from a singleton phase (e.g. PLANNED) into the
        # module band (a namespaced phase). Materialize tracks once and hand off.
        if multitrack.module_of(nxt) is not None and multitrack.module_of(name) is None:
            state["region"] = "module_band"
            state["tracks"] = multitrack.fork_tracks(spine, _band_module_plan(state, repo_root))
            return _evaluate_band(spine, state, repo_root)
        name = nxt


def _band_module_plan(state: dict, repo_root) -> dict | None:
    """Resolve the run's module plan (for real depends_on edges) without creating
    an import cycle at module load. None -> fork_tracks falls back to linear deps."""
    if repo_root is None:
        return None
    from e2e_harness import pipeline  # local import: pipeline imports multitrack/yaml, not engine
    return pipeline._module_plan_from_state(state, repo_root)


def _module_first_blocker(chain: list[Phase], state: dict, repo_root):
    """First phase in a module chain whose gate does not pass, with its missing
    keys. (None, []) when the whole chain passes (the module is complete)."""
    for phase in chain:
        rec = state.get("phases", {}).get(phase.name, {})
        ok, missing = gates.gate_passes(phase, rec, repo_root)
        if not ok:
            return phase, missing
    return None, []


def _evaluate_band(spine: list[Phase], state: dict, repo_root=None) -> dict:
    """Advance every active track to its own first blocker; surface the whole
    frontier (the per-beat dispatch set) plus a single leading-cursor projection
    for back-compat. Joins to epilogue/VERIFIED when all tracks complete."""
    tracks = state.setdefault("tracks", {})
    chains = multitrack.module_chains(spine)
    # Refresh each track's cursor + complete flag from evidence/gates (the cursor
    # is derived; only dispatch state is genuinely stored per track).
    for mid, chain in chains.items():
        track = tracks.setdefault(mid, {
            "module_id": mid, "current_phase": chain[0].name,
            "dispatch": "pending", "depends_on": [], "complete": False,
        })
        blocker, _missing = _module_first_blocker(chain, state, repo_root)
        if blocker is None:
            track["complete"] = True
            track["current_phase"] = chain[-1].name
        else:
            track["complete"] = False
            track["current_phase"] = blocker.name

    # Join barrier: all tracks complete -> epilogue, then run the VERIFIED gate.
    if tracks and all(t["complete"] for t in tracks.values()):
        state["region"] = "epilogue"
        state["current_phase"] = "VERIFIED"
        return _evaluate_singleton(spine, state, repo_root)

    rsp = state.get("_run_state_path", "")
    frontier: list[dict] = []
    for mid in multitrack.active_track_ids(tracks):
        blocker, missing = _module_first_blocker(chains[mid], state, repo_root)
        rec = state.get("phases", {}).get(blocker.name, {})
        entry = {
            "track": mid,
            "blocked_phase": blocker.name,
            "missing": missing,
            "worker_packet": dispatch.worker_packet(blocker, rsp),
        }
        if rec.get("dispatch") == dispatch.DispatchStatus.FAILED.value:
            entry["failed"] = True
            entry["blocker"] = rec.get("blocker")
        frontier.append(entry)

    lead = multitrack.project_leading_phase(tracks, "module_band", None)
    state["current_phase"] = lead
    lead_entry = next((e for e in frontier if e["blocked_phase"] == lead),
                      frontier[0] if frontier else None)
    result = {
        "complete": False,
        "region": "module_band",
        "tracks_frontier": frontier,
        "blocked_phase": lead,
        "missing_evidence": lead_entry["missing"] if lead_entry else [],
        "next_action": lead_entry["worker_packet"] if lead_entry else {},
    }
    if lead_entry and lead_entry.get("failed"):
        result["failed"] = True
        result["blocker"] = lead_entry.get("blocker")
    return result


def _last_code_write(chain: list[Phase]) -> Phase | None:
    """The rework target inside a module chain — the last phase that may write
    code (IMPLEMENTED#m). None when the chain has no code-write phase."""
    for phase in reversed(chain):
        if phase.allows_code_write:
            return phase
    return None


def _route_band_verification_rework(spine: list[Phase], state: dict, missing: list[str],
                                    reason: str, repo_root) -> dict | None:
    """Verification rework for a multi-track run (design §Per-Track Rework, v1).

    Attributable (a missing key carries a #module suffix) -> reopen only those
    modules; otherwise reopen every track conservatively. Reopening a track resets
    its IMPLEMENTED#m phase (supersede + clear evidence, mark failed) and flips the
    run back to module_band so the band re-drives the affected implementations.
    """
    chains = multitrack.module_chains(spine)
    tracks = state.get("tracks", {})
    attributed = sorted({multitrack.module_of(k) for k in missing
                         if multitrack.module_of(k) is not None})
    targets = attributed or list(tracks)
    reopened: list[str] = []
    for mid in targets:
        target = _last_code_write(chains.get(mid, []))
        if target is None:
            continue
        target_rec = _phase_record(state, target.name)
        existing = target_rec.get("evidence", {})
        if existing:
            target_rec["superseded_evidence"] = dict(existing)
        target_rec["evidence"] = {}
        target_rec["dispatch"] = dispatch.DispatchStatus.FAILED.value
        target_rec["blocker"] = reason
        target_rec["rework_required"] = {
            "from_phase": "VERIFIED",
            "missing_evidence": list(missing),
            "reason": reason,
        }
        tracks[mid]["complete"] = False
        tracks[mid]["dispatch"] = dispatch.DispatchStatus.PENDING.value
        tracks[mid]["current_phase"] = target.name
        reopened.append(mid)
    if not reopened:
        return None
    state["region"] = "module_band"
    result = _evaluate_band(spine, state, repo_root)
    result["rework_required"] = True
    result["rework_from_phase"] = "VERIFIED"
    result["verification_missing_evidence"] = list(missing)
    result["reopened_tracks"] = reopened
    result["blocker"] = reason
    return result
