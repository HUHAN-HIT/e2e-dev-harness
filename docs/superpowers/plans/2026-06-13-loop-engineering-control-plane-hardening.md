# Loop Engineering Control Plane Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the Loop Engineering hardening gaps that block honest productization: verification replay coverage, grounded delivery status, safe module fan-out, read-only run diagnosis, and tamper-evident event truth.

**Architecture:** Keep `run-state.json` as the compatibility projection while tightening the evidence and scheduling contracts around it. Add small, testable seams: replay allow-list branches in evidence validation, module grounding in scope validation, conflict-group filtering in multitrack scheduling, namespace ownership checks in evidence submission, a separate `doctor --state` diagnosis path, and a chained event log before any branding or UI work.

**Tech Stack:** Python stdlib, existing `e2e_harness` modules, pytest/unittest tests under `skills/e2e-dev-harness/tests`, GitNexus impact analysis for symbol edits.

---

## Preconditions

- Before modifying any function, class, or method, run GitNexus impact analysis for that symbol and record the risk in the worker handoff.
- Keep existing CLI JSON shapes stable unless the task explicitly introduces a new `--state` schema.
- Do not edit worker-owned artifacts or generated run outputs as part of these implementation tasks.
- Use repo-local temp settings for Windows test runs when broad tests are needed: `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, `TMP=.test-tmp`, `TEMP=.test-tmp`, and `--basetemp=.test-tmp/<slice>`.

## File Structure

- Modify `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/validate.py`: extend replay command allow-list while preserving strict test-command checks.
- Modify `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/scope.py`: ground delivered module ids from run-state rather than trusting `phases` self-report.
- Modify `skills/e2e-dev-harness/scripts/e2e_harness/core/module_plan.py`: accept optional `conflict_groups` as named shared resources and expose them to scheduling.
- Modify `skills/e2e-dev-harness/scripts/e2e_harness/core/multitrack.py`: filter module fan-out by declared conflict groups without repo I/O.
- Modify `skills/e2e-dev-harness/scripts/e2e_harness/core/engine.py`: add module namespace ownership validation for evidence submission when worker identity is supplied.
- Modify `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/submit.py`: pass worker identity to `submit_evidence` when invocation metadata is available.
- Modify `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/doctor.py`: keep default installer readiness behavior and add `--state` run diagnosis dispatch.
- Create `skills/e2e-dev-harness/scripts/e2e_harness/core/state_diagnosis.py`: compute first blocking run fact without mutation or replay.
- Create `skills/e2e-dev-harness/scripts/e2e_harness/core/event_log.py`: append canonical chained events and verify event chains.
- Create `skills/e2e-dev-harness/scripts/e2e_harness/core/state_store.py`: replay event chains into compatibility projections.
- Add or extend tests in `skills/e2e-dev-harness/tests/test_evidence_validation.py`, `test_scope_evidence.py`, `test_module_plan.py`, `test_multitrack.py`, `test_submit_evidence.py`, `test_cli_doctor.py`, and `test_event_log.py`.

### Task 1: Verification Replay Allow-List

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/validate.py:95`
- Test: `skills/e2e-dev-harness/tests/test_evidence_validation.py`

- [ ] **Step 1: Run impact analysis**

Run:

```powershell
gitnexus_impact target="_replay_command_allowed" direction="upstream" repo="e2e-dev-workflow"
```

Expected: risk is reviewed before editing. If risk is HIGH or CRITICAL, stop and report the blast radius before changing code.

- [ ] **Step 2: Write failing allow-list tests**

Add tests that assert these commands are allowed:

```python
def test_replay_allows_first_class_test_commands():
    allowed = [
        "go test ./...",
        "cargo test --all",
        "pnpm test",
        "pnpm run test",
        "yarn test",
        "yarn run test",
        "npx jest --runInBand",
        "npx jest test",
    ]
    for command in allowed:
        assert validate._replay_command_allowed(command), command
```

Add tests that assert non-test commands stay blocked:

```python
def test_replay_rejects_non_test_commands_for_new_runners():
    rejected = [
        "go build ./...",
        "cargo build",
        "pnpm install",
        "yarn add lodash",
        "npx jest --init",
    ]
    for command in rejected:
        assert not validate._replay_command_allowed(command), command
```

- [ ] **Step 3: Run the focused failing tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_evidence_validation.py -q
```

Expected: new allowed-command cases fail with `AssertionError`.

- [ ] **Step 4: Implement strict branches**

Update `_replay_command_allowed` with conservative branches:

```python
    if name == "go":
        return args[:1] == ["test"]
    if name == "cargo":
        return "test" in args
    if name in {"pnpm", "yarn"}:
        return args[:1] == ["test"] or args[:2] == ["run", "test"]
    if name == "npx":
        return bool(args) and (
            (_command_name(args[0]) in _NODE_TEST_COMMANDS and "test" in args[1:])
            or _command_name(args[0]) == "jest"
        )
```

Keep the existing Python, npm, node, Maven and Gradle behavior unchanged.

- [ ] **Step 5: Verify focused tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_evidence_validation.py -q
```

Expected: all tests in the file pass.

### Task 2: Ground Delivered Modules In Scope Manifest

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/scope.py:34`
- Test: `skills/e2e-dev-harness/tests/test_scope_evidence.py`

- [ ] **Step 1: Run impact analysis**

Run:

```powershell
gitnexus_impact target="_ground" direction="upstream" repo="e2e-dev-workflow"
gitnexus_impact target="label_delivery" direction="upstream" repo="e2e-dev-workflow"
```

Expected: blast radius is recorded before editing.

- [ ] **Step 2: Write failing module-grounding tests**

Add a test where `expected.phases` contains module ids and `delivered.phases` overclaims a missing module:

```python
def test_scope_manifest_rejects_ungrounded_delivered_module(tmp_path):
    state = {
        "phases": {
            "VERIFIED#auth": {"dispatch": "done", "evidence": {"verification#auth": {"path": "x"}}},
        }
    }
    manifest = {
        "schema": "e2e-dev-harness.scope-manifest.v1",
        "status": "COMPLETE",
        "expected": {"phases": ["auth", "billing"]},
        "delivered": {"phases": ["auth", "billing"]},
        "state": state,
    }
    ok, reason = scope.validate_scope_manifest(manifest, tmp_path)
    assert not ok
    assert reason == "overclaims-complete:phases:billing"
```

Add a passing test for a truthful partial manifest:

```python
def test_scope_manifest_allows_truthful_partial_module_delivery(tmp_path):
    state = {
        "phases": {
            "VERIFIED#auth": {"dispatch": "done", "evidence": {"verification#auth": {"path": "x"}}},
        }
    }
    manifest = {
        "schema": "e2e-dev-harness.scope-manifest.v1",
        "status": "PARTIAL",
        "expected": {"phases": ["auth", "billing"]},
        "delivered": {"phases": ["auth", "billing"]},
        "state": state,
    }
    ok, reason = scope.validate_scope_manifest(manifest, tmp_path)
    assert ok, reason
```

- [ ] **Step 3: Run the focused failing tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_scope_evidence.py -q
```

Expected: the overclaim test fails because current grounding trusts `delivered.phases`.

- [ ] **Step 4: Implement module grounding**

Add a helper that derives completed module ids from module-scoped VERIFIED records:

```python
def _completed_modules_from_state(state: dict) -> set[str]:
    completed: set[str] = set()
    for name, record in (state.get("phases") or {}).items():
        if not isinstance(name, str) or not name.startswith("VERIFIED#"):
            continue
        module_id = name.split("#", 1)[1]
        if record.get("dispatch") == "done" and record.get("evidence"):
            completed.add(module_id)
    return completed
```

Thread optional state into `_ground` and `_effective`, then filter `phases`:

```python
def _ground(delivered: dict, repo_root, state: dict | None = None) -> dict:
    grounded = dict(delivered)
    tables = delivered.get("tables") or []
    if tables:
        sql = _all_sql_text(repo_root)
        grounded["tables"] = [t for t in tables if _ddl_present(t, sql)]
    phases = delivered.get("phases") or []
    if phases and state is not None:
        completed = _completed_modules_from_state(state)
        grounded["phases"] = [p for p in phases if p in completed]
    return grounded
```

Read `state` from the manifest object so validation and labeling use the same snapshot:

```python
def _effective(obj, repo_root) -> tuple[str, dict]:
    grounded = _ground(obj.get("delivered", {}), repo_root, obj.get("state"))
    return scope_core.assess(obj.get("expected", {}), grounded)
```

- [ ] **Step 5: Verify focused tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_scope_evidence.py -q
```

Expected: scope evidence tests pass.

### Task 3: Module Fan-Out Safety Floor

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/module_plan.py:35`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/multitrack.py:92`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/engine.py:15`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/submit.py`
- Test: `skills/e2e-dev-harness/tests/test_module_plan.py`
- Test: `skills/e2e-dev-harness/tests/test_multitrack.py`
- Test: `skills/e2e-dev-harness/tests/test_submit_evidence.py`

- [ ] **Step 1: Run impact analysis**

Run:

```powershell
gitnexus_impact target="validate_module_plan" direction="upstream" repo="e2e-dev-workflow"
gitnexus_impact target="ready_frontier" direction="upstream" repo="e2e-dev-workflow"
gitnexus_impact target="submit_evidence" direction="upstream" repo="e2e-dev-workflow"
```

Expected: blast radius is reviewed before editing. If any result is HIGH or CRITICAL, report before edits.

- [ ] **Step 2: Write failing conflict-group tests**

Add module-plan validation tests:

```python
def test_module_plan_accepts_conflict_groups():
    obj = {
        "schema": module_plan.SCHEMA,
        "modules": [
            {
                "id": "auth",
                "name": "Auth",
                "depends_on": [],
                "acceptance_ids": ["AC-001"],
                "conflict_groups": ["db:migrations", "npm:lockfile"],
            }
        ],
    }
    assert module_plan.validate_module_plan(obj) == (True, None)
```

Add a scheduler test:

```python
def test_ready_frontier_withholds_shared_conflict_group():
    mplan = {
        "modules": [
            {"id": "auth", "name": "Auth", "depends_on": [], "acceptance_ids": ["AC-001"], "conflict_groups": ["db:migrations"]},
            {"id": "billing", "name": "Billing", "depends_on": [], "acceptance_ids": ["AC-002"], "conflict_groups": ["db:migrations"]},
        ]
    }
    frontier = multitrack.ready_frontier(spine, {"phases": {}}, mplan)
    assert [p.name for p in frontier] == ["RED#auth"]
```

- [ ] **Step 3: Write failing ownership tests**

Add a direct engine-level test:

```python
def test_submit_evidence_rejects_cross_module_worker_claim():
    state = {}
    with pytest.raises(ValueError, match="worker-module-mismatch"):
        engine.submit_evidence(
            state,
            "IMPLEMENTED#billing",
            "passing_tests#billing",
            "handoffs/IMPLEMENTED-passing_tests.json",
            worker_id="IMPLEMENTED#auth",
        )
```

- [ ] **Step 4: Run focused failing tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_module_plan.py skills/e2e-dev-harness/tests/test_multitrack.py skills/e2e-dev-harness/tests/test_submit_evidence.py -q
```

Expected: new conflict-group and ownership tests fail.

- [ ] **Step 5: Implement conflict-group validation**

In `module_plan._validate_module`, accept optional string lists:

```python
    groups = mod.get("conflict_groups", [])
    if not isinstance(groups, list) or not all(isinstance(g, str) and g.strip() for g in groups):
        return mid, f"bad-conflict-groups:{mid}"
```

Add a helper:

```python
def conflict_groups(obj) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = {}
    for mod in obj.get("modules", []):
        if isinstance(mod, dict) and "id" in mod:
            groups[mod["id"]] = set(mod.get("conflict_groups", []) or [])
    return groups
```

- [ ] **Step 6: Implement cheap frontier filtering**

In `ready_frontier`, after computing candidate phases, keep deterministic order and withhold later modules that share a conflict group with an already selected module:

```python
    groups = {
        m["id"]: set(m.get("conflict_groups", []) or [])
        for m in mplan.get("modules", [])
        if isinstance(m, dict) and "id" in m
    }
    selected: list[Phase] = []
    active_groups: set[str] = set()
    for phase in frontier:
        mid = module_of(phase.name)
        phase_groups = groups.get(mid or "", set())
        if active_groups.intersection(phase_groups):
            continue
        selected.append(phase)
        active_groups.update(phase_groups)
    return selected
```

- [ ] **Step 7: Implement namespace ownership guard**

Extend `submit_evidence` with optional `worker_id`:

```python
def _module_suffix(value: str) -> str | None:
    return value.split("#", 1)[1] if "#" in value else None
```

```python
    phase_module = _module_suffix(phase_name)
    key_module = _module_suffix(key)
    worker_module = _module_suffix(worker_id or "")
    if phase_module and key_module and phase_module != key_module:
        raise ValueError("phase-key-module-mismatch")
    if phase_module and worker_module and phase_module != worker_module:
        raise ValueError("worker-module-mismatch")
```

Pass `worker_id` from `submit.py` only when the CLI has a trusted invocation/worker identity. Manual runtime without identity remains explicit residual risk and should not invent a fake worker id.

- [ ] **Step 8: Verify focused tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_module_plan.py skills/e2e-dev-harness/tests/test_multitrack.py skills/e2e-dev-harness/tests/test_submit_evidence.py -q
```

Expected: all focused tests pass.

### Task 4: Read-Only `doctor --state`

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/doctor.py:8`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/main.py`
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/core/state_diagnosis.py`
- Test: `skills/e2e-dev-harness/tests/test_cli_doctor.py`

- [ ] **Step 1: Run impact analysis**

Run:

```powershell
gitnexus_impact target="run" file_path="skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/doctor.py" direction="upstream" repo="e2e-dev-workflow"
```

Expected: blast radius is reviewed before editing.

- [ ] **Step 2: Write compatibility tests**

Add a test that default `doctor` remains installer readiness:

```python
def test_doctor_default_schema_remains_installer_readiness(tmp_path):
    args = SimpleNamespace(project_root=str(tmp_path), runtime="claude", strict=False, state=False)
    code, payload = doctor.run(args)
    assert code == 0
    assert payload["schema"] == "e2e-dev-harness.doctor.v1"
    assert "checks" in payload
```

Add a test for `doctor --state`:

```python
def test_doctor_state_reports_first_missing_evidence(tmp_path):
    run_state = tmp_path / "run-state.json"
    run_state.write_text(json.dumps({
        "schema": "e2e-dev-harness.run-state.v1",
        "current_phase": "IMPLEMENTED",
        "phases": {"IMPLEMENTED": {"evidence": {}}},
    }), encoding="utf-8")
    args = SimpleNamespace(project_root=str(tmp_path), runtime="claude", strict=False, state=True, run_state=str(run_state))
    code, payload = doctor.run(args)
    assert code == 2
    assert payload["schema"] == "e2e-dev-harness.doctor-state.v1"
    assert payload["diagnosis_ready"] is True
    assert payload["run_blocked"] is True
    assert payload["first_fault"]["kind"] == "missing_evidence"
    assert payload["next_legal_command"]
```

- [ ] **Step 3: Run focused failing tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_cli_doctor.py -q
```

Expected: `--state` test fails because no state diagnosis path exists.

- [ ] **Step 4: Implement `state_diagnosis.py`**

Create a pure diagnosis function:

```python
def diagnose_run(state: dict, run_dir: Path) -> dict:
    current = state.get("current_phase")
    rec = (state.get("phases") or {}).get(current or "", {})
    evidence = rec.get("evidence") or {}
    required = _required_keys_for_phase(current)
    missing = [key for key in required if key not in evidence]
    first = None
    if missing:
        first = {
            "kind": "missing_evidence",
            "phase": current,
            "task_id": None,
            "message": f"{missing[0]} evidence is missing",
        }
    return {
        "schema": "e2e-dev-harness.doctor-state.v1",
        "diagnosis_ready": True,
        "run_blocked": bool(first),
        "run_dir": str(run_dir),
        "first_fault": first,
        "blocked_phase": current if first else None,
        "blocked_task": None,
        "missing_evidence": missing,
        "next_legal_command": f"e2e-harness dispatch-beat --run-dir {run_dir}" if first else None,
        "coordinator_may_write_worker_outputs": False,
    }
```

Use existing lifecycle catalog/spine helpers for `_required_keys_for_phase` rather than duplicating phase constants.

- [ ] **Step 5: Wire CLI args**

Add parser fields for `doctor --state --run-state <path>` in `cli/main.py`, and branch in `doctor.run(args)`:

```python
    if bool(getattr(args, "state", False)):
        return _run_state_diagnosis(args)
```

Default `doctor` behavior must remain byte-compatible for installer tests.

- [ ] **Step 6: Verify focused tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_cli_doctor.py -q
```

Expected: doctor tests pass.

### Task 5: Tamper-Evident Event Log

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/core/event_log.py`
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/core/state_store.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/run_state.py`
- Test: `skills/e2e-dev-harness/tests/test_event_log.py`

- [ ] **Step 1: Run impact analysis**

Run:

```powershell
gitnexus_impact target="mutate" file_path="skills/e2e-dev-harness/scripts/e2e_harness/core/run_state.py" direction="upstream" repo="e2e-dev-workflow"
```

Expected: blast radius is reviewed before editing.

- [ ] **Step 2: Write event-chain tests**

Add tests for append and verify:

```python
def test_event_log_detects_modified_event(tmp_path):
    path = tmp_path / "events.jsonl"
    first = event_log.append_event(path, {"type": "run.started", "run_id": "r1"})
    second = event_log.append_event(path, {"type": "gate.passed", "run_id": "r1", "phase": "CLARIFIED"})
    assert first["event_hash"]
    assert second["prev_event_hash"] == first["event_hash"]
    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = lines[1].replace("gate.passed", "gate.failed")
    path.write_text(lines[0] + "\n" + tampered + "\n", encoding="utf-8")
    ok, reason = event_log.verify_chain(path)
    assert not ok
    assert reason == "event-hash-mismatch:2"
```

Add tests for deletion/reordering:

```python
def test_event_log_detects_reordered_event(tmp_path):
    path = tmp_path / "events.jsonl"
    event_log.append_event(path, {"type": "run.started", "run_id": "r1"})
    event_log.append_event(path, {"type": "phase.submitted", "run_id": "r1", "phase": "CLARIFIED"})
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text(lines[1] + "\n" + lines[0] + "\n", encoding="utf-8")
    ok, reason = event_log.verify_chain(path)
    assert not ok
    assert reason.startswith("event-chain-broken")
```

- [ ] **Step 3: Run focused failing tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_event_log.py -q
```

Expected: import or function-not-found failure.

- [ ] **Step 4: Implement canonical event log**

Create canonical serialization:

```python
def _canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

Create event hashing:

```python
def _hash_event(payload: dict) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
```

Append events with sequence and previous hash:

```python
def append_event(path: Path, payload: dict) -> dict:
    events = read_events(path)
    prev = events[-1]["event_hash"] if events else None
    event = dict(payload)
    event["schema"] = "e2e-dev-harness.event.v1"
    event["sequence"] = len(events) + 1
    event["prev_event_hash"] = prev
    event["event_hash"] = _hash_event({k: v for k, v in event.items() if k != "event_hash"})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(_canonical(event) + "\n")
    return event
```

Verify chains by recomputing `sequence`, `prev_event_hash`, and `event_hash`.

- [ ] **Step 5: Implement projection replay shell**

In `state_store.py`, add a narrow replay function for the first event set:

```python
def replay_events(events: list[dict]) -> dict:
    state = {"phases": {}}
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
    return state
```

- [ ] **Step 6: Verify focused tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_event_log.py -q
```

Expected: event log tests pass.

### Final Verification

- [ ] **Step 1: Run affected Python tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_evidence_validation.py skills/e2e-dev-harness/tests/test_scope_evidence.py skills/e2e-dev-harness/tests/test_module_plan.py skills/e2e-dev-harness/tests/test_multitrack.py skills/e2e-dev-harness/tests/test_submit_evidence.py skills/e2e-dev-harness/tests/test_cli_doctor.py skills/e2e-dev-harness/tests/test_event_log.py -q
```

Expected: all affected tests pass.

- [ ] **Step 2: Run GitNexus change detection**

Run:

```powershell
gitnexus_detect_changes scope="all" repo="e2e-dev-workflow"
```

Expected: affected symbols match this plan: evidence validation, scope validation, multitrack scheduling, submit evidence, doctor diagnosis, event log/state store.

- [ ] **Step 3: Run package-surface checks when ready to ship**

Run:

```powershell
npm pack --dry-run
```

Expected: new source/test/docs files intended for package or repo review appear as expected; generated temp files do not appear.
