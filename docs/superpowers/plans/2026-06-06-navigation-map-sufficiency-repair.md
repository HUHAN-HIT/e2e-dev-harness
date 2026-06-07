# Navigation Map Sufficiency Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `e2e-harness next` / `map` tell agents the minimal trusted state, blocker source, required evidence, and files to read so they do not repeatedly rediscover run-state, schedule, phase-lock, summary, and event-log facts by hand.

**Architecture:** Keep `navigation_map.py` read-only and derived. Reuse existing doctor/state-consistency logic through a compact diagnostic projection instead of creating a new state owner. Preserve compact stdout compatibility by adding high-signal fields to the map and storing fuller diagnostics in `full_result_path` and `coordinator-summary.json`.

**Tech Stack:** Python stdlib, existing harness modules under `skills/e2e-dev-harness/scripts`, `unittest`, GitNexus impact/detect-changes workflow.

---

## File Structure

- Modify `skills/e2e-dev-harness/scripts/navigation_map.py`
  - Owns the read-only map schema and field normalization.
  - Add compact `state_confidence`, `diagnostics`, `must_read_paths`, and `authority` sections.
- Modify `skills/e2e-dev-harness/scripts/coordinator_flow.py`
  - Calls a read-only diagnostic projection during `evaluate_navigation_state()`.
  - Passes the diagnostic summary into `navigation_map.build()`.
- Modify `skills/e2e-dev-harness/scripts/harness_doctor.py`
  - Extract a small reusable read-only helper for state consistency summaries without changing doctor exit semantics.
- Modify `skills/e2e-dev-harness/scripts/coordinator_summary.py`
  - Persist the expanded map additively with bounded fields.
- Modify `skills/e2e-dev-harness/scripts/output_contract.py`
  - Keep compact stdout under budget while exposing high-signal navigation fields.
- Modify `tests/test_enterprise_harness_architecture.py`
  - Contract tests for map shape, shared evaluator behavior, and coordinator summary persistence.
- Modify `tests/test_harness_doctor.py`
  - Tests for the reusable state diagnostic helper.
- Modify `tests/test_unified_cli.py`
  - Compact/full stdout parity and truncation behavior.
- Optional docs update `README.md`
  - Document the new map sections only after behavior is tested.

## Implementation Notes

- Run GitNexus impact analysis before editing each target symbol:
  - `navigation_map.build`
  - `coordinator_flow.evaluate_navigation_state`
  - `harness_doctor.state_consistency_checks`
  - `coordinator_summary._compact_navigation_map`
  - `output_contract._compact_navigation_map`
- If any impact result is HIGH or CRITICAL, stop and report the blast radius before editing.
- Do not make `navigation_map.py` write files, transition lifecycle, or repair projections.
- Do not call full `harness_doctor.evaluate()` from `next` if it introduces heavyweight unrelated checks. Extract a narrow helper that only reads the active run directory state surfaces.
- Keep the default stdout compact. The goal is better pointers and confidence, not dumping every blocker into chat.

---

### Task 1: Add Red Tests For Diagnostic Navigation Fields

**Files:**
- Modify: `tests/test_enterprise_harness_architecture.py`
- Modify: `tests/test_unified_cli.py`

- [ ] **Step 1: Run impact analysis for planned symbols**

Run:

```powershell
# Use GitNexus MCP impact, not this shell, before editing:
# impact(target="build", file_path="skills/e2e-dev-harness/scripts/navigation_map.py", kind="Function", direction="upstream", repo="e2e-dev-workflow")
# impact(target="evaluate_navigation_state", file_path="skills/e2e-dev-harness/scripts/coordinator_flow.py", kind="Function", direction="upstream", repo="e2e-dev-workflow")
# impact(target="_compact_navigation_map", file_path="skills/e2e-dev-harness/scripts/output_contract.py", kind="Function", direction="upstream", repo="e2e-dev-workflow")
```

Expected: impact reports LOW/MEDIUM or, if HIGH/CRITICAL, the worker reports risk before proceeding.

- [ ] **Step 2: Add a direct map-shape failing test**

Append to `CliCommandFacadeContractTests` in `tests/test_enterprise_harness_architecture.py`:

```python
    def test_navigation_map_reports_state_confidence_and_must_read_paths(self) -> None:
        import navigation_map  # noqa: PLC0415

        result = navigation_map.build(
            repo=Path("C:/repo"),
            state_path=Path("C:/repo/docs/agent-runs/run/run-state.json"),
            state={"run_id": "run", "lifecycle": "CREATED", "dispatches": {}},
            lifecycle="CREATED",
            workflow_stage="CLARIFY",
            ready=False,
            blocked_reasons=["Runtime hook is not ready"],
            warnings=["coordinator-summary lifecycle CREATED does not match run-state lifecycle CLARIFIED"],
            action={"workflow_stage": "CLARIFY", "phase": "clarify", "command": "dispatch-beat"},
            preflight={
                "ready": False,
                "blockers": [
                    {
                        "gate": "clarification",
                        "code": "BLK_CLARIFY_DISPATCH",
                        "message": "Clarification gate blocked.",
                        "minimal_fix": "Run dispatch-beat --max-workers 1.",
                    }
                ],
                "next_single_action": "Run dispatch-beat --max-workers 1.",
            },
            execution_packet={
                "phase": "clarify",
                "objective": "Clarify before planning.",
                "required_evidence": ["requirements handoff"],
                "completion_checks": ["run-state lifecycle becomes CLARIFIED"],
            },
            checkpoint={},
            diagnostics={
                "state_confidence": "degraded",
                "primary_blocker_code": "BLK_CLARIFY_DISPATCH",
                "checks": [
                    {"name": "state-lifecycle", "status": "pass", "severity": "info"},
                    {"name": "state-coordinator-summary", "status": "warn", "severity": "warning"},
                ],
                "must_read_paths": [
                    "docs/agent-runs/run/run-state.json",
                    "docs/agent-runs/run/agent-schedule.json",
                    "docs/agent-runs/run/coordinator-summary.json",
                ],
                "authority": {
                    "primary": "run-state.json",
                    "derived": ["agent-schedule.json", ".phase-lock", "coordinator-summary.json"],
                },
            },
        )

        self.assertEqual("degraded", result["state_confidence"])
        self.assertEqual("BLK_CLARIFY_DISPATCH", result["diagnostics"]["primary_blocker_code"])
        self.assertIn("docs/agent-runs/run/agent-schedule.json", result["must_read_paths"])
        self.assertEqual("run-state.json", result["authority"]["primary"])
```

Expected before implementation: FAIL because `build()` does not accept `diagnostics` and does not emit these fields.

- [ ] **Step 3: Add compact stdout parity failing test**

Add to `UnifiedCliTests` in `tests/test_unified_cli.py`:

```python
    def test_compact_navigation_map_preserves_confidence_and_must_read_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            full_result_path = repo / "full.json"
            result = {
                "ready": False,
                "lifecycle": "CREATED",
                "navigation_map": {
                    "schema": "e2e-dev-harness.navigation-map.v1",
                    "you_are_here": {
                        "lifecycle": "CREATED",
                        "workflow_stage": "CLARIFY",
                        "phase": "clarify",
                    },
                    "status": {"ready": False, "health": "blocked", "blocked_by": ["hook missing"]},
                    "next_single_action": {"command": "Run install_hooks.py --runtime claude.", "source": "preflight"},
                    "state_confidence": "blocked",
                    "diagnostics": {
                        "primary_blocker_code": "BLK_RUNTIME_HOOK",
                        "checks": [{"name": "runtime-hook", "status": "fail", "severity": "error"}],
                    },
                    "must_read_paths": [
                        "docs/agent-runs/run/run-state.json",
                        "docs/agent-runs/run/agent-schedule.json",
                    ],
                    "authority": {
                        "primary": "run-state.json",
                        "derived": ["agent-schedule.json", ".phase-lock", "coordinator-summary.json"],
                    },
                    "artifacts": {"run_state": "docs/agent-runs/run/run-state.json"},
                },
            }

            payload = output_contract.compact_payload(repo, "next", result, full_result_path)

        self.assertEqual("blocked", payload["navigation_map"]["state_confidence"])
        self.assertEqual("BLK_RUNTIME_HOOK", payload["navigation_map"]["diagnostics"]["primary_blocker_code"])
        self.assertIn("docs/agent-runs/run/run-state.json", payload["navigation_map"]["must_read_paths"])
```

Expected before implementation: FAIL because compact navigation map drops these fields.

- [ ] **Step 4: Run focused failing tests**

Run:

```powershell
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py
python -m unittest discover -s tests -p test_unified_cli.py
```

Expected: only the new tests fail for missing fields/signature.

---

### Task 2: Extract Read-Only Doctor-Lite State Summary

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/harness_doctor.py`
- Modify: `tests/test_harness_doctor.py`

- [ ] **Step 1: Run impact analysis**

Run:

```powershell
# GitNexus MCP:
# impact(target="state_consistency_checks", file_path="skills/e2e-dev-harness/scripts/harness_doctor.py", kind="Function", direction="upstream", repo="e2e-dev-workflow")
```

Expected: report blast radius before editing. Stop if HIGH/CRITICAL until user approves.

- [ ] **Step 2: Add a failing helper test**

Add to `HarnessDoctorTests` in `tests/test_harness_doctor.py`:

```python
    def test_state_navigation_summary_projects_confidence_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            write_control_plane_doctor_fixture(repo, lifecycle="CREATED")

            summary = harness_doctor.state_navigation_summary(repo, state_path)

        self.assertEqual("ready", summary["state_confidence"])
        self.assertEqual("run-state.json", summary["authority"]["primary"])
        self.assertIn("docs/agent-runs/run/run-state.json", summary["must_read_paths"])
        self.assertIn("docs/agent-runs/run/agent-schedule.json", summary["must_read_paths"])
        self.assertTrue(any(item["name"] == "state-lifecycle" for item in summary["checks"]))
```

Expected before implementation: FAIL because `state_navigation_summary` is missing.

- [ ] **Step 3: Implement `state_navigation_summary()`**

Add this helper near `state_consistency_checks()` in `harness_doctor.py`:

```python
def state_navigation_summary(repo: Path, state: Path) -> dict:
    checks = state_consistency_checks(repo, state)
    state_path = resolve_repo_path(repo, state)
    run_dir = state_path.parent
    compact_checks: list[dict] = []
    primary_blocker_code = ""
    for item in checks:
        name = str(item.get("name", "")).strip()
        status = str(item.get("status", "")).strip()
        severity = str(item.get("severity", "")).strip()
        message = str(item.get("message", "")).strip()
        compact_checks.append(
            {
                key: value
                for key, value in {
                    "name": name,
                    "status": status,
                    "severity": severity,
                    "message": message,
                }.items()
                if value
            }
        )
        if not primary_blocker_code and status == "fail":
            primary_blocker_code = name
    failed = any(item.get("status") == "fail" for item in compact_checks)
    warned = any(item.get("status") == "warn" for item in compact_checks)
    confidence = "blocked" if failed else "degraded" if warned else "ready"
    return {
        "state_confidence": confidence,
        "primary_blocker_code": primary_blocker_code,
        "checks": compact_checks,
        "must_read_paths": [
            posix_relative(repo, run_dir / "run-state.json"),
            posix_relative(repo, run_dir / "agent-schedule.json"),
            posix_relative(repo, run_dir / ".phase-lock"),
            posix_relative(repo, run_dir / "coordinator-summary.json"),
            posix_relative(repo, run_dir / "dispatch-events"),
            posix_relative(repo, run_dir / "events"),
        ],
        "authority": {
            "primary": "run-state.json",
            "derived": ["agent-schedule.json", ".phase-lock", "coordinator-summary.json"],
            "audit": ["dispatch-events", "events", "control-plane.json"],
        },
    }
```

Expected: helper is read-only and reuses existing doctor checks.

- [ ] **Step 4: Run focused doctor tests**

Run:

```powershell
python -m unittest discover -s tests -p test_harness_doctor.py
```

Expected: PASS.

---

### Task 3: Thread Diagnostic Summary Into `next` And `map`

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/coordinator_flow.py`
- Modify: `skills/e2e-dev-harness/scripts/navigation_map.py`
- Modify: `tests/test_enterprise_harness_architecture.py`

- [ ] **Step 1: Run impact analysis**

Run:

```powershell
# GitNexus MCP:
# impact(target="evaluate_navigation_state", file_path="skills/e2e-dev-harness/scripts/coordinator_flow.py", kind="Function", direction="upstream", repo="e2e-dev-workflow")
# impact(target="build", file_path="skills/e2e-dev-harness/scripts/navigation_map.py", kind="Function", direction="upstream", repo="e2e-dev-workflow")
```

Expected: report blast radius before editing.

- [ ] **Step 2: Update `navigation_map.build()` signature and output**

Modify `navigation_map.build()` to accept a defaulted diagnostics argument:

```python
def build(
    *,
    repo: Path,
    state_path: Path,
    state: dict,
    lifecycle: str,
    workflow_stage: str,
    ready: bool,
    blocked_reasons: list[str],
    warnings: list[str],
    action: dict,
    preflight: dict,
    execution_packet: dict,
    checkpoint: dict,
    coordinator_summary_path: str = "",
    diagnostics: dict | None = None,
) -> dict:
```

Inside the function:

```python
    diagnostics = diagnostics or {}
    authority = diagnostics.get("authority") if isinstance(diagnostics.get("authority"), dict) else {
        "primary": "run-state.json",
        "derived": ["agent-schedule.json", ".phase-lock", "coordinator-summary.json"],
    }
    must_read_paths = _strings(diagnostics.get("must_read_paths", []))
```

Add these top-level fields to the returned dict:

```python
        "state_confidence": str(diagnostics.get("state_confidence", "unknown")).strip() or "unknown",
        "diagnostics": {
            "primary_blocker_code": str(diagnostics.get("primary_blocker_code", "")).strip(),
            "checks": [
                {
                    key: item[key]
                    for key in ("name", "status", "severity")
                    if isinstance(item, dict) and item.get(key)
                }
                for item in diagnostics.get("checks", [])[:MAX_LIST]
                if isinstance(item, dict)
            ],
        },
        "must_read_paths": must_read_paths,
        "authority": authority,
```

Expected: direct map-shape test from Task 1 can now pass.

- [ ] **Step 3: Import and call doctor-lite helper from `coordinator_flow.py`**

At the top of `coordinator_flow.py`, add:

```python
import harness_doctor
```

Before `navigation_map.build(...)` in `evaluate_navigation_state()`:

```python
    state_diagnostics = harness_doctor.state_navigation_summary(repo, state_path)
```

Pass it into the map:

```python
        diagnostics=state_diagnostics,
```

Also expose it in full result:

```python
    result["state_diagnostics"] = state_diagnostics
```

Expected: `next --json-full` has both `state_diagnostics` and `navigation_map`.

- [ ] **Step 4: Run focused architecture tests**

Run:

```powershell
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py
```

Expected: PASS.

---

### Task 4: Preserve High-Signal Fields In Compact Stdout And Summary

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/output_contract.py`
- Modify: `skills/e2e-dev-harness/scripts/coordinator_summary.py`
- Modify: `tests/test_unified_cli.py`
- Modify: `tests/test_enterprise_harness_architecture.py`

- [ ] **Step 1: Run impact analysis**

Run:

```powershell
# GitNexus MCP:
# impact(target="_compact_navigation_map", file_path="skills/e2e-dev-harness/scripts/output_contract.py", kind="Function", direction="upstream", repo="e2e-dev-workflow")
# impact(target="_compact_navigation_map", file_path="skills/e2e-dev-harness/scripts/coordinator_summary.py", kind="Function", direction="upstream", repo="e2e-dev-workflow")
```

Expected: report blast radius before editing.

- [ ] **Step 2: Update compact map in `output_contract.py`**

In `_compact_navigation_map()`, after `artifacts` is computed:

```python
    diagnostics = value.get("diagnostics") if isinstance(value.get("diagnostics"), dict) else {}
    authority = value.get("authority") if isinstance(value.get("authority"), dict) else {}
```

Add fields to `result`:

```python
        "state_confidence": value.get("state_confidence", ""),
        "diagnostics": {
            key: diagnostics[key]
            for key in ("primary_blocker_code",)
            if diagnostics.get(key)
        },
        "must_read_paths": _limited_strings(value.get("must_read_paths", []), 3),
        "authority": {
            key: authority[key]
            for key in ("primary",)
            if authority.get(key)
        },
```

Keep the final cleanup:

```python
    return {key: item for key, item in result.items() if item not in ({}, [])}
```

Expected: compact stdout still trims bulky check lists but preserves confidence, primary blocker, primary authority, and must-read paths.

- [ ] **Step 3: Update coordinator summary compact map**

In `coordinator_summary._compact_navigation_map()`, preserve slightly more than stdout:

```python
    diagnostics = value.get("diagnostics") if isinstance(value.get("diagnostics"), dict) else {}
    authority = value.get("authority") if isinstance(value.get("authority"), dict) else {}
```

Add:

```python
        "state_confidence": value.get("state_confidence", ""),
        "diagnostics": {
            "primary_blocker_code": diagnostics.get("primary_blocker_code", ""),
            "checks": _limited(diagnostics.get("checks", []), 8),
        },
        "must_read_paths": _limited(value.get("must_read_paths", []), 8),
        "authority": authority,
```

Expected: summary becomes the durable L1 map, while stdout remains L0.

- [ ] **Step 4: Run focused CLI tests**

Run:

```powershell
python -m unittest discover -s tests -p test_unified_cli.py
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py
```

Expected: PASS, including size/truncation tests.

---

### Task 5: Add End-To-End Fixture For Drifted Projection Guidance

**Files:**
- Modify: `tests/test_unified_cli.py`

- [ ] **Step 1: Add a failing E2E test for stale summary**

Add to `UnifiedCliTests`:

```python
    def test_next_map_reports_degraded_state_when_summary_lifecycle_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            state = e2e_dev_harness.run_state.build_state(
                "docs/agent-runs/run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            e2e_dev_harness.run_state.write_state(repo, state_path, state)
            (run_dir / "coordinator-summary.json").write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.coordinator-summary.v1",
                        "lifecycle": "CREATED",
                        "workflow_stage": "CLARIFY",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "e2e_dev_harness.py"),
                    "next",
                    str(repo),
                    "--state",
                    str(state_path),
                    "--runtime",
                    "claude-code",
                ],
                cwd=str(repo),
                text=True,
                capture_output=True,
                check=False,
            )
            payload = json.loads(completed.stdout)

        self.assertEqual(0, completed.returncode)
        self.assertEqual("degraded", payload["navigation_map"]["state_confidence"])
        self.assertIn("coordinator-summary", json.dumps(payload["navigation_map"]))
        self.assertIn("full_result_path", payload)
```

Expected before the previous tasks: FAIL or missing confidence. Expected after implementation: PASS.

- [ ] **Step 2: Verify full result has richer diagnostics**

Extend the same test:

```python
            full_path = Path(payload["full_result_path"])
            if not full_path.is_absolute():
                full_path = repo / full_path
            full = json.loads(full_path.read_text(encoding="utf-8"))

        self.assertIn("state_diagnostics", full)
        self.assertTrue(any(item["name"] == "state-coordinator-summary" for item in full["state_diagnostics"]["checks"]))
```

Expected: full result has L2 detail.

- [ ] **Step 3: Run focused E2E test file**

Run:

```powershell
python -m unittest discover -s tests -p test_unified_cli.py
```

Expected: PASS.

---

### Task 6: Documentation And Compatibility Check

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update map docs**

In the section that currently documents `e2e-harness map`, add:

```markdown
The map has three detail levels:

- Compact stdout: `you_are_here`, `state_confidence`, `next_single_action`, `primary_blocker_code`, and a short `must_read_paths` list.
- `coordinator-summary.json`: durable coordinator resume view with bounded diagnostic checks and authority pointers.
- `full_result_path` / `--json-full`: full control-plane result with execution packet, workflow overview, preflight, and state diagnostics.

Use `state_confidence` as the first trust signal:

- `ready`: run-state and derived views agree.
- `degraded`: the main lifecycle is readable, but a derived view such as `coordinator-summary.json` is stale.
- `blocked`: a required control-plane surface is missing, invalid, or inconsistent.

The map remains read-only. Repair still goes through the command named in `next_single_action` or through doctor/recovery commands.
```

Expected: docs explain how to avoid ad hoc file probing.

- [ ] **Step 2: Run doc-adjacent tests**

Run:

```powershell
python -m unittest discover -s tests -p test_unified_cli.py
```

Expected: PASS.

---

### Task 7: Final Verification And Scope Audit

**Files:**
- No new edits unless failures identify a real issue.

- [ ] **Step 1: Run all focused tests**

Run:

```powershell
python -m unittest discover -s tests -p test_harness_doctor.py
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py
python -m unittest discover -s tests -p test_unified_cli.py
```

Expected: all PASS.

- [ ] **Step 2: Run full suite**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: all PASS.

- [ ] **Step 3: Run GitNexus change detection**

Run:

```powershell
# GitNexus MCP:
# detect_changes(scope="all", repo="e2e-dev-workflow")
```

Expected: affected scope is limited to navigation map, coordinator next/map output, doctor diagnostic helper, compact output, and tests/docs.

- [ ] **Step 4: Refresh index if code changed**

Run:

```powershell
npx gitnexus analyze
```

Expected: repository indexed successfully.

- [ ] **Step 5: Optional installed-copy sync**

Only if the change is intended to affect runtime-visible installed harness copies in this same session:

```powershell
node tools/install-e2e-dev-harness.mjs --sync --yes --json
```

Expected: installed `.codex`, `.agents`, and `.claude` copies match source for touched harness files.

---

## Self-Review

- Spec coverage: The plan addresses insufficient map guidance by adding state confidence, blocker code, authority, must-read paths, summary/full parity, and documentation.
- Placeholder scan: No TBD/TODO placeholders remain; each task names exact files, commands, expected results, and code shape.
- Type consistency: New `diagnostics` argument is a dict; emitted fields are `state_confidence`, `diagnostics`, `must_read_paths`, and `authority` across full map, compact stdout, and coordinator summary.

## Execution Options

Plan complete and saved to `docs/superpowers/plans/2026-06-06-navigation-map-sufficiency-repair.md`. Two execution options:

1. Subagent-Driven (recommended) - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. Inline Execution - execute tasks in this session using executing-plans, batch execution with checkpoints.
