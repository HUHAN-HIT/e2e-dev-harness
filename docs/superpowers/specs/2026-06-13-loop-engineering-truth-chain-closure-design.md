# Loop Engineering Truth-Chain Closure (Phase 1) Design

> Status: proposed · 2026-06-13 · scope: **Phase 1 foundation only**
> Family: follows `docs/loop-engineering-control-plane-design.md` (Phase 4 event seam)
> and feeds `docs/superpowers/specs/2026-06-13-loop-engineering-context-checkpoints-design.md`.

## Executive Summary

The append-only event log is **implemented but open-loop**. It is written on the
recovery path only, it is *never read back* by any command, and its event
vocabulary is too narrow to derive anything from. The control plane therefore
trusts the `run-state.json` projection it can neither verify nor reconstruct.

This phase **closes the loop without breaking compatibility**: turn on forward-path
event emission, complete the event vocabulary for the one `dispatch` value the
drift check compares (so emission itself does not read as drift), and make
`doctor --state` cross-check the projection against event truth. `run-state.json`
remains the in-practice authority; the event log is promoted from a dormant seam
to a **tamper-evident witness that the diagnosis surface actually consults**.

This is deliberately the smallest, highest-confidence slice of the larger
"Close the Truth Loop" arc. Phase 2 (coordinator projections) and Phase 3
(context checkpoints) are **out of scope here** and listed only as roadmap — both
have a hard dependency on the verified, vocabulary-complete event truth this
phase delivers.

## Problem Statement

Three facets of one structural defect (verified against the current checkout):

1. **Written half-way.** `events_path` is passed to `run_state.mutate` only by
   `recovery.py:128` (`apply_recovery`). The four forward write paths —
   `dispatch.py:160`, `next.py:32`, `submit.py:62`, `migrate.py:43` — call
   `mutate` without it. A normal run produces **no event chain at all**.
2. **Never read back.** `event_log.verify_chain` (`event_log.py:104`) and
   `state_store.detect_drift` (`state_store.py:90`) have **no command caller** —
   they are referenced only by their own definitions and docstrings.
   `doctor --state` → `state_diagnosis.diagnose_run` reads `run-state.json` and
   never reconciles it against the log. The control-plane design's own Q1
   (`loop-engineering-control-plane-design.md`) self-acknowledges this.
3. **Vocabulary mismatched with the drift check.** `state_store.derive_events`
   (`state_store.py:55-68`) maps the per-phase `dispatch` field's `done`/`failed`
   values to `gate.passed`/`gate.failed`, but **not `dispatched`**
   (`DispatchStatus.DISPATCHED`, `dispatch.py:28`). Yet `detect_drift` *compares*
   that same `dispatch` field (`state_store.py:139-143`). So the moment Slice 1
   turns emission on, a phase sitting at `dispatched` (dispatched, not yet
   submitted) appears in run-state but not in the replayed chain → **false
   `drift:phases.<p>.dispatch`**. (Richer witness events for downstream projections
   — `verification.replayed`, dispatch metadata — are a separate, deferred concern;
   see N6.)

Consequence for loop engineering: a long run is **unauditable** (no projection
sees the truth), **untrusted** (projection drift has no cross-witness), and the
absence of this substrate blocks the context-checkpoint work whose `trust_basis`
must sit on a verified event truth.

## Design Goals

- G1. Every forward state transition appends to the chained event log, inside the
  same lock as the `run-state.json` write, so the two stay consistent under
  concurrency.
- G2. The event vocabulary is symmetrically complete for **every per-phase
  `dispatch` value `detect_drift` compares** — specifically the `dispatched` value,
  which today has no event and would otherwise read as false drift. Richer witness
  events (`verification.replayed`, dispatch metadata) are deferred to their Phase 2
  consumer (N6).
- G3. `doctor --state` verifies chain integrity (`verify_chain`) and projection
  agreement (`detect_drift`) and reports a drift/tamper as a first-class blocking
  fault. The two dead functions become live.
- G4. `run-state.json` byte-semantics for *its own content* are unchanged; the only
  additive artifacts are the sibling `events.jsonl` + `events.jsonl.head`.
- G5. Lifecycle wording is made truthful: `REWORK` and `WAITING_DISPATCH` are
  documented as **projected operational states**, not lifecycle phases (closes the
  claim-6 doc/code drift in the same change set).

## Non-Goals

- N1. **No Option C.** `replay_events` does not become the loader; `run-state.json`
  is not downgraded to a cache. Events stay a *witness*, not yet the *authority*.
- N2. **No coordinator projections** (`agent-schedule.json`,
  `coordinator-summary.json`, timeline) — Phase 2.
- N3. **No context checkpoints** — Phase 3.
- N4. **No new threat-model surface** — no event signatures, no external
  commitment service. The existing forward chain + `.head` anchor + drift
  cross-witness is the ceiling for this phase.
- N5. **No singleton trusted-binding change** (claim 8) — tracked as residual S-B,
  done independently.
- N6. **No richer witness events** beyond the `dispatched` drift-fix.
  `verification.replayed` and dispatch metadata have no Phase 1 consumer
  (`detect_drift` never reads them), and the verification replay fires in the
  read-only gate/navigation path (`gates.gate_passes` ← `navigation`,
  `skip_replay=False`; `submit` does not replay), so where/how to emit it is a
  Phase 2 decision made against the projection that consumes it.

## Current Checkout Facts (the seams we build on)

- `run_state.mutate(path, fn, now=, events_path=)` already projects the
  load→fn→save transition onto the log **inside the lock** when `events_path` is
  given (`run_state.py:101-126`). The seam is wired-but-inert on the forward path.
- `recovery.py` already establishes the artifact convention: sibling
  `events.jsonl` via `_sibling_events_path` (`recovery.py:46-47`), plus explicit
  `append_event(recovery.approved/applied)` around the mutate.
- `detect_drift` already handles the honest `start`-via-`save` residual: a
  well-formed log derives `run.started` only when `run_id` is newly set, which the
  forward path never does, so an absent `run.started` is not read as drift
  (`state_store.py:105-129`).
- `verify_chain` already consults the persisted `.head` sidecar and reports
  `event-chain-truncated` / `event-chain-tip-mismatch` (`event_log.py:104-146`).

The machinery exists. This phase is **wiring + vocabulary + one diagnosis hook**,
not new core algorithms.

## Proposed Architecture

### Slice 0 — Pre-flight (residual S-A): land the working tree

The 10 uncommitted files (the `E2E_HARNESS_AVAILABLE_SUBAGENTS` portability guard
+ `subagent_fallback_reason`) must be committed with a short companion spec before
truth-chain changes stack on top — a clean SSOT baseline, and the guard underpins
the trustworthy fan-out that Phase 2 will audit. Deliverable: commit + a brief
`docs/superpowers/specs/2026-06-13-runtime-subagent-availability-guard-design.md`
recording the env-confirmation contract and the fallback reason. (Mechanical; no
behavior change beyond what is already in the tree.)

### Slice 1 — Forward-path emission, switched at run creation (G1, G4, R5)

Emission is a **per-run property fixed at `start`**, not a per-command decision:

- `start` reads `E2E_HARNESS_DISABLE_EVENTS`. Unset (default) → `start` lays down
  `events.jsonl` with the initial `run.started` event + `.head` anchor. Set to `1`
  → no `events.jsonl` is created and the run is permanently event-free.
- The four forward commands (`dispatch`, `next`, `submit`, `migrate`) emit **iff
  `events.jsonl` already exists** for the run — i.e. pass
  `events_path=run_state.events_path_for(args.state)` when it exists, else `None`.
- Factor the sibling-path helper out of `recovery.py` into
  `run_state.events_path_for(state_path)` (= `<run_dir>/events.jsonl`) so recovery,
  `start`, and the four commands share one convention.

Why fixed-at-`start` (R5): it gives a clean opt-out (CI / perf set the env before
`start`) AND makes the **old-run upgrade** safe — a run created before this phase
has no `events.jsonl`, so forward commands skip emission and never produce a
*partial* chain starting mid-run (which `detect_drift` would read as under-claim
drift). New runs get a chain complete from `run.started`, so the witness covers the
whole run. The log is additive: `run-state.json`'s own bytes are unchanged (G4) —
this consciously relaxes the old "run-state.json is the sole artifact" non-goal,
which *is* Phase 1's purpose. `start` still creates run-state via `save`; it now
*also* seeds the chain, keeping `run.started` honest (emitted exactly when `run_id`
is first set).

### Slice 1.5 — Witness write-failure is loud and attributed (R4)

`run_state.mutate` does `save` then derives+appends events (`run_state.py:121-125`);
the two are **not atomic**. A post-`save` `append_event` failure (disk full,
permission, corruption) leaves run-state advanced but the chain behind, and today
the raw exception propagates out of `mutate` — so the command errors *after* the
authoritative write already committed, and a retry may re-apply `fn` to an
already-advanced state.

Resolution — the witness must never veto the authority, but its failure must be
loud and distinguishable from tampering:

- Wrap the append loop in `try/except`. On failure: **do not roll back `save`**;
  write a best-effort sidecar `events.jsonl.write-failed` =
  `{run_id, expected_sequence, type, reason}`; emit a stderr warning; **swallow**
  the exception so the command reports the success that actually happened.
- The run's witness is now degraded for the rest of its life (the chain stays one
  behind; `detect_drift` would flag it) — acceptable and **reported, not silent**:
  the sentinel names the cause at the next `doctor --state`.
- Chain healing / rebuild-from-run-state is **out of Phase 1 scope** (it approaches
  Option C). If even the sentinel write fails, the warning still surfaces and
  `detect_drift` still catches the lag — the sentinel is attribution, not a
  correctness crutch.

### Slice 2 — Close the `dispatched` drift gap only (G2)

Scope is deliberately narrow: make the chain represent **every `dispatch` value
`detect_drift` compares** — no more. Today that is the missing `dispatched` value
(problem #3). Resolve it by extending `derive_events` **and** `replay_events`
**symmetrically**, preserving the "`derive_events` is the inverse of
`replay_events`" invariant (`state_store.py:18`):

- `derive_events`: when a phase record's `dispatch` transitions to `dispatched`,
  emit `dispatch.dispatched {phase}`. (A module-band `_mark_dispatched` sets several
  phases at once — emit one per phase, sorted, deterministic.)
- `replay_events`: consume `dispatch.dispatched` → set that phase's
  `dispatch="dispatched"`.

Because both sides move together, the state a clean chain replays to still matches
run-state exactly — **no false drift**, and `detect_drift`'s comparison set is
unchanged. `dispatch.dispatched` carries its own `type` (semantically distinct from
`gate.*`), so the gate vocabulary is not overloaded. This is *derived*, not the
annotate/explicit mechanism the original draft floated — simpler, and it is the
only mechanism that keeps derive/replay strict inverses.

Event envelope (already de-facto present, no change): `schema`, `sequence`,
`prev_event_hash`, `event_hash`, `run_id`, `type`, plus `type`-specific fields.

**Explicitly NOT in Slice 2** (N6): `verification.replayed` and any dispatch
*metadata* beyond the bare `dispatched` state. They have no Phase 1 consumer
(`detect_drift` never reads them), and the verification replay fires in the
read-only gate/navigation path (`gates.gate_passes` ← `navigation`,
`skip_replay=False`; `submit` does **not** replay), so "where does a read-only path
emit?" is a Phase 2 decision made against the projection that consumes it.

### Slice 3 — doctor read-back (G3)

`diagnose_run(state, state_path, repo)` gains a **control-plane integrity check**
at the *front* of the fault ladder (a tampered/drifted control plane invalidates
every downstream diagnosis, so it takes precedence over missing-evidence/failed-
gate):

```
events_path = run_state.events_path_for(state_path)
if (events_path.parent / "events.jsonl.write-failed").exists():   # R4: known write failure
    first_fault = {"kind": "event_log_write_failed", "phase": current, ...}
elif events_path.exists():
    ok, why = event_log.verify_chain(events_path)        # tamper / truncation
    if ok:
        ok, why = state_store.detect_drift(event_log.read_events(events_path), state)
    if not ok:
        first_fault = {"kind": "control_plane_drift", "phase": current,
                       "task_id": None, "message": why}   # e.g. "drift:current_phase"
```

- Fault-ladder precedence (highest first): **`event_log_write_failed`** (a sentinel
  records a known append failure — a precise cause) > **`control_plane_drift`**
  (chain tamper / truncation, or projection drift with no recorded cause) > the
  existing missing-evidence / failed-gate faults. A known write failure must not be
  reported as ambiguous "drift."
- Both new kinds set `run_blocked = true`.
- `next_legal_command` for this fault is a **read-only** instruction (re-run
  `doctor --state`, inspect the log) — never an auto-mutating verb. Recovery of a
  drifted plane stays operator-gated.
- Absent log (a run created before this phase, or `start` before first `mutate`)
  is **not** a fault — the check is skipped, matching `detect_drift`'s
  "not-yet-recorded ≠ truncated" rule.
- `doctor` without `--state` is untouched (installer readiness, `doctor.v1`).

### Slice 4 — Lifecycle wording (G5)

In the same change set, make the doc/code agree (claim 6):
- `REWORK` → documented as the `rework_required` + `superseded_evidence` +
  cursor-rollback **side effect**, not a `Phase`/enum.
- `WAITING_DISPATCH` → a **projected operational state** (dispatch guidance ×
  runtime capability × artifact readiness), per `dispatch.py:131` and
  control-plane-design line 172. Reflect this in the `doctor-state.v1` field
  documentation. (Note: claim-6's "blocked_task still null" is already closed by
  F-6 in `state_diagnosis.py:127-132`; nothing to do there.)

## Compatibility & Migration

- Existing runs without `events.jsonl` keep working; the doctor check self-skips.
- New runs gain `events.jsonl` + `events.jsonl.head` siblings; no change to
  `run-state.json` content.
- **Old-run upgrade**: a run created before Phase 1 has no `events.jsonl`; forward
  commands skip emission and `doctor` skips the integrity check — no partial chain,
  no false drift. Emission begins only for runs `start`ed after the upgrade.
- No schema bump to `run-state.v1`. `doctor-state.v1` gains two new
  `first_fault.kind` values (`control_plane_drift`, `event_log_write_failed`) —
  additive, consumers already switch on `kind`.

## Testing Strategy

- **Slice 1**: each forward command, after running, produces a chain whose
  `replay_events` reproduces the run-state projectable fields; `mutate` unit tests
  for with/without `events_path` already exist (`test_run_state.py`) — extend to
  the command layer.
- **Slice 2**: golden vocabulary test — a scripted run emits the expected `type`
  sequence; `verify_chain` passes; unknown types don't trip `detect_drift`.
- **Slice 3**: tamper fixtures — (a) edit a non-tail event → `event-hash-mismatch`;
  (b) truncate + rewrite `.head` → `detect_drift` `drift:*`; both surface as
  `control_plane_drift` from `doctor --state`. Clean run → no drift fault.
- Zero-runtime-dependency property preserved (stdlib only).

## Acceptance Criteria

1. After `dispatch/next/submit/migrate`, a sibling `events.jsonl` exists and its
   replay matches the run-state projectable fields.
2. `verify_chain` and `detect_drift` are invoked by `doctor --state` (no longer
   dead), proven by fixtures:
   - 2a. Edit a non-tail event → `control_plane_drift`, message contains
     `event-hash-mismatch`.
   - 2b. Truncate + rewrite `.head` → `control_plane_drift`, message contains
     `drift:*`.
   - 2c. Simulated `append_event` failure → the command still succeeds, an
     `events.jsonl.write-failed` sentinel is written, and the next `doctor --state`
     reports `event_log_write_failed` (precedence above drift).
3. A phase at `dispatched` produces a `dispatch.dispatched` event and yields **no**
   false drift; `derive_events`/`replay_events` round-trip the `dispatched` value.
4. `run-state.json` content is byte-unchanged vs. pre-change for the same inputs.
5. Working tree is clean (Slice 0 committed); REWORK/WAITING_DISPATCH documented as
   non-phases.

## Risks & Tradeoffs

- **R1 — relaxing the sole-artifact non-goal.** Mitigated: additive sidecar only,
  run-state content untouched; the relaxation is the explicit purpose.
- **R2 — emission cost in the hot path.** Append is O(log length) per mutate (it
  re-reads to chain). For run-scale logs this is negligible; if it ever matters,
  cache the tail in the `.head` anchor (out of scope now).
- **R3 — partial vocabulary.** Phase 2 may discover it needs more event types;
  acceptable — the envelope is extensible and projections ignore unknown types.
- **R4 — witness degradation is not self-healing.** A post-`save` append failure
  degrades a run's chain for its remaining life (reported via the
  `events.jsonl.write-failed` sentinel; chain rebuild is out of scope). The
  authoritative `run-state.json` is unaffected.
- **R7 — log growth.** Phase 1 does no rotation/archival; `events.jsonl` grows
  monotonically within a run. Events are ~100–300 B/line and O(phases × reworks) —
  hundreds of lines, <100 KB at realistic run scale, so unbounded growth is not a
  Phase 1 concern. Rotation / archival / chain-checkpointing is a later phase (it
  interacts with Phase 3 checkpoints).

## Roadmap (explicitly out of this spec)

- **Phase 2 — Coordinator projections (claim 7).** `agent-schedule.json` /
  `coordinator-summary.json` / `timeline` as pure read-only replays of the now-
  verified log; doctor rebuilds rather than trusts on mismatch. **Owns the richer
  witness vocabulary deferred from Slice 2** (`verification.replayed`, dispatch
  metadata) — designed against these concrete consumers, including the decision of
  where a read-only gate/navigation replay may emit.
- **Phase 3 — Context checkpoints (claim 2).** Land the 2026-06-13 checkpoint
  design; `trust_basis` sits on Phase 1's verified event truth + Phase 2 projections.
  This is the actual fix for "loops get more dangerous as they deepen."
- **Residual S-B — singleton trusted binding (claim 8).** Extend
  `authorized_producers` enforcement to singleton phases. Independent.
- **Residual S-C — test hygiene (claim 5).** `conftest.py` teardown for
  `.test-tmp` basetemp residue. Independent, anytime.
