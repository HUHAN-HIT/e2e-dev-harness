"""Event<->state projection for the Phase 4 seam.

`replay_events` is the READ side — events are authoritative, `run-state.json` is
the *output* of replaying them. `derive_events` is the WRITE-side derivation —
the inverse: given the opaque before/after run-state dicts a writer produces, it
recovers the semantic event types `replay_events` dispatches on. Both are
narrow (the smallest useful event set) and pure: no I/O, no mutation.

This module is NOT yet wired into the write path; coupling `derive_events` +
`event_log.append_event` into `run_state.mutate` is a separate, later projection
task. `mutate` only ever sees a post-mutation dict, never an event type, which is
exactly the gap `derive_events` closes.
"""
from __future__ import annotations


def derive_events(before: dict, after: dict) -> list[dict]:
    """Inverse of `replay_events` over a before->after state diff.

    Returns the semantic events that, replayed on top of `before`, reproduce
    `after`'s key fields (run_id, current_phase, per-phase dispatch/blocker).
    Pure and deterministic: emits run.started, then phase.submitted, then per-
    phase gate events in sorted phase order, so a writer that appends these to
    the chained event log produces a stable, reproducible hash chain.

    Only the event types `replay_events` consumes are emitted: run.started,
    phase.submitted, gate.passed/failed, and dispatch.dispatched (Slice 2 — the
    one `dispatch` value `detect_drift` compares). Richer witness events
    (verification.replayed, recovery.*, dispatch metadata) remain out of scope for
    this minimal seam — they have no `detect_drift` consumer.
    """
    run_id = after.get("run_id")
    events: list[dict] = []

    def _tag(event: dict) -> dict:
        # Every event carries run_id when known (design event envelope); replay
        # only reads it for run.started, but a well-formed log needs it on each.
        if run_id is not None:
            event.setdefault("run_id", run_id)
        return event

    # run.started: run_id newly present (None/absent -> set).
    if run_id is not None and not before.get("run_id"):
        events.append(_tag({"type": "run.started", "run_id": run_id}))

    # phase.submitted: current_phase advanced (this is what `evaluate` writes,
    # and what a rework rollback writes when it moves the cursor back).
    after_phase = after.get("current_phase")
    if after_phase and after_phase != before.get("current_phase"):
        events.append(_tag({"type": "phase.submitted", "phase": after_phase}))

    # gate.passed / gate.failed: a phase record's dispatch transitioned. Mirrors
    # `submit_evidence` (done/failed) and rework target marking (failed). Sorted
    # for deterministic event order regardless of dict insertion order.
    before_phases = before.get("phases") or {}
    after_phases = after.get("phases") or {}
    for name in sorted(after_phases):
        rec = after_phases.get(name)
        if not isinstance(rec, dict):
            continue
        prev = before_phases.get(name)
        prev = prev if isinstance(prev, dict) else {}
        prev_dispatch = prev.get("dispatch") if isinstance(prev, dict) else None
        dispatch = rec.get("dispatch")
        if dispatch != prev_dispatch:
            if dispatch == "done":
                events.append(_tag({"type": "gate.passed", "phase": name}))
            elif dispatch == "failed":
                events.append(_tag({"type": "gate.failed", "phase": name,
                                    "reason": rec.get("blocker")}))
            elif dispatch == "dispatched":
                # Slice 2: the `dispatch` verb's state. detect_drift COMPARES the
                # per-phase `dispatch` field, so this value MUST have an event or a
                # dispatched phase reads as false drift. Distinct `type` (not gate.*)
                # keeps the gate vocabulary unoverloaded.
                events.append(_tag({"type": "dispatch.dispatched", "phase": name}))
        prev_keys = sorted((prev.get("evidence") or {}).keys())
        keys = sorted((rec.get("evidence") or {}).keys())
        if keys != prev_keys:
            events.append(_tag({"type": "evidence.keys", "phase": name, "keys": keys}))
    return events


def replay_events(events: list[dict]) -> dict:
    state: dict = {"phases": {}}
    for event in events:
        etype = event.get("type")
        phase = event.get("phase")
        if etype == "run.started":
            state["run_id"] = event.get("run_id")
        elif etype == "phase.submitted" and phase:
            state["current_phase"] = phase
        elif etype == "gate.passed" and phase:
            state.setdefault("phases", {}).setdefault(phase, {})["dispatch"] = "done"
        elif etype == "gate.failed" and phase:
            rec = state.setdefault("phases", {}).setdefault(phase, {})
            rec["dispatch"] = "failed"
            rec["blocker"] = event.get("reason")
        elif etype == "dispatch.dispatched" and phase:
            # Slice 2: inverse of derive's dispatch.dispatched branch.
            state.setdefault("phases", {}).setdefault(phase, {})["dispatch"] = "dispatched"
        elif etype == "evidence.keys" and phase:
            keys = event.get("keys") or []
            if isinstance(keys, list):
                rec = state.setdefault("phases", {}).setdefault(phase, {})
                rec["evidence"] = {str(k): {} for k in keys if isinstance(k, str)}
    return state


def detect_drift(events: list[dict], run_state: dict) -> tuple[bool, str | None]:
    """Cross-witness for the event log against the independently-maintained
    run-state.json projection (design Phase 4: "detect first projection
    mismatch"). Replays `events` and compares the narrow PROJECTABLE fields
    (run_id, current_phase, per-phase dispatch/blocker) against `run_state`;
    run-state legitimately carries more (evidence, contract, timestamps), which is
    not drift.

    Catches a truncate-then-append whose co-located `.head` anchor was rewritten,
    in BOTH directions:
      * CONFLICT — the forged replay claims a field that disagrees with run-state.
      * UNDER-CLAIM — the truncated log simply FALLS BEHIND run-state: the replay
        goes silent on a current_phase/dispatch that run-state still asserts. This
        is the most natural truncation (drop trailing events) and the earlier
        conflict-only witness missed it.
    The under-claim check fires only once the projection has ESTABLISHED the run
    (it carries run_id, current_phase, or a phase): an empty projection asserts
    nothing, so there is nothing for it to have fallen behind on — that is a
    not-yet-recorded log, not a truncated one. `run_id` stays conflict-only: a
    well-formed log derives run.started only when run_id is newly set, which the
    real write path never does (`start` creates the run via save, not mutate — the
    F-2 honest residual), so an omitted run_id must not be read as drift.

    Returns (False, "drift:<field>") at the FIRST divergence in a deterministic
    order (run_id, current_phase, then phases in sorted name order), else
    (True, None).
    """
    projected = replay_events(events)
    established = bool(
        projected.get("run_id") or projected.get("current_phase")
        or projected.get("phases")
    )
    if "run_id" in projected and projected["run_id"] != run_state.get("run_id"):
        return False, "drift:run_id"
    proj_cp = projected.get("current_phase")
    real_cp = run_state.get("current_phase")
    if proj_cp is not None and proj_cp != real_cp:
        return False, "drift:current_phase"
    if established and proj_cp is None and real_cp is not None:
        return False, "drift:current_phase"
    proj_phases = projected.get("phases", {})
    real_phases = run_state.get("phases") or {}
    # Union of phase names so a phase run-state carries but the truncated projection
    # DROPPED is caught (under-claim), not just a conflicting phase still claimed.
    names = set(proj_phases) | (set(real_phases) if established else set())
    for name in sorted(names):
        proj_rec = proj_phases.get(name) or {}
        real_rec = real_phases.get(name)
        real_rec = real_rec if isinstance(real_rec, dict) else {}
        for field in ("dispatch", "blocker"):
            if field in proj_rec and proj_rec[field] != real_rec.get(field):
                return False, f"drift:phases.{name}.{field}"
            if established and field in real_rec and field not in proj_rec:
                return False, f"drift:phases.{name}.{field}"
        if "evidence" in proj_rec:
            proj_keys = set((proj_rec.get("evidence") or {}).keys())
            real_keys = set((real_rec.get("evidence") or {}).keys())
            if proj_keys != real_keys:
                return False, f"drift:phases.{name}.evidence_keys"
    return True, None
