# Single File Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate e2e-dev-harness run control state into one authoritative file, then make clarification repair dispatch transactional so CREATED deadlocks cannot recur through split JSON state or prompt keyword fallback.

**Architecture:** Introduce a single authoritative `control-plane.json` per run. Existing files such as `run-state.json`, `agent-schedule.json`, `.phase-lock`, `coordinator-summary.json`, and `snapshots/*` become derived compatibility projections and must not be read as independent truth by new control-plane code. Dispatch, repair, task status, lifecycle, phase lock, and coordinator guidance are updated through typed state-store transactions.

**Tech Stack:** Python 3, existing `e2e-dev-harness` scripts, `unittest`, GitNexus impact/detect-changes, append-only projection compatibility for legacy CLI surfaces.

---

## Architectural Analysis

The current deadlock is not caused by one missing field. It is caused by a split-brain control plane:

- `agent-schedule.json` owns task metadata but is hand-written by multiple paths.
- `run-state.json` owns lifecycle and dispatch status but can disagree with `dispatch-events/*`.
- `coordinator-summary.json` repeats next-action guidance and can become stale.
- `.phase-lock` repeats lifecycle/write policy and can disagree with run state.
- `phase_guard.py` falls back to prompt keyword heuristics when schedule metadata is incomplete.
- Repair tasks are appended as normal tasks, so each repair can create another partially specified task.

The correct target is a single durable state document:

```text
docs/agent-runs/<run>/control-plane.json
```

This file is the only authoritative state for:

- lifecycle and gates
- phase lock/write policy
- tasks and role metadata
- dispatch status and worker proof
- repair transactions
- artifact ownership and hashes
- coordinator next action
- projection versions and compatibility output status

Derived files may still exist for compatibility, but they are outputs:

```text
run-state.json
agent-schedule.json
.phase-lock
coordinator-summary.json
snapshots/run-state.json
snapshots/agent-schedule.json
dispatch-events/*.json
```

New code must not merge truth from those files. It may read legacy files only through a migration/import function that produces `control-plane.json`, then all future writes go through the state store.

## Blast Radius

GitNexus impact checks:

- `_ensure_artifact_repair_tasks`: LOW risk, 2 direct callers, affects clarification flow only.
- `dispatcher_task_role_group`: MEDIUM risk, direct caller `_validate_action`, many phase guard tests indirectly affected.
- `event_log.append_event`: CRITICAL risk, 8 direct callers, 16 affected processes.
- `event_log.write_snapshot_projections`: CRITICAL risk, 4 direct callers, 8 affected processes.

Plan implication: do not replace `append_event` wholesale first. Add the single-file control plane beside the event log, migrate one CREATED clarification repair slice, and keep legacy projection contracts stable.

## File Structure

Create:

- `skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py`  
  Owns schema defaults, load/save, typed mutations, projection generation, and legacy import.

- `skills/e2e-dev-harness/scripts/e2e_harness/domain/control_plane_models.py`  
  Small dataclasses or typed dict helpers for task contracts, dispatch records, repair transactions, and projection status.

- `tests/test_control_plane_state_store.py`  
  Focused unit tests for single-file state creation, legacy import, projections, repair transaction lifecycle, and invariant checks.

Modify:

- `skills/e2e-dev-harness/scripts/e2e_harness/engine/state_store.py`  
  Route lifecycle/task/dispatch wrappers through `control_plane.py`; keep existing public functions stable.

- `skills/e2e-dev-harness/scripts/e2e_harness/engine/clarification_flow.py`  
  Replace repair-task append logic with repair transaction open/dispatch/complete operations.

- `skills/e2e-dev-harness/scripts/dispatcher.py`  
  Use typed task contracts from the control plane when building spawn prompts, dispatch state, and completion guidance.

- `skills/e2e-dev-harness/scripts/phase_guard.py`  
  Resolve dispatcher tasks from `control-plane.json`; fail closed with `schedule_contract_invalid` when metadata is missing, never fall back to `CODE_TASK_RE` for dispatcher-generated tasks.

- `skills/e2e-dev-harness/scripts/event_log.py`  
  Keep append compatibility; add projection helpers that derive legacy snapshots from `control-plane.json` instead of treating snapshots as truth.

- `skills/e2e-dev-harness/scripts/harness_doctor.py`  
  Report control-plane projection drift and legacy-file import status.

## Task 1: Add The Single-File Control Plane Schema

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/domain/control_plane_models.py`
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py`
- Test: `tests/test_control_plane_state_store.py`

- [ ] **Step 1: Write failing tests for new run creation**

Add tests proving a new control plane contains lifecycle, gates, phase lock, tasks, dispatches, repairs, artifacts, and projection metadata in one file.

```python
def test_control_plane_create_writes_single_authoritative_file(self):
    repo, run_dir = self.make_run_dir()
    result = control_plane.create(repo, run_dir, run_id="docs/agent-runs/run")
    self.assertTrue(result["ready"])
    path = run_dir / "control-plane.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    self.assertEqual(data["schema"], "e2e-dev-harness.control-plane.v1")
    self.assertEqual(data["lifecycle"], "CREATED")
    self.assertIn("tasks", data)
    self.assertIn("dispatches", data)
    self.assertIn("repair_transactions", data)
    self.assertEqual(data["phase_lock"]["state"], "code-write-locked")
```

- [ ] **Step 2: Run the focused red test**

Run:

```powershell
python -m unittest discover -s tests -p test_control_plane_state_store.py
```

Expected: import or missing function failure for `control_plane.create`.

- [ ] **Step 3: Implement minimal schema creation**

Implement `control_plane.create(repo, run_dir, run_id)` with atomic JSON writes. Include these top-level keys:

```python
{
    "schema": "e2e-dev-harness.control-plane.v1",
    "run_id": run_id,
    "lifecycle": "CREATED",
    "gates": {...},
    "phase_lock": {...},
    "tasks": [],
    "dispatches": {},
    "repair_transactions": {},
    "artifacts": {},
    "coordinator": {},
    "projections": {},
    "history": [],
}
```

- [ ] **Step 4: Verify creation passes**

Run:

```powershell
python -m unittest discover -s tests -p test_control_plane_state_store.py
```

Expected: new creation test passes.

- [ ] **Step 5: Commit**

```powershell
git add skills/e2e-dev-harness/scripts/e2e_harness/domain/control_plane_models.py skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py tests/test_control_plane_state_store.py
git commit -m "feat: add single-file control plane schema"
```

## Task 2: Import Legacy Run Files Into Control Plane

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py`
- Test: `tests/test_control_plane_state_store.py`

- [ ] **Step 1: Write failing legacy import test**

Use a fixture with `run-state.json`, `agent-schedule.json`, `.phase-lock`, and `coordinator-summary.json`; assert import writes one `control-plane.json` and marks legacy files as projections.

```python
def test_import_legacy_run_converges_state_into_control_plane(self):
    repo, run_dir = self.write_legacy_created_run()
    result = control_plane.import_legacy(repo, run_dir)
    self.assertTrue(result["ready"])
    data = json.loads((run_dir / "control-plane.json").read_text(encoding="utf-8"))
    self.assertEqual(data["lifecycle"], "CREATED")
    self.assertEqual(data["tasks"][0]["id"], "T01")
    self.assertEqual(data["tasks"][0]["role_group"], "design")
    self.assertEqual(data["projections"]["run-state.json"]["mode"], "compat")
```

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m unittest discover -s tests -p test_control_plane_state_store.py
```

Expected: `import_legacy` missing.

- [ ] **Step 3: Implement legacy import**

Merge legacy fields into one document with deterministic precedence:

1. `run-state.json` supplies lifecycle, gates, dispatches, history.
2. `agent-schedule.json` supplies tasks.
3. `.phase-lock` supplies phase lock only when lifecycle matches run state.
4. `coordinator-summary.json` supplies coordinator guidance only as projection metadata.
5. Missing task contract fields are filled from canonical phase/agent metadata.

- [ ] **Step 4: Add invariant errors**

If legacy files disagree, store warnings in `diagnostics` and return `ready: false` only when the conflict would change write permissions or dispatch ownership.

- [ ] **Step 5: Verify**

Run:

```powershell
python -m unittest discover -s tests -p test_control_plane_state_store.py
```

Expected: import tests pass.

- [ ] **Step 6: Commit**

```powershell
git add skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py tests/test_control_plane_state_store.py
git commit -m "feat: import legacy run state into control plane"
```

## Task 3: Generate Legacy Projections From Control Plane

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py`
- Modify: `skills/e2e-dev-harness/scripts/event_log.py`
- Test: `tests/test_control_plane_state_store.py`
- Test: `tests/test_enterprise_harness_architecture.py`

- [ ] **Step 1: Write projection test**

Assert `write_legacy_projections` writes `run-state.json`, `agent-schedule.json`, `.phase-lock`, and `coordinator-summary.json` from `control-plane.json`.

```python
def test_legacy_projections_are_derived_from_control_plane(self):
    repo, run_dir = self.make_control_plane_with_task("T01")
    result = control_plane.write_legacy_projections(repo, run_dir)
    self.assertTrue(result["ready"])
    state = json.loads((run_dir / "run-state.json").read_text(encoding="utf-8"))
    schedule = json.loads((run_dir / "agent-schedule.json").read_text(encoding="utf-8"))
    self.assertEqual(state["source"], "control-plane.json")
    self.assertEqual(schedule["tasks"][0]["id"], "T01")
```

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m unittest discover -s tests -p test_control_plane_state_store.py
```

Expected: projection function missing.

- [ ] **Step 3: Implement projections**

Projection must be deterministic and complete enough for existing CLI/hook consumers:

- run state: lifecycle, gates, dispatch/current dispatch, dispatches, history, artifact registry path.
- schedule: tasks, selected mode, completion mode, max workers.
- phase lock: lifecycle, write states, services, owners.
- coordinator summary: navigation map and next action from control plane.

- [ ] **Step 4: Preserve event_log compatibility**

Keep `event_log.write_snapshot_projections(...)` behavior but make it call control-plane projection when `control-plane.json` exists. If not, use legacy event replay.

- [ ] **Step 5: Verify focused tests**

Run:

```powershell
python -m unittest discover -s tests -p test_control_plane_state_store.py
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py
```

Expected: projection and existing event architecture tests pass.

- [ ] **Step 6: Commit**

```powershell
git add skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py skills/e2e-dev-harness/scripts/event_log.py tests/test_control_plane_state_store.py tests/test_enterprise_harness_architecture.py
git commit -m "feat: project legacy harness files from control plane"
```

## Task 4: Add Typed Task Contract Factory

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/domain/control_plane_models.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py`
- Modify: `skills/e2e-dev-harness/scripts/orchestration_plan.py`
- Test: `tests/test_control_plane_state_store.py`
- Test: `tests/test_clarification_flow.py`

- [ ] **Step 1: Write failing task factory tests**

```python
def test_task_factory_fills_required_contract_for_repair_task(self):
    task = control_plane.task_contract(
        task_id="T01b",
        agent="requirements-clarifier",
        phase="clarify",
        kind="artifact_repair",
        outputs=["docs/design/example.md"],
        repair_targets=["docs/design/example.md"],
    )
    self.assertEqual(task["role_group"], "design")
    self.assertEqual(task["runtime_subagent_type"], "requirements-clarifier")
    self.assertEqual(task["dispatch_contract"], "fresh-subagent")
```

- [ ] **Step 2: Run red tests**

Run:

```powershell
python -m unittest discover -s tests -p test_control_plane_state_store.py
python -m unittest discover -s tests -p test_clarification_flow.py
```

Expected: factory missing.

- [ ] **Step 3: Implement `task_contract`**

The factory must fill:

- `id`
- `agent`
- `phase`
- `role_group`
- `role_template`
- `role_template_key`
- `runtime_subagent_type`
- `parallel_group`
- `depends_on_phases`
- `inputs`
- `outputs`
- `status`
- `requires_runtime_dispatch`
- `dispatch_contract`
- repair fields when `kind == artifact_repair`

- [ ] **Step 4: Route initial schedule generation through the factory**

In `orchestration_plan.agent_schedule`, replace inline task dict construction with the factory while preserving current output shape.

- [ ] **Step 5: Verify**

Run:

```powershell
python -m unittest discover -s tests -p test_control_plane_state_store.py
python -m unittest discover -s tests -p test_clarification_flow.py
```

Expected: task factory tests pass and existing clarify tests remain green.

- [ ] **Step 6: Commit**

```powershell
git add skills/e2e-dev-harness/scripts/e2e_harness/domain/control_plane_models.py skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py skills/e2e-dev-harness/scripts/orchestration_plan.py tests/test_control_plane_state_store.py tests/test_clarification_flow.py
git commit -m "feat: centralize harness task contracts"
```

## Task 5: Make Clarification Repair A Transaction

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/engine/clarification_flow.py`
- Test: `tests/test_clarification_flow.py`
- Test: `tests/test_preflight_aggregator.py`

- [ ] **Step 1: Write failing repair transaction test**

```python
def test_repair_transaction_prevents_duplicate_active_repair_tasks(self):
    repo, run_dir = self.write_created_run_needing_impact_repair()
    first = control_plane.open_repair_transaction(
        repo, run_dir, code="impact_summary_too_long", target="docs/design/example.md"
    )
    second = control_plane.open_repair_transaction(
        repo, run_dir, code="impact_summary_too_long", target="docs/design/example.md"
    )
    self.assertEqual(first["task_id"], second["task_id"])
    self.assertEqual(second["status"], "already_open")
```

- [ ] **Step 2: Run red tests**

Run:

```powershell
python -m unittest discover -s tests -p test_clarification_flow.py
python -m unittest discover -s tests -p test_preflight_aggregator.py
```

Expected: repair transaction API missing.

- [ ] **Step 3: Implement repair transaction lifecycle**

Use statuses:

```text
opened -> dispatched -> worker_running -> evidence_validated -> closed
opened -> cancelled
opened -> blocked
```

The transaction owns the repair task id and target artifact. It must refuse to open a second active transaction for the same `(repair_code, target)`.

- [ ] **Step 4: Replace `_ensure_artifact_repair_tasks` append behavior**

Change clarification flow so mechanical remediation opens or resumes one repair transaction and gets its task from the task factory.

- [ ] **Step 5: Update preflight guidance**

Preflight should say `complete active repair transaction <id>` rather than `dispatch mechanical repair task T01c` when a transaction is active.

- [ ] **Step 6: Verify**

Run:

```powershell
python -m unittest discover -s tests -p test_clarification_flow.py
python -m unittest discover -s tests -p test_preflight_aggregator.py
```

Expected: transaction tests pass; no duplicate repair task behavior.

- [ ] **Step 7: Commit**

```powershell
git add skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py skills/e2e-dev-harness/scripts/e2e_harness/engine/clarification_flow.py tests/test_clarification_flow.py tests/test_preflight_aggregator.py
git commit -m "feat: make clarification repair transactional"
```

## Task 6: Route Dispatch State Through Control Plane

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/engine/state_store.py`
- Modify: `skills/e2e-dev-harness/scripts/dispatcher.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/engine/dispatch_engine.py`
- Test: `tests/test_dispatch_finish.py`
- Test: `tests/test_control_plane_state_store.py`

- [ ] **Step 1: Write failing dispatch convergence test**

```python
def test_dispatch_ack_and_complete_update_only_control_plane_then_project(self):
    repo, run_dir = self.make_control_plane_with_task("T01")
    ack = state_store.dispatch_ack(repo, run_dir / "run-state.json", "T01", "requirements-clarifier", "worker-1")
    self.assertTrue(ack["ready"])
    data = json.loads((run_dir / "control-plane.json").read_text(encoding="utf-8"))
    self.assertEqual(data["dispatches"]["T01"]["status"], "worker_running")
    self.assertTrue((run_dir / "run-state.json").exists())
```

- [ ] **Step 2: Run red tests**

Run:

```powershell
python -m unittest discover -s tests -p test_dispatch_finish.py
python -m unittest discover -s tests -p test_control_plane_state_store.py
```

Expected: dispatch wrappers still write legacy state first.

- [ ] **Step 3: Implement control-plane dispatch mutations**

Add:

- `control_plane.dispatch_started`
- `control_plane.dispatch_acknowledged`
- `control_plane.dispatch_completed`
- `control_plane.dispatch_failed`

Each mutation writes `control-plane.json` atomically, then writes projections.

- [ ] **Step 4: Preserve public CLI output**

`dispatch-beat`, `dispatch-ack`, `dispatch-complete`, and `dispatch-finish` must keep their current JSON result fields while reading authoritative state from `control-plane.json`.

- [ ] **Step 5: Verify focused dispatch tests**

Run:

```powershell
python -m unittest discover -s tests -p test_dispatch_finish.py
python -m unittest discover -s tests -p test_control_plane_state_store.py
```

Expected: dispatch finish and new convergence tests pass.

- [ ] **Step 6: Commit**

```powershell
git add skills/e2e-dev-harness/scripts/e2e_harness/engine/state_store.py skills/e2e-dev-harness/scripts/dispatcher.py skills/e2e-dev-harness/scripts/e2e_harness/engine/dispatch_engine.py tests/test_dispatch_finish.py tests/test_control_plane_state_store.py
git commit -m "feat: route dispatch through single control plane"
```

## Task 7: Make Phase Guard Contract-Based

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/phase_guard.py`
- Test: `tests/test_dispatch_finish.py`
- Test: `tests/test_e2e_dev_harness_scripts.py`

- [ ] **Step 1: Write failing regression for T01c prompt**

Create a fixture where a dispatcher-generated requirements-clarifier repair prompt contains the word `code`, lifecycle is `CREATED`, and task contract has `role_group: design`. Assert phase guard allows the Task spawn.

```python
def test_created_repair_worker_prompt_with_code_word_uses_contract_not_keyword(self):
    result = phase_guard.validate_action(
        repo=self.repo,
        tool_name="Task",
        payload={"description": self.t01c_prompt_with_code_word},
    )
    self.assertTrue(result["ready"], result.get("blocked_reasons"))
```

- [ ] **Step 2: Write failing contract-missing test**

If the prompt is dispatcher-generated but task metadata cannot be resolved, assert a contract error instead of code-agent lifecycle denial.

```python
def test_dispatcher_prompt_missing_task_contract_fails_as_schedule_contract_invalid(self):
    result = phase_guard.validate_action(
        repo=self.repo,
        tool_name="Task",
        payload={"description": self.prompt_for_missing_task},
    )
    self.assertFalse(result["ready"])
    self.assertIn("schedule_contract_invalid", result["blocked_reason_codes"])
```

- [ ] **Step 3: Run red tests**

Run:

```powershell
python -m unittest discover -s tests -p test_dispatch_finish.py
python -m unittest discover -s tests -p test_e2e_dev_harness_scripts.py
```

Expected: current fallback hits code-agent lifecycle denial.

- [ ] **Step 4: Implement contract-based dispatcher classification**

For dispatcher-generated prompts:

1. Parse task id and context pack.
2. Resolve task from `control-plane.json`.
3. If missing or missing required fields, block with `schedule_contract_invalid`.
4. If `role_group == "code"`, enforce IMPLEMENTED lifecycle.
5. Otherwise allow according to worker-output ownership rules.

Never use `CODE_TASK_RE` for dispatcher-generated prompts.

- [ ] **Step 5: Verify**

Run:

```powershell
python -m unittest discover -s tests -p test_dispatch_finish.py
python -m unittest discover -s tests -p test_e2e_dev_harness_scripts.py
```

Expected: phase guard regression passes and existing write-safety tests remain green.

- [ ] **Step 6: Commit**

```powershell
git add skills/e2e-dev-harness/scripts/phase_guard.py tests/test_dispatch_finish.py tests/test_e2e_dev_harness_scripts.py
git commit -m "fix: classify dispatcher tasks from control-plane contracts"
```

## Task 8: Add A Legal Control-Plane Repair Command

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_dev_harness.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py`
- Test: `tests/test_e2e_dev_harness_scripts.py`
- Test: `tests/test_control_plane_state_store.py`

- [ ] **Step 1: Write failing CLI repair test**

```python
def test_control_plane_repair_normalizes_missing_task_contract(self):
    repo, run_dir = self.write_control_plane_with_task_missing_role_group()
    result = self.run_cli([
        "control-plane", "repair",
        ".",
        "--run-dir", str(run_dir),
        "--scope", "task-contracts",
        "--json",
    ])
    self.assertEqual(result.returncode, 0)
    data = json.loads((run_dir / "control-plane.json").read_text(encoding="utf-8"))
    self.assertEqual(data["tasks"][0]["role_group"], "design")
```

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m unittest discover -s tests -p test_control_plane_state_store.py
python -m unittest discover -s tests -p test_e2e_dev_harness_scripts.py
```

Expected: CLI command missing.

- [ ] **Step 3: Implement repair command**

Command:

```powershell
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py control-plane repair . --run-dir docs/agent-runs/<run> --scope task-contracts --json
```

Allowed scopes:

- `task-contracts`
- `projections`
- `legacy-import`

Disallowed:

- writing worker-owned outputs
- changing lifecycle
- completing tasks
- editing evidence content

- [ ] **Step 4: Teach phase_guard to allow this command**

Allow the specific CLI command shape while keeping arbitrary control-file mutations blocked.

- [ ] **Step 5: Verify**

Run:

```powershell
python -m unittest discover -s tests -p test_control_plane_state_store.py
python -m unittest discover -s tests -p test_e2e_dev_harness_scripts.py
```

Expected: repair command passes and direct file edit tests still block.

- [ ] **Step 6: Commit**

```powershell
git add skills/e2e-dev-harness/scripts/e2e_dev_harness.py skills/e2e-dev-harness/scripts/e2e_harness/cli/commands skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py tests/test_control_plane_state_store.py tests/test_e2e_dev_harness_scripts.py
git commit -m "feat: add legal control-plane repair command"
```

## Task 9: Add Doctor Drift Diagnostics

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/harness_doctor.py`
- Test: `tests/test_harness_doctor.py`

- [ ] **Step 1: Write failing doctor test**

```python
def test_doctor_reports_projection_drift_from_control_plane(self):
    repo, run_dir = self.write_control_plane_and_stale_run_state()
    result = harness_doctor.evaluate(repo, json_mode=True)
    self.assertFalse(result["ready"])
    self.assertIn("control-plane-projection-drift", result["blocked_reasons"][0])
```

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m unittest discover -s tests -p test_harness_doctor.py
```

Expected: doctor does not detect projection drift.

- [ ] **Step 3: Implement doctor checks**

Doctor should report:

- missing `control-plane.json`
- legacy files newer than control-plane
- projection drift by hash
- active repair transaction older than lease
- dispatcher task with missing contract fields

- [ ] **Step 4: Verify**

Run:

```powershell
python -m unittest discover -s tests -p test_harness_doctor.py
```

Expected: doctor diagnostics pass.

- [ ] **Step 5: Commit**

```powershell
git add skills/e2e-dev-harness/scripts/harness_doctor.py tests/test_harness_doctor.py
git commit -m "feat: diagnose control-plane projection drift"
```

## Task 10: Validate Against Petalpay Deadlock Fixture

**Files:**
- Create: `tests/fixtures/petalpay-created-repair-deadlock/`
- Test: `tests/test_control_plane_state_store.py`
- Test: `tests/test_dispatch_finish.py`

- [ ] **Step 1: Add minimized fixture**

Fixture contains:

- `control-plane.json` imported from the deadlock state
- legacy `run-state.json`
- legacy `agent-schedule.json`
- `dispatch-spawn-requests/T01c-spawn-request.json`
- `.phase-lock`

Keep the design doc body short and synthetic; preserve only fields needed to reproduce the dispatch contract failure.

- [ ] **Step 2: Write regression test**

```python
def test_petalpay_t01c_created_repair_spawn_is_allowed_after_contract_import(self):
    repo, run_dir = self.copy_fixture("petalpay-created-repair-deadlock")
    control_plane.import_legacy(repo, run_dir)
    result = phase_guard.validate_action(
        repo=repo,
        tool_name="Task",
        payload={"description": (run_dir / "dispatch-spawn-requests/T01c-prompt.md").read_text(encoding="utf-8")},
    )
    self.assertTrue(result["ready"], result.get("blocked_reasons"))
```

- [ ] **Step 3: Run regression**

Run:

```powershell
python -m unittest discover -s tests -p test_control_plane_state_store.py
python -m unittest discover -s tests -p test_dispatch_finish.py
```

Expected: fixture passes.

- [ ] **Step 4: Commit**

```powershell
git add tests/fixtures/petalpay-created-repair-deadlock tests/test_control_plane_state_store.py tests/test_dispatch_finish.py
git commit -m "test: cover petalpay created repair deadlock fixture"
```

## Task 11: Full Verification And Installed Runtime Sync

**Files:**
- Modify only if verification reveals missed projection or installed-copy issues.

- [ ] **Step 1: Run focused suite**

Run:

```powershell
python -m unittest discover -s tests -p test_control_plane_state_store.py
python -m unittest discover -s tests -p test_clarification_flow.py
python -m unittest discover -s tests -p test_preflight_aggregator.py
python -m unittest discover -s tests -p test_dispatch_finish.py
python -m unittest discover -s tests -p test_harness_doctor.py
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py
```

Expected: all pass.

- [ ] **Step 2: Run full regression**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 3: Run GitNexus change analysis**

Run:

```powershell
python skills/e2e-dev-harness/scripts/kg_refresh.py . --json
npx gitnexus analyze
gitnexus detect-changes --repo C:\Users\14907\Documents\Codex\2026-05-23\skill-skill-superpowers-skill-tdd-graphify --scope unstaged
```

Expected: changed symbols and affected flows match the planned control-plane surface.

- [ ] **Step 4: Sync installed harness copies**

Run:

```powershell
node tools/install-e2e-dev-harness.mjs --sync --yes --json
```

Expected: installed `.codex`, `.agents`, and `.claude` copies match source hashes for `control_plane.py`, `state_store.py`, `event_log.py`, `dispatcher.py`, `phase_guard.py`, and `dispatch_engine.py`.

- [ ] **Step 5: Smoke petalpay recovery**

In `C:\Users\14907\Documents\Codex\2026-05-23\petalpay`, run:

```powershell
e2e-harness doctor . --json
e2e-harness control-plane repair . --run-dir docs/agent-runs/2026-06-06-feature --scope legacy-import --json
e2e-harness control-plane repair . --run-dir docs/agent-runs/2026-06-06-feature --scope task-contracts --json
e2e-harness next . --state docs/agent-runs/2026-06-06-feature/run-state.json
```

Expected: doctor no longer reports schedule contract deadlock; `next` points to completing/resuming the active repair transaction, not re-dispatching or code-agent denial.

- [ ] **Step 6: Final detect-changes before commit**

Run:

```powershell
gitnexus detect-changes --repo C:\Users\14907\Documents\Codex\2026-05-23\skill-skill-superpowers-skill-tdd-graphify --scope unstaged
```

Expected: affected flows are the intended control-plane, dispatch, phase guard, and doctor paths.

- [ ] **Step 7: Commit verification changes**

```powershell
git add .
git commit -m "feat: converge harness control plane to single state file"
```

## Non-Goals

- Do not delete legacy files in this slice.
- Do not weaken worker-owned output protection.
- Do not allow coordinator-authored handoff/evidence repair.
- Do not rewrite all lifecycle phases at once.
- Do not make event log the only file; the agreed target is one authoritative state file plus derived projections.

## Completion Criteria

- Every run has exactly one authoritative `control-plane.json`.
- All new control-plane decisions read from `control-plane.json`.
- Legacy files are regenerated projections and marked as such.
- Clarification repair is a transaction and cannot create duplicate active repair tasks.
- Dispatcher-generated prompts never fall back to `CODE_TASK_RE`.
- There is a legal CLI path to normalize task contracts.
- Doctor reports projection drift and stale repair transactions.
- The petalpay CREATED/T01c fixture no longer deadlocks.
- Focused and full test suites pass.
- GitNexus `detect-changes` confirms expected affected scope.
