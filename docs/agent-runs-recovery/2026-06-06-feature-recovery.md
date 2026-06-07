# Recovery runbook — petalpay run `2026-06-06-feature`

**Scope:** Recover the petalpay agent run at
`petalpay/docs/agent-runs/2026-06-06-feature` from the control-plane / run-state
split-brain that the pre-SSOT harness produced (clobbered `tasks`, phantom T06
dispatch, misleading `stale-transaction` blocker masking the real divergence).

**Run this ONCE, after the fixed harness ships** (commits `617f70d..HEAD` on
branch `codex/clarification-bash-reduction`: control-plane SSOT write path,
non-destructive projection, dispatch phase guard, authority flip + divergence
check). It writes only to the petalpay run directory; nothing here mutates the
harness repo.

The steps are **idempotent** — re-running any step converges to the same state.
Substitute your real paths for the placeholders:

```bash
REPO=path/to/petalpay                       # the petalpay repo root
RUN_DIR=docs/agent-runs/2026-06-06-feature  # run dir, relative to $REPO
HARNESS=path/to/skills/e2e-dev-harness/scripts/e2e_dev_harness.py
DESIGN_DOC="$RUN_DIR/<the design doc the plan was built from>"
```

---

## Step 1 — Back up the run directory FIRST

Copy the entire run dir before touching anything. This is your rollback point.

```bash
cp -r "$REPO/$RUN_DIR" "$REPO/${RUN_DIR}.bak-$(date +%Y%m%dT%H%M%SZ)"
```

Verify the backup is complete (control-plane.json, run-state.json,
agent-schedule.json, coordinator-results/, dispatch-events/, service-designs/,
service-plans/ all present), then proceed.

---

## Step 2 — Rebuild the control-plane task set + lifecycle

The clobbered `control-plane.json` `tasks` array and its lifecycle must be
rebuilt from a trustworthy source. Pick **one** option.

### Option A (preferred) — re-run the now-SSOT-writing `plan` command

The fixed `plan` command persists the expanded task set **and** advances the
control-plane lifecycle in lockstep with run-state via
`control_plane.replace_tasks` (commits `d4c2cfe`, `80eafb8`). Regenerate from
the design doc:

```bash
python "$HARNESS" plan "$REPO" \
  --design-doc "$DESIGN_DOC" \
  --create-archive
```

This rewrites `control-plane.json` `tasks` + lifecycle as the authoritative SSOT
and projects outward to the legacy files. Use this when the design doc still
faithfully describes the intended schedule.

### Option B — rebuild `tasks` directly from the recorded plan + events

Use this when you must preserve the *exact* originally-dispatched schedule rather
than re-expand the design doc. Rebuild the task list from the persisted plan
result plus the dispatch event log, then call the sanctioned write path:

Source files:
- `"$RUN_DIR/coordinator-results/20260607T073351Z-plan.json"` — the expanded plan
  (authoritative structural task set: ids, phases, agents, dependencies).
- `"$RUN_DIR/dispatch-events/"` — `*-completed.json` / dispatch events
  (which tasks actually ran; reconciled by `write_legacy_projections`, do NOT
  hand-encode dispatch status into `tasks`).

```python
# run from $REPO, e.g.  python recover_2026-06-06-feature.py
import json
from pathlib import Path
import sys

sys.path.insert(0, "path/to/skills/e2e-dev-harness/scripts")
from e2e_harness.engine import control_plane  # noqa: E402

repo = Path(".")
run_dir = Path("docs/agent-runs/2026-06-06-feature")

plan = json.loads(
    (run_dir / "coordinator-results/20260607T073351Z-plan.json").read_text("utf-8")
)
# Extract the structural task list from the plan result. Keep ONLY structural
# fields (id, phase, agent, depends_on, title, ...). Leave dispatch/claim/
# completion state out — write_legacy_projections folds that back in from
# dispatch-events via _reconcile_on_disk_tasks.
tasks = plan["tasks"]            # adjust key to the plan schema if it differs

control_plane.replace_tasks(
    repo,
    run_dir,
    tasks,
    lifecycle="<the correct lifecycle, e.g. PLANNED>",  # advance in lockstep
)
```

`replace_tasks(repo, run_dir, tasks, lifecycle=...)` is the **only** sanctioned
write path for the task set (commit `d369944`); it normalises the structural
list, sets lifecycle/gate, then runs `write_legacy_projections`, which is
**non-destructive** — `_reconcile_on_disk_tasks` folds the live on-disk dispatch
state back on top instead of erasing it (commit `68f9a5e`).

---

## Step 3 — Resolve the phantom T06 dispatch

T06 has a dispatch recorded with no trustworthy completion (the split-brain
artifact). There is an honest `service-designs/jeepay-core.md` on disk. Pick
**one**.

### Option A — honor the existing design, record a trustworthy completion

If `service-designs/jeepay-core.md` is the genuine T06 output, record a
dispatch-complete so the harness writes `dispatch-events/T06-completed.json`.
T06's dispatch is a phantom (no ack/worker_running proof), so use the auditable
manual-recovery path:

```bash
# 1. Write a recovery-approval request and get explicit user approval.
#    --schedule is required; --write-recovery-request takes the output PATH.
python "$HARNESS" dispatch-status "$REPO" \
  --schedule "$RUN_DIR/agent-schedule.json" \
  --task-id T06 \
  --write-recovery-request "$RUN_DIR/T06-recovery-request.json"

# 2. After approval, record the completion with the design as evidence.
#    --schedule is required on dispatch-complete.
python "$HARNESS" dispatch-complete "$REPO" \
  --schedule "$RUN_DIR/agent-schedule.json" \
  --task-id T06 \
  --manual-recovery \
  --recovery-approval "$RUN_DIR/<approval-file>" \
  --evidence "$RUN_DIR/service-designs/jeepay-core.md"
```

This writes `dispatch-events/T06-completed.json`; the next projection reconciles
it into `control-plane.json` non-destructively.

### Option B — discard the phantom dispatch and re-dispatch cleanly

If the phantom dispatch is untrustworthy, remove the stray T06 dispatch
record/event and let the fixed harness re-dispatch under the new phase guard:

```bash
# Remove the phantom T06 dispatch event(s) only (keep everything else).
rm -f "$RUN_DIR/dispatch-events/"T06-*.json

# Re-run a dispatch beat; the phase guard now gates T06 against lifecycle.
python "$HARNESS" dispatch-beat "$REPO" \
  --schedule "$RUN_DIR/agent-schedule.json" \
  --state "$RUN_DIR/run-state.json" \
  --max-workers 1
```

Because lifecycle/phase were reconciled in Step 2, the `_DISPATCH_PHASE_ALLOWLIST`
guard (`_phase_allowed`, commit `83f64df`) will only let T06 dispatch if its
phase is legal for the current lifecycle — preventing the original
design@CLARIFIED phantom re-dispatch.

---

## Step 4 — Validate

```bash
# 1. State must no longer be blocked.
python "$HARNESS" next "$REPO" --state "$RUN_DIR/run-state.json"
#    Expect: state_confidence != "blocked".

# 2. Doctor must report no control-plane divergence.
#    doctor has no --run-dir; pass --state and it derives run_dir from the
#    state file's parent to run the state-control-plane-divergence check.
python "$HARNESS" doctor "$REPO" --state "$RUN_DIR/run-state.json" --json
#    Expect: NO "state-control-plane-divergence" check failure.
```

If `next` still reports `blocked` or doctor still flags
`state-control-plane-divergence`, do NOT improvise — restore from the Step 1
backup and re-run Step 2 before retrying Step 3.

---

## Why this recovery is now safe and idempotent

The pre-SSOT harness made this run unrecoverable in three ways; each shipped fix
removes one failure mode, which is what makes the steps above re-runnable:

1. **Non-destructive projection won't re-clobber the task set.**
   `write_legacy_projections` used to overwrite `tasks`/schedule from a stale
   source. It now calls `_reconcile_on_disk_tasks` to fold live on-disk dispatch
   state back on top (commit `68f9a5e`), so re-running Step 2 (or any later beat)
   cannot wipe completed/in-flight work. This is what makes `replace_tasks` safe
   to call repeatedly.

2. **The phase guard prevents re-dispatching design@CLARIFIED.**
   `_DISPATCH_PHASE_ALLOWLIST` + `_phase_allowed` block tasks whose phase doesn't
   match the current lifecycle (commits `83f64df`, `4eba02d`). Once Step 2
   reconciles lifecycle/phase, Step 3 Option B cannot recreate the original
   phantom T06 dispatch — the guard rejects a `design` task under a `CLARIFIED`
   lifecycle.

3. **The divergence check surfaces the real problem, not the stale-tx red herring.**
   The authority map now treats `control-plane.json` as primary (commit
   `73012c3`), `transition_lifecycle` garbage-collects stale
   `impact_summary_too_long` repair transactions, and the doctor's
   `state-control-plane-divergence` check is ranked **ahead of** the
   stale-transaction blocker. So Step 4's `doctor` reports the actual
   control-plane/run-state divergence (if any remains) instead of the misleading
   "stale transaction" message that previously masked it — giving an honest
   validation signal.

Together: you can run the whole runbook, inspect the result, and if it's wrong,
restore the backup and run it again with no risk of compounding the damage.
