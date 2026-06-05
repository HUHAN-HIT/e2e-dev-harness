# Dispatch Hook Explicit Blocking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix dispatch auto-spawn confusion by replacing hook-missing silent manual downgrade with explicit blocking guidance and a single next action.

**Architecture:** Keep the change inside the dispatch entry wrapper and preflight-style result shape. Do not change the high-risk `runtime_adapters.adapter_for` unknown-runtime fallback in this slice.

**Tech Stack:** Python, `unittest`, GitNexus impact/detect-changes, existing `coordinator_flow.py`, `preflight.py`, `test_orchestration.py`, and `test_preflight_aggregator.py`.

---

### Task 1: Convert Hook-Missing Dispatch Behavior To A Failing Regression Test

**Files:**
- Modify: `tests/test_orchestration.py`

- [ ] **Step 1: Replace the old waiting-dispatch expectation**

Change `test_cli_dispatch_next_forces_waiting_dispatch_when_hooks_are_missing` so it expects an explicit blocked dispatch result:

```python
self.assertEqual(2, code)
self.assertFalse(result["ready"])
self.assertIn("hook_status", result)
self.assertEqual("generic", result["hook_status"]["runtime"])
self.assertTrue(any("install_hooks" in reason for reason in result["blocked_reasons"]))
self.assertEqual("PLANNED", updated["lifecycle"])
self.assertNotIn("runtime_spawn_request", result)
self.assertNotIn("dispatch", result)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m unittest discover -s tests -p test_orchestration.py -k test_cli_dispatch_next_forces_waiting_dispatch_when_hooks_are_missing
```

Expected: FAIL because current code still returns `waiting_dispatch`.

### Task 2: Add Preflight-Style Hook Blocking In Dispatch Wrapper

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/coordinator_flow.py`

- [ ] **Step 1: Add explicit hook block result after budget gate passes**

In `_dispatch_with_hook_guard`, after `hooks = runtime_hook_status(repo)`, keep user-selected manual as manual, but block generic or unready hooks for non-manual runtime:

```python
runtime = args.runtime
explicit_manual = str(runtime or "").strip().lower().replace("_", "-") == "manual"
forced_waiting = hooks.get("runtime") == "generic" or not hooks.get("ready", False)
if forced_waiting and not explicit_manual:
    result = {
        "repo": str(repo),
        "ready": False,
        "blocked_reasons": [
            "Runtime hook is not ready for automatic dispatch; run install_hooks for the selected runtime before dispatching workers."
        ],
        "warnings": hooks.get("warnings", []),
        "hook_status": hooks,
        "coordinator_context_budget": budget_gate["coordinator_context_budget"],
        "session_checkpoint": budget_gate["session_checkpoint"],
        "next_required": {
            "command": "python skills/e2e-dev-harness/scripts/install_hooks.py --runtime claude",
            "reason": "install runtime hooks before automatic worker dispatch",
        },
        "next_single_action": "Run install_hooks --runtime claude before dispatch-beat/dispatch-next.",
    }
    write_status(args.status_file, result)
    return 2, result
if forced_waiting:
    runtime = "manual"
```

- [ ] **Step 2: Run the focused test and verify GREEN**

Run:

```powershell
python -m unittest discover -s tests -p test_orchestration.py -k test_cli_dispatch_next_forces_waiting_dispatch_when_hooks_are_missing
```

Expected: PASS.

### Task 3: Extend Preflight Aggregator Coverage For Hook Readiness

**Files:**
- Modify: `tests/test_preflight_aggregator.py`
- Modify: `skills/e2e-dev-harness/scripts/preflight.py`

- [ ] **Step 1: Add failing preflight test**

Add a test showing a run with missing runtime hook reports one single next action:

```python
def test_missing_runtime_hook_blocks_preflight_with_install_guidance(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        state = _write_state(repo, "PLANNED")

        result = harness.aggregate_preflight_blockers(repo, state)

    self.assertFalse(result["ready"])
    blocker = result["blockers"][0]
    self.assertEqual("runtime_hook", blocker["gate"])
    self.assertEqual("BLK_RUNTIME_HOOK", blocker["code"])
    self.assertIn("install_hooks", blocker["minimal_fix"])
    self.assertEqual(blocker["minimal_fix"], result["next_single_action"])
```

- [ ] **Step 2: Run the focused preflight test and verify RED**

Run:

```powershell
python -m unittest discover -s tests -p test_preflight_aggregator.py -k test_missing_runtime_hook_blocks_preflight_with_install_guidance
```

Expected: FAIL because preflight does not check hook readiness yet.

- [ ] **Step 3: Add a local hook-readiness check without importing coordinator_flow**

In `preflight.py`, add a small helper that detects missing project hook config using filesystem facts to avoid circular imports:

```python
def runtime_hook_blockers(repo: Path, run_state_path: Path | str | None) -> list[str]:
    _ = run_state_path
    if (repo / ".claude" / "settings.json").exists() or (repo / ".opencode" / "plugins" / "e2e-dev-harness.js").exists():
        return []
    return [
        "Runtime hook config is missing; automatic dispatch cannot spawn workers until install_hooks configures the runtime."
    ]
```

Register it before phase-specific dispatch checks:

```python
{
    "gate": "runtime_hook",
    "code": "BLK_RUNTIME_HOOK",
    "return_phase": "CREATED",
    "minimal_fix": "Run install_hooks --runtime claude before dispatch-beat/dispatch-next.",
    "fn": runtime_hook_blockers,
},
```

- [ ] **Step 4: Run preflight tests and verify GREEN**

Run:

```powershell
python -m unittest discover -s tests -p test_preflight_aggregator.py
```

Expected: PASS.

### Task 4: Focused Regression Verification And Impact Review

**Files:**
- Read only after edits.

- [ ] **Step 1: Run focused orchestration tests**

Run:

```powershell
python -m unittest discover -s tests -p test_orchestration.py -k "dispatch_next_forces_waiting_dispatch_when_hooks_are_missing or dispatch_budget_gate_blocks_when_waves_exceed_without_fresh_checkpoint"
```

Expected: PASS.

- [ ] **Step 2: Run harness architecture anchor tests**

Run:

```powershell
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py
```

Expected: PASS.

- [ ] **Step 3: Run GitNexus detect changes**

Run GitNexus detect-changes for unstaged changes and confirm affected flows are limited to dispatch/preflight behavior.

- [ ] **Step 4: Run broader verification if focused checks pass**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: PASS or report unrelated pre-existing failures separately from this fix.

### Out Of Scope

- Do not change `runtime_adapters.adapter_for` unknown runtime fallback in this slice. GitNexus marks that symbol CRITICAL because it affects dispatcher, dispatch engine, state store, adapter contract tests, and runtime-specific adapters.
- Do not modify user-owned pending files `AGENTS.md`, `CLAUDE.md`, or the existing `docs/analysis/` content except as explicitly requested.
