# Development Navigation Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a compact Development Navigation Map that gives developers a single "you are here" view without creating a new lifecycle or dispatch fact source.

**Architecture:** The map is a read-only projection built from existing `next_step` facts: lifecycle, workflow stage, next action, preflight, execution packet, active dispatches, checkpoint, and artifact paths. `coordinator_flow.next_step()` remains the primary aggregator; a new `navigation_map.py` owns projection shaping; `output_contract.py` and `coordinator_summary.py` only compact and expose that projection. No lifecycle transitions, dispatch status mutation, or doctor checks move into the map.

**Tech Stack:** Python standard library, existing e2e-dev-harness CLI modules, `unittest`, GitNexus impact/detect-changes.

---

## Blast Radius And Guardrails

GitNexus impact analysis was run before planning the affected symbols:

- `coordinator_flow.next_step`: LOW risk, 2 direct callers (`e2e_harness/cli/commands/next.py:run_from_args`, `e2e_harness/engine/orchestrator.py:next_step`), 0 affected processes.
- `output_contract.compact_payload`: LOW risk, 2 direct callers, 1 affected process (`e2e_dev_harness.py:main`).
- `coordinator_summary.write`: CRITICAL risk, 2 direct callers but broad downstream usage through run-state, dispatch, start, plan, and tests. Treat this as additive-only and avoid changing existing keys or ready/blocking semantics.

Implementation guardrails:

- Do not add a new lifecycle owner.
- Do not call `doctor` from the navigation map.
- Do not duplicate the full `workflow_plan`.
- Do not mutate `run-state.json`, dispatch events, checkpoint files, or coordinator summary from the map builder.
- Preserve legacy compact/full/status fields and add `navigation_map` as an additive field.
- Keep compact stdout under the existing `MAX_COMPACT_CHARS` fallback behavior; when truncation happens, retain a minimal map rather than dropping it.

## File Structure

- Create `skills/e2e-dev-harness/scripts/navigation_map.py`
  - Owns `build(...)`, `_compact_strings(...)`, `_active_dispatches(...)`, and `_artifact_paths(...)`.
  - Produces schema `e2e-dev-harness.navigation-map.v1`.
  - Accepts already-loaded facts from `next_step`; never reads doctor state or mutates files.
- Modify `skills/e2e-dev-harness/scripts/coordinator_flow.py`
  - Imports `navigation_map`.
  - Builds `navigation_map` after session checkpoint and before coordinator summary creation.
  - Includes the map in the full `next` result and status-file result.
- Modify `skills/e2e-dev-harness/scripts/output_contract.py`
  - Adds `_compact_navigation_map(...)`.
  - Includes compact `navigation_map` in quiet stdout for `next`.
  - Preserves a minimal map in every truncation fallback.
- Modify `skills/e2e-dev-harness/scripts/coordinator_summary.py`
  - Adds `_compact_navigation_map(...)`.
  - Stores additive `navigation_map` in `coordinator-summary.json`.
  - Does not change `ready`, `next_action`, `execution_packet`, or `active_dispatches` semantics.
- Modify `tests/test_unified_cli.py`
  - Adds contract coverage for compact stdout and full result.
- Modify `tests/test_enterprise_harness_architecture.py`
  - Adds focused unit coverage for the projection builder and coordinator summary additive field.

---

### Task 1: Add The Read-Only Navigation Map Projection

**Files:**
- Create: `skills/e2e-dev-harness/scripts/navigation_map.py`
- Test: `tests/test_enterprise_harness_architecture.py`

- [ ] **Step 1: Write the failing projection builder test**

Add this test method to `CliCommandFacadeContractTests` in `tests/test_enterprise_harness_architecture.py`:

```python
    def test_navigation_map_projection_reports_you_are_here_and_single_action(self) -> None:
        import navigation_map  # noqa: PLC0415

        state = {
            "run_id": "run",
            "lifecycle": "CREATED",
            "dispatches": {
                "T01": {
                    "status": "awaiting_runtime_spawn",
                    "runtime": "codex",
                    "current_agent": "requirements-clarifier",
                    "context_pack": "docs/agent-runs/run/context-packs/T01.json",
                    "invocation_path": "docs/agent-runs/run/dispatch-invocations/T01.json",
                }
            },
        }
        action = {
            "workflow_stage": "CLARIFY",
            "phase": "clarify",
            "dispatch_command": "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-beat . --max-workers 1",
            "allowed_writes": ["docs/agent-runs/run/design.md"],
            "blocked_writes": ["src/**"],
            "forbidden_local_actions": ["do not edit production code"],
        }
        execution_packet = {
            "schema": "e2e-dev-harness.execution-packet.v1",
            "lifecycle": "CREATED",
            "phase": "clarify",
            "objective": "Clarify intent and scope through the bootstrap requirements worker before planning.",
            "primary_command": action["dispatch_command"],
            "required_actions": ["Dispatch the requirements-clarifier worker."],
            "required_evidence": ["confirmed Restated Intent and closed Open Questions in the design doc"],
            "forbidden_actions": ["do not edit production code"],
            "completion_checks": ["run-state lifecycle becomes CLARIFIED"],
            "next_gate": "clarification",
        }

        result = navigation_map.build(
            repo=Path("C:/repo"),
            state_path=Path("C:/repo/docs/agent-runs/run/run-state.json"),
            state=state,
            lifecycle="CREATED",
            workflow_stage="CLARIFY",
            ready=False,
            blocked_reasons=["Runtime hook is not ready"],
            warnings=["Session checkpoint is stale"],
            action=action,
            preflight={"ready": False, "blockers": ["dispatch ack missing"], "next_single_action": "run dispatch-ack"},
            execution_packet=execution_packet,
            checkpoint={"checkpoint": "docs/agent-runs/run/session-checkpoint.json"},
            coordinator_summary_path="docs/agent-runs/run/coordinator-summary.json",
        )

        self.assertEqual("e2e-dev-harness.navigation-map.v1", result["schema"])
        self.assertEqual({"lifecycle": "CREATED", "workflow_stage": "CLARIFY", "phase": "clarify"}, result["you_are_here"])
        self.assertFalse(result["status"]["ready"])
        self.assertEqual(["Runtime hook is not ready", "dispatch ack missing"], result["status"]["blocked_by"])
        self.assertEqual("run dispatch-ack", result["next_single_action"]["command"])
        self.assertEqual("preflight", result["next_single_action"]["source"])
        self.assertEqual("T01", result["active_work"][0]["task_id"])
        self.assertEqual(["docs/agent-runs/run/design.md"], result["allowed_now"])
        self.assertIn("do not edit production code", result["forbidden_now"])
        self.assertEqual(["confirmed Restated Intent and closed Open Questions in the design doc"], result["required_evidence"])
        self.assertEqual("docs/agent-runs/run/run-state.json", result["artifacts"]["run_state"])
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
python -m unittest tests.test_enterprise_harness_architecture.CliCommandFacadeContractTests.test_navigation_map_projection_reports_you_are_here_and_single_action
```

Expected: FAIL with `ModuleNotFoundError: No module named 'navigation_map'`.

- [ ] **Step 3: Add the projection builder**

Create `skills/e2e-dev-harness/scripts/navigation_map.py`:

```python
#!/usr/bin/env python3
"""Read-only Development Navigation Map projection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

SCHEMA = "e2e-dev-harness.navigation-map.v1"
MAX_LIST = 8


def _strings(values: Any, limit: int = MAX_LIST) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _rel(repo: Path, value: Any) -> str:
    if not value:
        return ""
    path = value if isinstance(value, Path) else Path(str(value))
    try:
        resolved = path if path.is_absolute() else repo / path
        return resolved.resolve().relative_to(repo.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def _active_dispatches(state: dict) -> list[dict]:
    dispatches = state.get("dispatches", {}) if isinstance(state.get("dispatches"), dict) else {}
    active: list[dict] = []
    for task_id, dispatch in dispatches.items():
        if not isinstance(dispatch, dict):
            continue
        status = str(dispatch.get("status", "")).strip()
        if status.lower() in {"", "completed", "cancelled"}:
            continue
        item = {
            "task_id": str(task_id),
            "status": status,
            "runtime": str(dispatch.get("runtime", "")),
            "agent": str(dispatch.get("current_agent", dispatch.get("agent", ""))),
            "worker_handle": str(dispatch.get("worker_handle", "")),
            "context_pack": str(dispatch.get("context_pack", "")),
            "invocation_path": str(dispatch.get("invocation_path", "")),
        }
        active.append({key: value for key, value in item.items() if value})
        if len(active) >= MAX_LIST:
            break
    return active


def _single_action(action: dict, preflight: dict, execution_packet: dict) -> dict:
    preflight_action = str(preflight.get("next_single_action", "")).strip()
    if preflight_action:
        return {
            "command": preflight_action,
            "source": "preflight",
            "reason": "Preflight selected the next single safe action.",
        }
    command = str(
        action.get("dispatch_command")
        or action.get("command")
        or execution_packet.get("exact_next_command")
        or execution_packet.get("primary_command")
        or ""
    ).strip()
    return {
        "command": command,
        "source": "next_action" if command else "none",
        "reason": str(execution_packet.get("objective", "")).strip(),
    }


def _artifacts(
    repo: Path,
    state_path: Path,
    checkpoint: dict,
    coordinator_summary_path: str = "",
) -> dict:
    artifacts = {
        "run_state": _rel(repo, state_path),
        "run_dir": _rel(repo, state_path.parent),
    }
    checkpoint_path = str(checkpoint.get("checkpoint", "")).strip() if isinstance(checkpoint, dict) else ""
    if checkpoint_path:
        artifacts["checkpoint"] = checkpoint_path
    if coordinator_summary_path:
        artifacts["coordinator_summary"] = coordinator_summary_path
    return artifacts


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
) -> dict:
    phase = str(action.get("phase") or execution_packet.get("phase") or "").strip()
    preflight_blockers = _strings(preflight.get("blockers", []))
    return {
        "schema": SCHEMA,
        "you_are_here": {
            "lifecycle": lifecycle or "<missing>",
            "workflow_stage": workflow_stage or "UNKNOWN",
            "phase": phase,
        },
        "status": {
            "ready": bool(ready),
            "health": "ready" if ready else "blocked",
            "blocked_by": _strings(list(blocked_reasons) + preflight_blockers),
            "warnings": _strings(warnings),
        },
        "next_single_action": _single_action(action, preflight, execution_packet),
        "active_work": _active_dispatches(state),
        "allowed_now": _strings(action.get("allowed_writes", execution_packet.get("allowed_now", []))),
        "forbidden_now": _strings(
            list(action.get("forbidden_local_actions", []))
            + list(action.get("blocked_writes", []))
            + list(execution_packet.get("forbidden_now", []))
        ),
        "required_evidence": _strings(execution_packet.get("required_evidence", [])),
        "completion_checks": _strings(execution_packet.get("completion_checks", execution_packet.get("completion_requires", []))),
        "artifacts": _artifacts(repo, state_path, checkpoint, coordinator_summary_path),
    }
```

- [ ] **Step 4: Run the projection test**

Run:

```powershell
python -m unittest tests.test_enterprise_harness_architecture.CliCommandFacadeContractTests.test_navigation_map_projection_reports_you_are_here_and_single_action
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```powershell
git add skills/e2e-dev-harness/scripts/navigation_map.py tests/test_enterprise_harness_architecture.py
git commit -m "test: define navigation map projection contract"
```

---

### Task 2: Attach Navigation Map To `next` Full Results

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/coordinator_flow.py`
- Test: `tests/test_unified_cli.py`

- [ ] **Step 1: Write the failing full-result test**

Update `test_next_cli_quiet_default_writes_full_result_artifact` in `tests/test_unified_cli.py` by adding these assertions after `self.assertIn("execution_packet", full_payload)`:

```python
        self.assertIn("navigation_map", full_payload)
        self.assertEqual("e2e-dev-harness.navigation-map.v1", full_payload["navigation_map"]["schema"])
        self.assertEqual("CREATED", full_payload["navigation_map"]["you_are_here"]["lifecycle"])
        self.assertEqual("CLARIFY", full_payload["navigation_map"]["you_are_here"]["workflow_stage"])
        self.assertIn("dispatch-beat", full_payload["navigation_map"]["next_single_action"]["command"])
        self.assertEqual("docs/agent-runs/run/run-state.json", full_payload["navigation_map"]["artifacts"]["run_state"])
```

- [ ] **Step 2: Run the failing full-result test**

Run:

```powershell
python -m unittest tests.test_unified_cli.UnifiedCliTests.test_next_cli_quiet_default_writes_full_result_artifact
```

Expected: FAIL because `navigation_map` is absent from the full result.

- [ ] **Step 3: Build the map in `coordinator_flow.next_step`**

Modify imports near the top of `skills/e2e-dev-harness/scripts/coordinator_flow.py`:

```python
import navigation_map
```

In `next_step`, after:

```python
    result["coordinator_context_budget"] = checkpoint.get("context_budget", {})
```

add:

```python
    result["navigation_map"] = navigation_map.build(
        repo=repo,
        state_path=state_path,
        state=state,
        lifecycle=lifecycle,
        workflow_stage=result["workflow_stage"],
        ready=result["ready"],
        blocked_reasons=list(result.get("blocked_reasons", [])),
        warnings=list(result.get("warnings", [])),
        action=action,
        preflight=result["preflight"],
        execution_packet=execution_packet,
        checkpoint=checkpoint,
    )
```

After:

```python
    result["coordinator_summary_path"] = summary.get("coordinator_summary", "")
```

add:

```python
    if isinstance(result.get("navigation_map"), dict):
        result["navigation_map"].setdefault("artifacts", {})["coordinator_summary"] = summary.get("coordinator_summary", "")
```

- [ ] **Step 4: Run the full-result test**

Run:

```powershell
python -m unittest tests.test_unified_cli.UnifiedCliTests.test_next_cli_quiet_default_writes_full_result_artifact
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```powershell
git add skills/e2e-dev-harness/scripts/coordinator_flow.py tests/test_unified_cli.py
git commit -m "feat: attach navigation map to next results"
```

---

### Task 3: Surface Navigation Map In Compact Stdout Without Breaking Truncation

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/output_contract.py`
- Test: `tests/test_unified_cli.py`

- [ ] **Step 1: Write the failing compact stdout assertions**

In `test_next_cli_quiet_default_writes_full_result_artifact`, add these assertions after `self.assertEqual("CLARIFY", payload["workflow_stage"])`:

```python
        self.assertIn("navigation_map", payload)
        self.assertEqual("CREATED", payload["navigation_map"]["you_are_here"]["lifecycle"])
        self.assertEqual("CLARIFY", payload["navigation_map"]["you_are_here"]["workflow_stage"])
        self.assertIn("dispatch-beat", payload["navigation_map"]["next_single_action"]["command"])
        self.assertNotIn("required_evidence", payload["navigation_map"])
```

Add this new test to `UnifiedCliTests`:

```python
    def test_compact_payload_preserves_minimal_navigation_map_when_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            full_result_path = repo / "full.json"
            result = {
                "ready": False,
                "lifecycle": "PLANNED",
                "blocked_reasons": [f"blocker-{index}" for index in range(80)],
                "warnings": [f"warning-{index}" for index in range(80)],
                "navigation_map": {
                    "schema": "e2e-dev-harness.navigation-map.v1",
                    "you_are_here": {
                        "lifecycle": "PLANNED",
                        "workflow_stage": "TEST_READY",
                        "phase": "tdd-red",
                    },
                    "status": {
                        "ready": False,
                        "health": "blocked",
                        "blocked_by": ["dispatch ack missing"],
                        "warnings": ["checkpoint stale"],
                    },
                    "next_single_action": {
                        "command": "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-ack . --task-id T02",
                        "source": "preflight",
                        "reason": "Preflight selected the next single safe action.",
                    },
                    "active_work": [{"task_id": "T02", "status": "awaiting_runtime_spawn"}],
                    "allowed_now": ["docs/agent-runs/run/evidence/red-test.txt"],
                    "forbidden_now": ["src/**"],
                    "required_evidence": ["red test evidence"],
                    "completion_checks": ["run-state lifecycle becomes RED_READY"],
                    "artifacts": {"run_state": "docs/agent-runs/run/run-state.json"},
                },
            }

            payload = output_contract.compact_payload(repo, "next", result, full_result_path)

        self.assertTrue(payload["truncated"])
        self.assertIn("navigation_map", payload)
        self.assertEqual("PLANNED", payload["navigation_map"]["you_are_here"]["lifecycle"])
        self.assertEqual("TEST_READY", payload["navigation_map"]["you_are_here"]["workflow_stage"])
        self.assertIn("dispatch-ack", payload["navigation_map"]["next_single_action"]["command"])
```

- [ ] **Step 2: Run the failing compact tests**

Run:

```powershell
python -m unittest tests.test_unified_cli.UnifiedCliTests.test_next_cli_quiet_default_writes_full_result_artifact tests.test_unified_cli.UnifiedCliTests.test_compact_payload_preserves_minimal_navigation_map_when_truncated
```

Expected: FAIL because compact payload does not expose `navigation_map`.

- [ ] **Step 3: Add compact map helpers**

In `skills/e2e-dev-harness/scripts/output_contract.py`, add these helpers before `compact_payload`:

```python
def _compact_navigation_map(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    you_are_here = value.get("you_are_here") if isinstance(value.get("you_are_here"), dict) else {}
    status = value.get("status") if isinstance(value.get("status"), dict) else {}
    next_action = value.get("next_single_action") if isinstance(value.get("next_single_action"), dict) else {}
    artifacts = value.get("artifacts") if isinstance(value.get("artifacts"), dict) else {}
    result = {
        "you_are_here": {
            key: you_are_here[key]
            for key in ("lifecycle", "workflow_stage", "phase")
            if you_are_here.get(key)
        },
        "status": {
            "ready": bool(status.get("ready", False)),
            "health": status.get("health", "blocked"),
            "blocked_by": _limited_strings(status.get("blocked_by", []), 3),
        },
        "next_single_action": {
            key: next_action[key]
            for key in ("command", "source")
            if next_action.get(key)
        },
        "active_work": _limited_list(value.get("active_work", []), 3),
        "artifacts": {
            key: artifacts[key]
            for key in ("run_state", "coordinator_summary")
            if artifacts.get(key)
        },
    }
    return {key: item for key, item in result.items() if item not in ({}, [])}


def _minimal_navigation_map(value: Any) -> dict:
    compact = _compact_navigation_map(value)
    if not compact:
        return {}
    return {
        key: compact[key]
        for key in ("you_are_here", "status", "next_single_action")
        if compact.get(key)
    }
```

In the initial `payload` dict inside `compact_payload`, add:

```python
        "navigation_map": _compact_navigation_map(result.get("navigation_map")),
```

In every truncation fallback payload, add or preserve:

```python
    payload["navigation_map"] = _minimal_navigation_map(result.get("navigation_map"))
```

For the final full rebuild branch, include:

```python
            "navigation_map": _minimal_navigation_map(result.get("navigation_map")),
```

- [ ] **Step 4: Run compact tests**

Run:

```powershell
python -m unittest tests.test_unified_cli.UnifiedCliTests.test_next_cli_quiet_default_writes_full_result_artifact tests.test_unified_cli.UnifiedCliTests.test_compact_payload_preserves_minimal_navigation_map_when_truncated
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```powershell
git add skills/e2e-dev-harness/scripts/output_contract.py tests/test_unified_cli.py
git commit -m "feat: show navigation map in compact output"
```

---

### Task 4: Persist Navigation Map In Coordinator Summary Additively

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/coordinator_summary.py`
- Test: `tests/test_enterprise_harness_architecture.py`

- [ ] **Step 1: Write the failing coordinator summary test**

Add this test method to `CliCommandFacadeContractTests` in `tests/test_enterprise_harness_architecture.py`:

```python
    def test_coordinator_summary_persists_navigation_map_additively(self) -> None:
        import coordinator_summary  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            run_dir.mkdir(parents=True)
            state_path = run_dir / "run-state.json"
            state = {"run_id": "run", "lifecycle": "CREATED"}
            result = {
                "ready": True,
                "lifecycle": "CREATED",
                "navigation_map": {
                    "schema": "e2e-dev-harness.navigation-map.v1",
                    "you_are_here": {
                        "lifecycle": "CREATED",
                        "workflow_stage": "CLARIFY",
                        "phase": "clarify",
                    },
                    "status": {"ready": True, "health": "ready", "blocked_by": []},
                    "next_single_action": {
                        "command": "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-beat . --max-workers 1",
                        "source": "next_action",
                    },
                    "active_work": [],
                    "allowed_now": ["docs/agent-runs/run/design.md"],
                    "forbidden_now": ["src/**"],
                    "required_evidence": ["requirements handoff"],
                    "completion_checks": ["run-state lifecycle becomes CLARIFIED"],
                    "artifacts": {"run_state": "docs/agent-runs/run/run-state.json"},
                },
            }

            summary = coordinator_summary.write(repo, state_path, state, result=result)
            payload = json.loads(Path(summary["coordinator_summary"]).read_text(encoding="utf-8"))

        self.assertTrue(summary["ready"])
        self.assertEqual("CREATED", payload["lifecycle"])
        self.assertEqual("CLARIFY", payload["workflow_stage"])
        self.assertIn("navigation_map", payload)
        self.assertEqual("CREATED", payload["navigation_map"]["you_are_here"]["lifecycle"])
        self.assertIn("dispatch-beat", payload["navigation_map"]["next_single_action"]["command"])
        self.assertIn("next_action", payload)
        self.assertIn("execution_packet", payload)
```

- [ ] **Step 2: Run the failing summary test**

Run:

```powershell
python -m unittest tests.test_enterprise_harness_architecture.CliCommandFacadeContractTests.test_coordinator_summary_persists_navigation_map_additively
```

Expected: FAIL because coordinator summary does not include `navigation_map`.

- [ ] **Step 3: Add additive summary compaction**

In `skills/e2e-dev-harness/scripts/coordinator_summary.py`, add:

```python
def _compact_navigation_map(value: dict | None) -> dict:
    value = value or {}
    you_are_here = value.get("you_are_here") if isinstance(value.get("you_are_here"), dict) else {}
    status = value.get("status") if isinstance(value.get("status"), dict) else {}
    next_action = value.get("next_single_action") if isinstance(value.get("next_single_action"), dict) else {}
    artifacts = value.get("artifacts") if isinstance(value.get("artifacts"), dict) else {}
    return {
        "you_are_here": {
            key: you_are_here[key]
            for key in ("lifecycle", "workflow_stage", "phase")
            if you_are_here.get(key)
        },
        "status": {
            "ready": bool(status.get("ready", False)),
            "health": status.get("health", "blocked"),
            "blocked_by": _limited(status.get("blocked_by", []), 5),
            "warnings": _limited(status.get("warnings", []), 5),
        },
        "next_single_action": {
            key: next_action[key]
            for key in ("command", "source", "reason")
            if next_action.get(key)
        },
        "active_work": _limited(value.get("active_work", []), 5),
        "allowed_now": _limited(value.get("allowed_now", []), 5),
        "forbidden_now": _limited(value.get("forbidden_now", []), 5),
        "required_evidence": _limited(value.get("required_evidence", []), 5),
        "artifacts": {
            key: artifacts[key]
            for key in ("run_state", "run_dir", "checkpoint", "coordinator_summary")
            if artifacts.get(key)
        },
    }
```

Inside the `data` dict in `write(...)`, add:

```python
        "navigation_map": _compact_navigation_map(result.get("navigation_map")),
```

Do not alter existing `ready`, `blocked_reasons`, `next_action`, `execution_packet`, or `active_dispatches` assignments.

- [ ] **Step 4: Run the summary test**

Run:

```powershell
python -m unittest tests.test_enterprise_harness_architecture.CliCommandFacadeContractTests.test_coordinator_summary_persists_navigation_map_additively
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```powershell
git add skills/e2e-dev-harness/scripts/coordinator_summary.py tests/test_enterprise_harness_architecture.py
git commit -m "feat: persist navigation map in coordinator summary"
```

---

### Task 5: Add An Optional `map` CLI Facade

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_dev_harness.py`
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/map.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_dev_harness.py`
- Test: `tests/test_enterprise_harness_architecture.py`

- [ ] **Step 1: Inspect current parser registration**

Run:

```powershell
rg -n "subparsers|add_parser\\(\"next\"|dispatch-beat|timeline" skills/e2e-dev-harness/scripts/e2e_dev_harness.py skills/e2e-dev-harness/scripts/e2e_harness/cli
```

Expected: confirm the current command registration lives in `skills/e2e-dev-harness/scripts/e2e_dev_harness.py`, with command imports near lines 46-67, wrapper functions near `next_step(args)`, parser registration near the `next_parser` block, and command dispatch through the `if args.command == ...` chain.

- [ ] **Step 2: Write the failing map facade test**

Add this test to `CliCommandFacadeContractTests`:

```python
    def test_map_cli_facade_returns_navigation_map_only(self) -> None:
        from e2e_harness.cli.commands import map as map_command  # noqa: PLC0415
        import argparse  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _code, start_result = e2e_dev_harness.start(
                argparse.Namespace(
                    repo=repo,
                    feature="Quote",
                    request="Return a quote.",
                    design_doc=None,
                    agent_run_dir=None,
                    run_id="run",
                    run_date=None,
                    force=False,
                    status_file=None,
                )
            )
            status_file = repo / "map-status.json"

            code, result = map_command.run_from_args(
                argparse.Namespace(
                    repo=repo,
                    state=Path(start_result["run_state"]),
                    runtime="claude-code",
                    status_file=status_file,
                )
            )
            status_payload = json.loads(status_file.read_text(encoding="utf-8"))

        self.assertEqual(0, code)
        self.assertEqual("e2e-dev-harness.navigation-map.v1", result["schema"])
        self.assertEqual("CREATED", result["you_are_here"]["lifecycle"])
        self.assertEqual("CLARIFY", result["you_are_here"]["workflow_stage"])
        self.assertEqual(result, status_payload)
        self.assertNotIn("workflow_plan", result)
        self.assertNotIn("todo_policy", result)
```

- [ ] **Step 3: Run the failing facade test**

Run:

```powershell
python -m unittest tests.test_enterprise_harness_architecture.CliCommandFacadeContractTests.test_map_cli_facade_returns_navigation_map_only
```

Expected: FAIL because `e2e_harness.cli.commands.map` does not exist.

- [ ] **Step 4: Add the map command module**

Create `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/map.py`:

```python
"""Navigation map command facade."""

from __future__ import annotations

import argparse
from pathlib import Path

import coordinator_flow


def run(
    repo: Path,
    state: Path,
    runtime: str = "claude-code",
    status_file: Path | None = None,
) -> tuple[int, dict]:
    return run_from_args(
        argparse.Namespace(
            repo=repo,
            state=state,
            runtime=runtime,
            status_file=status_file,
        )
    )


def run_from_args(args) -> tuple[int, dict]:
    code, result = coordinator_flow.next_step(args)
    navigation = result.get("navigation_map") if isinstance(result.get("navigation_map"), dict) else {}
    if getattr(args, "status_file", None):
        coordinator_flow.write_status(args.status_file, navigation)
    return code, navigation
```

In `skills/e2e-dev-harness/scripts/e2e_dev_harness.py`, add the command import next to the other command facade imports:

```python
from e2e_harness.cli.commands import map as map_command  # noqa: E402
```

Add this wrapper next to `next_step(args)`:

```python
def map_view(args) -> tuple[int, dict]:
    return map_command.run_from_args(args)
```

Register the command after `next_parser`:

```python
    map_parser = subparsers.add_parser("map", help="Print the compact Development Navigation Map")
    map_parser.add_argument("repo", nargs="?", default=".", type=Path)
    map_parser.add_argument("--state", required=True, type=Path)
    map_parser.add_argument("--runtime", default="claude-code", help="Runtime used in suggested dispatch commands.")
    map_parser.add_argument("--status-file", type=Path)
```

Add `map_parser` to the `for output_parser in (...)` tuple so it receives the same output arguments as other commands:

```python
        next_parser,
        map_parser,
        preflight_parser,
```

Add the main command dispatch branch immediately after the `next` branch:

```python
        elif args.command == "map":
            exit_code, result = map_view(args)
```

When compact output is rendered, keep `map` as a normal compact command; do not add the extra `session_checkpoint.create_coordinator_summary(...)` branch that is specific to `next`.

- [ ] **Step 5: Run the facade test**

Run:

```powershell
python -m unittest tests.test_enterprise_harness_architecture.CliCommandFacadeContractTests.test_map_cli_facade_returns_navigation_map_only
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```powershell
git add skills/e2e-dev-harness/scripts/e2e_dev_harness.py skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/map.py tests/test_enterprise_harness_architecture.py
git commit -m "feat: add navigation map command facade"
```

---

### Task 6: Update Docs And Verify Installed Runtime Copy

**Files:**
- Modify: `README.md` or the existing CLI docs section that lists `next`, `doctor`, `timeline`, and dispatch commands.
- Modify: any generated/installed copies only through the existing installer sync command.

- [ ] **Step 1: Find the current CLI documentation**

Run:

```powershell
rg -n "doctor|timeline|dispatch-beat|next|workflow_stage|execution_packet" README.md docs skills/e2e-dev-harness
```

Expected: identify the smallest docs location that already describes harness navigation or command flow.

- [ ] **Step 2: Add the documented command contract**

Add concise wording to the selected docs:

```markdown
### Development Navigation Map

Use `e2e-harness map <repo> --state <run-state.json>` for the shortest "you are here" view. The map is a read-only projection of the current `next` result and does not advance lifecycle state.

The map reports:

- current lifecycle, workflow stage, and phase
- ready/blocked status
- one next safe action
- active dispatch work
- allowed and forbidden writes now
- required evidence and key artifact paths

Use `next --json-full` or the `full_result_path` when you need the complete workflow plan, execution packet, todo policy, or checkpoint details. Use `doctor --state` when environment health or state consistency looks abnormal.
```

- [ ] **Step 3: Run focused tests**

Run:

```powershell
python -m unittest tests.test_unified_cli.UnifiedCliTests.test_next_cli_quiet_default_writes_full_result_artifact tests.test_unified_cli.UnifiedCliTests.test_compact_payload_preserves_minimal_navigation_map_when_truncated tests.test_enterprise_harness_architecture.CliCommandFacadeContractTests.test_navigation_map_projection_reports_you_are_here_and_single_action tests.test_enterprise_harness_architecture.CliCommandFacadeContractTests.test_coordinator_summary_persists_navigation_map_additively tests.test_enterprise_harness_architecture.CliCommandFacadeContractTests.test_map_cli_facade_returns_navigation_map_only
```

Expected: PASS.

- [ ] **Step 4: Run broader regression**

Run:

```powershell
python -m unittest discover -s tests -p "test_unified_cli.py"
python -m unittest discover -s tests -p "test_enterprise_harness_architecture.py"
```

Expected: PASS.

- [ ] **Step 5: Run GitNexus detect changes before any commit or handoff**

Run GitNexus:

```text
gitnexus_detect_changes(scope="all", repo="e2e-dev-workflow")
```

Expected: changed symbols are limited to `navigation_map.py`, `coordinator_flow.next_step`, compact output projection, coordinator summary projection, optional map CLI registration, and tests/docs.

- [ ] **Step 6: Sync installed skill copies if this will be used by live runtimes**

Run:

```powershell
node tools\install-e2e-dev-harness.mjs --sync --yes --json
```

Expected: source skill is synced to `.codex`, `.claude`, and `.agents` installed copies with no unexpected drift.

- [ ] **Step 7: Smoke the installed command surface**

Run:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py --help
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py map . --state docs/agent-runs/<run>/run-state.json
```

Expected: `map` appears in help. The second command prints only the `e2e-dev-harness.navigation-map.v1` payload for a real or fixture run-state path.

- [ ] **Step 8: Commit**

Run:

```powershell
git add README.md docs skills tests
git commit -m "docs: document development navigation map"
```

---

## Final Verification Checklist

- [ ] `navigation_map.py` has no file writes and no lifecycle transition calls.
- [ ] `next` full result includes `navigation_map`.
- [ ] `next` compact stdout includes compact `navigation_map`.
- [ ] Compact truncation keeps `you_are_here`, `status`, and `next_single_action`.
- [ ] `coordinator-summary.json` includes additive `navigation_map`.
- [ ] Optional `map` command returns only navigation map payload.
- [ ] `doctor` remains diagnostic-only and is not called by the map builder.
- [ ] `gitnexus_detect_changes(scope="all", repo="e2e-dev-workflow")` confirms expected impact.
- [ ] Installed runtime copies are synced if the live harness should expose the change.

## Self-Review

- Spec coverage: The plan covers the requested unified "you are here" view, preserves existing fragmented command contracts, and keeps `doctor` as diagnostic support rather than the default navigation owner.
- Placeholder scan: No task contains TBD/TODO-style placeholder work. The parser-registration step includes exact import, wrapper, parser, output-argument tuple, and main-dispatch changes for the current CLI structure.
- Type consistency: The same `navigation_map` payload shape is used in builder, `next` result, compact stdout, coordinator summary, and optional `map` command.
