# Control-Plane Single-Source-of-Truth (SSOT) Enforcement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Project rule (CLAUDE.md):** Before editing any function/class/method, run `gitnexus_impact({target, direction:"upstream"})` and report blast radius. Before each commit, run `gitnexus_detect_changes()`. Do not edit symbols flagged HIGH/CRITICAL without surfacing it first.

**Relationship to prior plans:** This completes `docs/superpowers/plans/2026-06-06-single-file-control-plane.md`. That plan declared `control-plane.json` authoritative and the legacy files "derived projections … must not be read as independent truth," but the implementation left two leaks: the `plan` command still writes the task set only into `agent-schedule.json`, and the diagnostics `authority` map still names `run-state.json` primary. This plan closes those leaks. It does **not** duplicate `2026-06-06-petalpay-harness-stuck-recovery.md` (different run dir `DESIGN-2026-002`, different incident).

**Goal:** Make `control-plane.json` the enforced single source of truth so a planning expansion can never be silently destroyed by a later projection write (the petalpay `2026-06-06-feature` split-brain).

**Architecture:** Today the *task set* lives only in the legacy `agent-schedule.json` (the `plan` command and `dispatch_beat` both read/write it), while `control-plane.json` is supposed to mirror it. Claims/dispatch/completion already reconcile into the control plane via event-sourcing (`_merge_dispatch_events`), so the **only** un-ingested mutation is the schedule's task array. The fix: (P2) the planner writes the expanded `tasks` into the control plane; (P3) the control→legacy projection becomes non-destructive (never drops a task that exists on disk, never regresses lifecycle); (P4) dispatch is gated so a task's `phase` must match the current lifecycle; (P1) the diagnostics `authority` map agrees with the engine (`primary = control-plane.json`); (P5) stale clarification repair transactions are garbage-collected and a real divergence check replaces the misleading "stale-transaction" blocker.

**Tech Stack:** Python 3.13, `unittest` (tests under `tests/`, add `SCRIPTS` to `sys.path`), atomic JSON writes via `common.atomic_write_json`. Engine code under `skills/e2e-dev-harness/scripts/e2e_harness/engine/`.

**Root-cause recap (evidence):** `control-plane.json` had `tasks=[T01,T01b]` and `history` with only `CREATED→CLARIFIED`; a real `T06` (design-phase) was dispatched while `lifecycle=CLARIFIED`; the `07:37` `dispatch-ack` ran `control_plane.dispatch_acknowledged → write_legacy_projections`, regenerating `agent-schedule.json` from the stale control plane and wiping the 29-task schedule. The harness then misreported the cause as `control-plane-repair-transaction-stale`.

**Out of scope:** Recovering the live petalpay run (user chose "先修 harness，不动现网"). A separate recovery doc is produced in Task 7 but no petalpay file is touched.

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py` | Authoritative store + projections | Add `replace_tasks`; make projection non-destructive; GC stale transactions; add divergence helper |
| `skills/e2e-dev-harness/scripts/e2e_harness/engine/state_store.py` | Bridge wrappers | Route `plan` task-set writes through `replace_tasks`; remove the asymmetric reverse-import risk |
| `skills/e2e-dev-harness/scripts/e2e_dev_harness.py` | CLI `plan` command | Persist expanded schedule into control plane after building it (~line 661) |
| `skills/e2e-dev-harness/scripts/dispatcher.py` | `dispatch_beat` | Add phase↔lifecycle dispatch guard (~line 1426–1428) |
| `skills/e2e-dev-harness/scripts/harness_doctor.py` | Diagnostics + authority map | Flip authority primary (line 839); add `state-control-plane-divergence` check |
| `skills/e2e-dev-harness/scripts/navigation_map.py` | Navigation authority default | Flip authority primary (line 143) |
| `tests/test_control_plane_state_store.py` | Engine tests | New regression + unit tests (existing file, extend) |
| `tests/test_e2e_dev_harness_scripts.py` | CLI/dispatcher tests | New dispatch-guard + plan-persists-cp tests |
| `docs/agent-runs-recovery/2026-06-06-feature-recovery.md` | Recovery runbook (no petalpay writes) | New doc |

**Test conventions:** `unittest`; each test builds a tmp repo + `run_dir = repo/"docs/agent-runs/run"`, calls `control_plane.create(repo, run_dir, run_id="docs/agent-runs/run")`, then mutates. Run a single test with:
`python -m pytest tests/test_control_plane_state_store.py::ClassName::test_name -v` (or `python -m unittest tests.test_control_plane_state_store.ClassName.test_name`).

---

## Task 1: Regression test that reproduces the split-brain (red harness for the whole fix)

**Files:**
- Test: `tests/test_control_plane_state_store.py` (append a new `unittest.TestCase`)

- [ ] **Step 1: Write the failing regression test**

Append to `tests/test_control_plane_state_store.py`:

```python
class ControlPlaneSsotRegression(unittest.TestCase):
    def _make_run(self, tmp: str):
        repo = Path(tmp)
        run_dir = repo / "docs" / "agent-runs" / "run"
        run_dir.mkdir(parents=True)
        control_plane.create(repo, run_dir, run_id="docs/agent-runs/run")
        # Clarify done: lifecycle CLARIFIED, only the clarify task exists in the control plane.
        control_plane.transition_lifecycle(
            repo, run_dir, "CLARIFIED", gate="clarification", gate_status="passed"
        )
        t01 = control_plane.task_contract("T01", "requirements-clarifier", "clarify", status="completed")
        data = control_plane.load(repo, run_dir)
        data["tasks"] = [t01]
        from common import atomic_write_json
        atomic_write_json(control_plane.control_plane_path(run_dir), data)
        control_plane.write_legacy_projections(repo, run_dir)
        return repo, run_dir

    def test_dispatch_ack_does_not_drop_expanded_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run_dir = self._make_run(tmp)
            # Planner expands the schedule THROUGH the control plane (P2 contract).
            expanded = [
                control_plane.task_contract("T01", "requirements-clarifier", "clarify", status="completed"),
                control_plane.task_contract("T06", "service-designer-jeepay-core", "design", service="jeepay-core"),
            ]
            control_plane.replace_tasks(repo, run_dir, expanded, lifecycle="SERVICE_DESIGN_REQUIRED")
            # A dispatch-ack for T06 must NOT shrink the schedule back to clarify-only.
            control_plane.dispatch_acknowledged(
                repo, run_dir, {"current_task_id": "T06", "current_agent": "service-designer-jeepay-core", "status": "worker_running"}
            )
            schedule = json.loads((run_dir / "agent-schedule.json").read_text(encoding="utf-8"))
            ids = [t["id"] for t in schedule["tasks"]]
            self.assertIn("T06", ids, "dispatch-ack must not drop the expanded task set")
            self.assertIn("T01", ids)
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python -m pytest "tests/test_control_plane_state_store.py::ControlPlaneSsotRegression::test_dispatch_ack_does_not_drop_expanded_schedule" -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'replace_tasks'` (the function does not exist yet). This proves the test exercises the missing SSOT path.

- [ ] **Step 3: Commit the red test**

```bash
git add tests/test_control_plane_state_store.py
git commit -m "test: red regression for control-plane schedule clobber"
```

---

## Task 2 (P2): `control_plane.replace_tasks` — planner writes the task set into the control plane

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py` (add function after `dispatch_completed`, ~line 695)
- Test: `tests/test_control_plane_state_store.py`

- [ ] **Step 1 (gitnexus):** Run `gitnexus_impact({target:"write_legacy_projections", direction:"upstream"})` and report callers. Expected callers: `repair`, `open_repair_transaction`, `dispatch_acknowledged`, `dispatch_completed`, `state_store._project`. Surface risk level before editing.

- [ ] **Step 2: Write the failing unit test**

```python
    def test_replace_tasks_persists_into_control_plane_and_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run_dir = self._make_run(tmp)
            tasks = [
                control_plane.task_contract("T01", "requirements-clarifier", "clarify", status="completed"),
                control_plane.task_contract("T02", "service-designer-core", "design", service="core"),
            ]
            result = control_plane.replace_tasks(repo, run_dir, tasks, lifecycle="SERVICE_DESIGN_REQUIRED")
            self.assertTrue(result["ready"])
            data = control_plane.load(repo, run_dir)
            self.assertEqual([t["id"] for t in data["tasks"]], ["T01", "T02"])
            self.assertEqual(data["lifecycle"], "SERVICE_DESIGN_REQUIRED")
            schedule = json.loads((run_dir / "agent-schedule.json").read_text(encoding="utf-8"))
            self.assertEqual([t["id"] for t in schedule["tasks"]], ["T01", "T02"])
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest "tests/test_control_plane_state_store.py::ControlPlaneSsotRegression::test_replace_tasks_persists_into_control_plane_and_projects" -v`
Expected: FAIL — `AttributeError: ... 'replace_tasks'`.

- [ ] **Step 4: Implement `replace_tasks`**

Add to `control_plane.py` (after `dispatch_completed`):

```python
def replace_tasks(
    repo: Path,
    run_dir: Path,
    tasks: list[dict],
    lifecycle: str = "",
    gate: str = "",
    gate_status: str = "",
) -> dict:
    """Authoritatively set the control-plane task set, then project outward.

    This is the only sanctioned path for the planner/service-design expansion to
    persist the schedule. Dispatch/claim/completion state is reconciled separately
    from dispatch-events, so we normalise the structural task list here and let
    write_legacy_projections fold the live dispatch state back on top.
    """
    resolved_run_dir = _resolve(repo, run_dir)
    path = control_plane_path(resolved_run_dir)
    if not path.exists():
        imported = import_legacy(repo, resolved_run_dir)
        if not imported.get("ready"):
            return imported
    data = read_json_object(path)
    if not data:
        return {"ready": False, "blocked_reasons": [f"Missing {CONTROL_PLANE_FILE} at {posix(path)}."]}

    normalized = [_normalize_task(task) for task in tasks if isinstance(task, dict)]
    data["tasks"] = normalized

    target = str(lifecycle or "").strip()
    if target:
        # Atomic plan+lifecycle commit so the gate can never lag the schedule (P4 precondition).
        data["lifecycle"] = target
        gates = dict(data.get("gates", {})) if isinstance(data.get("gates"), dict) else {}
        selected_gate = str(gate or "").strip()
        if selected_gate:
            gates[selected_gate] = str(gate_status or "passed")
        data["gates"] = gates
        phase_lock = dict(data.get("phase_lock", {})) if isinstance(data.get("phase_lock"), dict) else {}
        phase_lock["lifecycle"] = target
        data["phase_lock"] = phase_lock

    atomic_write_json(path, data)
    projection = write_legacy_projections(repo, resolved_run_dir)
    return {
        "ready": bool(projection.get("ready")),
        "control_plane_path": posix(path),
        "tasks": len(normalized),
        "lifecycle": data.get("lifecycle", ""),
    }
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest "tests/test_control_plane_state_store.py::ControlPlaneSsotRegression::test_replace_tasks_persists_into_control_plane_and_projects" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py tests/test_control_plane_state_store.py
git commit -m "feat(control-plane): add replace_tasks SSOT write path"
```

---

## Task 3 (P3): Make `write_legacy_projections` non-destructive (the belt that prevents the clobber)

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py` (`write_legacy_projections`, lines 391–426; add a reconcile helper before it)

- [ ] **Step 1: Write the failing test** (this is the direct petalpay scenario — stale control plane, newer on-disk schedule)

```python
    def test_projection_never_drops_tasks_present_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run_dir = self._make_run(tmp)
            # Simulate the legacy failure: agent-schedule.json on disk is AHEAD of the control plane.
            from common import atomic_write_json
            schedule = json.loads((run_dir / "agent-schedule.json").read_text(encoding="utf-8"))
            schedule["tasks"].append(
                control_plane.task_contract("T06", "service-designer-jeepay-core", "design", service="jeepay-core")
            )
            atomic_write_json(run_dir / "agent-schedule.json", schedule)
            # A control->legacy projection (e.g. from dispatch-ack) must reconcile, not erase T06.
            control_plane.write_legacy_projections(repo, run_dir)
            out = json.loads((run_dir / "agent-schedule.json").read_text(encoding="utf-8"))
            self.assertIn("T06", [t["id"] for t in out["tasks"]])
            data = control_plane.load(repo, run_dir)
            self.assertIn("T06", [t["id"] for t in data["tasks"]], "stale control plane must absorb the on-disk task")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest "tests/test_control_plane_state_store.py::ControlPlaneSsotRegression::test_projection_never_drops_tasks_present_on_disk" -v`
Expected: FAIL — `T06` is erased because `_schedule_projection` replaces from `data["tasks"]`.

- [ ] **Step 3: Implement the reconcile guard**

In `control_plane.py`, add before `write_legacy_projections` (line 391):

```python
def _reconcile_on_disk_tasks(data: dict, run_dir: Path) -> dict:
    """Defense-in-depth: never let a stale control plane erase tasks that already
    exist in the on-disk agent-schedule.json. Any task id present on disk but
    missing from the control plane is folded in before projecting."""
    schedule_file = run_dir / "agent-schedule.json"
    on_disk = read_json_object(schedule_file)
    disk_tasks = on_disk.get("tasks") if isinstance(on_disk.get("tasks"), list) else []
    if not disk_tasks:
        return data
    cp_tasks = [task for task in data.get("tasks", []) if isinstance(task, dict)]
    known = {str(task.get("id", "")).strip() for task in cp_tasks}
    appended = False
    for task in disk_tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id", "")).strip()
        if task_id and task_id not in known:
            cp_tasks.append(_normalize_task(task))
            known.add(task_id)
            appended = True
    if appended:
        data["tasks"] = cp_tasks
        data.setdefault("diagnostics", []).append(
            {"code": "control_plane_absorbed_on_disk_tasks", "severity": "warning"}
        )
    return data
```

Then, inside `write_legacy_projections`, insert the reconcile call right after the merge-events line. Change:

```python
    data = _merge_dispatch_events(data, resolved_run_dir)
    atomic_write_json(path, data)
```

to:

```python
    data = _merge_dispatch_events(data, resolved_run_dir)
    data = _reconcile_on_disk_tasks(data, resolved_run_dir)
    atomic_write_json(path, data)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest "tests/test_control_plane_state_store.py::ControlPlaneSsotRegression::test_projection_never_drops_tasks_present_on_disk" -v`
Expected: PASS.

- [ ] **Step 5: Run the Task 1 regression too**

Run: `python -m pytest "tests/test_control_plane_state_store.py::ControlPlaneSsotRegression" -v`
Expected: all PASS (including `test_dispatch_ack_does_not_drop_expanded_schedule`).

- [ ] **Step 6: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py tests/test_control_plane_state_store.py
git commit -m "fix(control-plane): non-destructive projection reconciles on-disk tasks"
```

---

## Task 4 (P2 wiring): CLI `plan` persists the expanded schedule into the control plane

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_dev_harness.py` (the `plan` command around line 661 where `orchestration_plan.agent_schedule(...)` is built and written)
- Test: `tests/test_e2e_dev_harness_scripts.py`

- [ ] **Step 1 (gitnexus):** Run `gitnexus_context({name:"agent_schedule"})` and `gitnexus_impact({target:"agent_schedule", direction:"upstream"})`; confirm the `plan` command is the writer and report risk.

- [ ] **Step 2: Read the exact write site.** Open `e2e_dev_harness.py` around lines 640–700. Identify (a) the `run_dir`, (b) the built `schedule` dict (`schedule["tasks"]`), (c) the lifecycle the plan targets, and (d) where `agent-schedule.json` is written. The new behavior: after the schedule is built, if `control-plane.json` exists in the run dir, call `control_plane.replace_tasks(repo, run_dir, schedule["tasks"], lifecycle=<target>)` instead of (or in addition to, then re-projected) the raw legacy write.

- [ ] **Step 3: Write the failing test** (drives the CLI `plan` to update the control plane). Add to `tests/test_e2e_dev_harness_scripts.py` a test that: builds a run with `control-plane.json` at `CLARIFIED`, invokes the `plan` command entrypoint, then asserts `control-plane.json` `tasks` contains the planned service-design task ids (not just T01). Use the existing CLI-invocation pattern in that file (subprocess or direct `e2e_dev_harness.main([...])`). Expected: FAIL because `plan` currently writes only `agent-schedule.json`.

- [ ] **Step 4: Implement.** At the `plan` write site in `e2e_dev_harness.py`, after `schedule = orchestration_plan.agent_schedule(...)` and after the legacy file is written, add:

```python
from e2e_harness.engine import control_plane as _control_plane  # prefer a top-of-file import
...
run_dir = Path(schedule_path).parent
if (run_dir / "control-plane.json").exists():
    _control_plane.replace_tasks(repo, run_dir, schedule.get("tasks", []), lifecycle=target_lifecycle)
```

Use the module's existing import style (add `from e2e_harness.engine import control_plane` to the imports if not present). `target_lifecycle` is the lifecycle the plan stage advances to (e.g. `SERVICE_DESIGN_REQUIRED` / `PLANNED`); if the plan command does not itself transition lifecycle, pass `lifecycle=""` so only the task set is committed.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest "tests/test_e2e_dev_harness_scripts.py" -k plan_persists_control_plane -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_dev_harness.py tests/test_e2e_dev_harness_scripts.py
git commit -m "fix(plan): persist expanded schedule into control plane (SSOT)"
```

---

## Task 5 (P4): Dispatch phase↔lifecycle guard

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/dispatcher.py` (`dispatch_beat`, after line 1428 where `tasks` is computed)
- Test: `tests/test_e2e_dev_harness_scripts.py`

- [ ] **Step 1 (gitnexus):** Run `gitnexus_impact({target:"dispatch_beat", direction:"upstream"})`; report callers (CLI `dispatch-beat`, `state_store.dispatch_next`).

- [ ] **Step 2: Decide the allow-map.** Reuse `lifecycle_policy`/`agent_roles` if it already maps lifecycle→phases; otherwise add a small helper in `dispatcher.py`. Verify the exact phase strings against the values `control_plane.task_contract`/`agent_roles` actually emit before finalizing:

```python
_LIFECYCLE_ALLOWED_PHASES = {
    "CREATED": {"clarify"},
    "CLARIFIED": {"clarify", "r1-design-review"},
    "SERVICE_DESIGN_REQUIRED": {"service-design", "design"},
    "PLANNED": {"plan", "tdd-red", "r2-review", "plan-tdd-red-r2"},
    "RED_READY": {"implement", "implementation-gate"},
    "IMPLEMENTED": {"implement", "r3-review"},
    "REVIEWED": {"completion"},
}

def _phase_allowed(phase: str, lifecycle: str) -> bool:
    allowed = _LIFECYCLE_ALLOWED_PHASES.get(str(lifecycle).strip())
    if allowed is None:
        return True  # unknown lifecycle: do not block (fail-open, but logged by diagnostics)
    return str(phase).strip() in allowed
```

- [ ] **Step 3: Write the failing test.** A `dispatch_beat`/CLI test: lifecycle=`CLARIFIED`, schedule contains a `design`-phase `T06`; assert the result is `ready:false` (or `T06` appears in `blocked_tasks` with a phase-mismatch reason), and **no** `dispatch-events/T06-dispatched.json` is written. Expected: FAIL (today T06 gets dispatched).

- [ ] **Step 4: Implement the guard.** In `dispatch_beat`, after `tasks, blocked_tasks = ready_tasks(...)` (line 1428), filter:

```python
    guarded = []
    for task in tasks:
        if _phase_allowed(task.get("phase", ""), lifecycle):
            guarded.append(task)
        else:
            blocked_tasks.append({
                "task_id": str(task.get("id", "")),
                "agent": str(task.get("agent", "")),
                "phase": task.get("phase", ""),
                "parallel_group": task_parallel_group(task),
                "blocked_reasons": [
                    f"phase '{task.get('phase','')}' not permitted in lifecycle '{lifecycle}'."
                ],
            })
    tasks = guarded
```

This sits before the `if not tasks:` early-return so a fully-blocked beat returns the blocked reasons.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest "tests/test_e2e_dev_harness_scripts.py" -k dispatch_phase_guard -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/e2e-dev-harness/scripts/dispatcher.py tests/test_e2e_dev_harness_scripts.py
git commit -m "fix(dispatch): block tasks whose phase does not match lifecycle"
```

---

## Task 6 (P1 + P5): Authority map + stale-transaction GC + divergence diagnostic

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/harness_doctor.py` (authority line 839; add divergence check near the other `state-*` checks)
- Modify: `skills/e2e-dev-harness/scripts/navigation_map.py` (authority default line 143)
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py` (`transition_lifecycle`: close clarify-scope transactions when leaving CLARIFIED)
- Test: `tests/test_control_plane_state_store.py`, `tests/test_harness_advice.py` or `tests/test_e2e_dev_harness_scripts.py`

- [ ] **Step 1 (P1) Flip authority — write the failing test.** Add a test asserting the doctor/navigation authority map reports `primary == "control-plane.json"`. Expected: FAIL (currently `run-state.json`).

- [ ] **Step 2 (P1) Implement.** In `harness_doctor.py:839-841`:

```python
        "authority": {
            "primary": control_plane.CONTROL_PLANE_FILE,
            "derived": ["run-state.json", "agent-schedule.json", run_state.PHASE_LOCK, "coordinator-summary.json"],
            "audit": ["dispatch-events", "events"],
        },
```

In `navigation_map.py:142-145` default block, set `"primary": "control-plane.json"` and move `run-state.json` into `derived`.

- [ ] **Step 3 (P5 GC) Write the failing test.** After `transition_lifecycle(... "SERVICE_DESIGN_REQUIRED")`, any `repair_transactions` with a clarify/`impact_summary_too_long` scope and `status` still `opened` must become `superseded`/`closed`. Expected: FAIL (transitions never touch transactions today).

- [ ] **Step 4 (P5 GC) Implement.** In `control_plane.py` `transition_lifecycle`, before `atomic_write_json(path, data)` (line 485), add:

```python
    if target not in {"CREATED", "CLARIFIED"}:
        transactions = data.get("repair_transactions") if isinstance(data.get("repair_transactions"), dict) else {}
        for transaction in transactions.values():
            if isinstance(transaction, dict) and _active_transaction(transaction):
                if str(transaction.get("repair_code", "")) == "impact_summary_too_long":
                    transaction["status"] = "superseded"
                    transaction["closed_at"] = now_iso()
        data["repair_transactions"] = transactions
```

- [ ] **Step 5 (P5 divergence) Write the failing test.** Construct a control plane where `dispatch.current_task_id="T06"` but `tasks` has no `T06` (the limbo). Assert the doctor’s checks include a `state-control-plane-divergence` entry with `status:"fail"` and that it is selected as `primary_blocker_code` over `control-plane-repair-transaction-stale`. Expected: FAIL.

- [ ] **Step 6 (P5 divergence) Implement.** In `harness_doctor.py`, where the `state-control-plane` checks are assembled, add a check:

```python
    dispatched_id = str((data.get("dispatch") or {}).get("current_task_id", "")).strip()
    task_ids = {str(t.get("id", "")).strip() for t in data.get("tasks", []) if isinstance(t, dict)}
    if dispatched_id and dispatched_id not in task_ids:
        checks.append({
            "name": "state-control-plane-divergence",
            "status": "fail",
            "severity": "error",
            "message": (
                f"control-plane-divergence: dispatch references task '{dispatched_id}' "
                f"that is not in the control-plane task set; schedule and dispatch state have split."
            ),
        })
```

Ensure the blocker-selection logic ranks `state-control-plane-divergence` ahead of `state-control-plane` (the stale-transaction message) so the primary blocker reported is the real one. Once GC exists, downgrade the stale-transaction message to `warning` if it is no longer a true blocker.

- [ ] **Step 7: Run all touched tests**

Run: `python -m pytest tests/test_control_plane_state_store.py tests/test_harness_advice.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add skills/e2e-dev-harness/scripts/harness_doctor.py skills/e2e-dev-harness/scripts/navigation_map.py skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py tests/
git commit -m "fix(diagnostics): control-plane authority + stale-tx GC + divergence check"
```

---

## Task 7: Full suite + change verification + recovery runbook (no petalpay writes)

**Files:**
- Create: `docs/agent-runs-recovery/2026-06-06-feature-recovery.md`

- [ ] **Step 1: Run the full harness test suite**

Run: `python -m pytest tests/ -q`
Expected: PASS. Some existing tests assert the OLD contract (`authority.primary == "run-state.json"`, or that `write_legacy_projections` replaces rather than merges the schedule). Update those tests to the new contract — do **not** weaken the new guards to satisfy a stale assertion.

- [ ] **Step 2 (gitnexus): Verify change scope**

Run `gitnexus_detect_changes()` and confirm only the intended symbols changed (`replace_tasks`, `_reconcile_on_disk_tasks`, `write_legacy_projections`, `transition_lifecycle`, `dispatch_beat`, authority maps, divergence check). Report affected processes.

- [ ] **Step 3: Write the recovery runbook** (documentation only — the user chose not to touch the live run). Document the exact, idempotent recovery for `petalpay/docs/agent-runs/2026-06-06-feature` once the fixed harness ships:
  1. Back up the run dir.
  2. Re-run `plan` (now SSOT-writing) to rebuild `control-plane.json` `tasks` + lifecycle from the design doc, OR rebuild `tasks` from `coordinator-results/20260607T073351Z-plan.json` + `dispatch-events/` and call `control_plane.replace_tasks`.
  3. Resolve T06: either honor the existing `service-designs/jeepay-core.md` via a trustworthy `dispatch-complete` (writes `T06-completed.json`), or discard the phantom dispatch and re-dispatch under the new phase guard.
  4. Run `next` and confirm `state_confidence != blocked` and no `state-control-plane-divergence`.

- [ ] **Step 4: Commit**

```bash
git add docs/agent-runs-recovery/2026-06-06-feature-recovery.md
git commit -m "docs: petalpay 2026-06-06-feature SSOT recovery runbook"
```

---

## Self-Review

**Spec coverage:**
- P1 (authority) → Task 6 Steps 1–2.
- P2 (planner writes control plane) → Task 2 (`replace_tasks`) + Task 4 (CLI wiring).
- P3 (non-destructive projection) → Task 3.
- P4 (dispatch phase guard) → Task 5; atomic plan+lifecycle commit → `replace_tasks` lifecycle arg (Task 2).
- P5 (stale-tx GC + real divergence diagnosis) → Task 6 Steps 3–6.
- Recovery (out-of-scope for live writes) → Task 7 Step 3 (doc only).

**Type consistency:** `replace_tasks(repo, run_dir, tasks, lifecycle="", gate="", gate_status="")` is used identically in Tasks 1, 2, 4. `_reconcile_on_disk_tasks(data, run_dir)`, `_phase_allowed(phase, lifecycle)` consistent across references. `control_plane.CONTROL_PLANE_FILE` is the existing constant (`"control-plane.json"`).

**Placeholder scan:** Tasks 4 and 5 Steps 2 require reading the exact CLI/dispatcher write site (the precise lifecycle variable name and CLI entrypoint) before writing the test — deliberate in-context verification, not a placeholder; the implementation code and assertions are otherwise fully specified.

**Known residual risk:** Existing tests asserting the old `authority.primary == "run-state.json"` or asserting `write_legacy_projections` replaces (not merges) the schedule will need updating to the new contract in Task 7 Step 1. That is expected and correct, not a regression.
