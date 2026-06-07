# Petalpay Harness Stuck Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover the current `petalpay` harness run from `SERVICE_DESIGN_REQUIRED` and fix the harness command surface that makes `e2e-harness status/doctor` appear stuck.

**Architecture:** Treat the live `petalpay` repository as a runtime validation fixture and keep production Java code untouched until the harness lifecycle reaches an implementation-allowed phase. Fixes belong in the harness control plane: command routing, doctor/status invocation behavior, control-plane repair guidance, and dispatch/service-design state visibility. Preserve legacy CLI compatibility and run-state semantics.

**Tech Stack:** Python `unittest`, e2e-dev-harness Python CLI, Node `e2e-harness` shim, GitNexus MCP/CLI, PowerShell on Windows.

---

## File Structure

- Runtime fixture only: `C:/Users/14907/Documents/Codex/2026-05-23/petalpay/docs/agent-runs/2026-06-06-DESIGN-2026-002/`
  - Inspect `run-state.json`, `agent-schedule.json`, `.phase-lock`, `coordinator-summary.json`, `coordinator-results/*.json`, `events/*.json`.
  - Do not edit Java production source while lifecycle is `SERVICE_DESIGN_REQUIRED`.
- Modify if command-wrapper bug is confirmed:
  - `skills/e2e-dev-harness/scripts/e2e_dev_harness.py`
  - `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/doctor.py`
  - `skills/e2e-dev-harness/scripts/e2e_harness/cli/status.py`
  - `tools/install-e2e-dev-harness.mjs`
  - `bin/e2e-harness.js` or `lib/resolve.js` only if the Node shim is proven to be the failing layer.
- Test:
  - `tests/test_harness_doctor.py`
  - `tests/test_enterprise_harness_architecture.py`
  - `test/node-installer.test.js` or existing Node CLI tests if the shim is changed.

---

### Task 1: Freeze The Current Runtime Facts

**Files:**
- Read: `C:/Users/14907/Documents/Codex/2026-05-23/petalpay/docs/agent-runs/2026-06-06-DESIGN-2026-002/run-state.json`
- Read: `C:/Users/14907/Documents/Codex/2026-05-23/petalpay/docs/agent-runs/2026-06-06-DESIGN-2026-002/agent-schedule.json`
- Read: `C:/Users/14907/Documents/Codex/2026-05-23/petalpay/docs/agent-runs/2026-06-06-DESIGN-2026-002/coordinator-summary.json`

- [ ] **Step 1: Confirm the active run**

Run:

```powershell
e2e-harness next . --state docs/agent-runs/2026-06-06-DESIGN-2026-002/run-state.json
```

Expected: compact JSON returns `lifecycle: SERVICE_DESIGN_REQUIRED` and points to service-design dispatch.

- [ ] **Step 2: Confirm there is no active dispatch**

Run:

```powershell
$p='C:\Users\14907\Documents\Codex\2026-05-23\petalpay\docs\agent-runs\2026-06-06-DESIGN-2026-002'; @('control-plane.json','dispatch-spawn-requests','dispatch-invocations','dispatch-events') | ForEach-Object { $path=Join-Path $p $_; [pscustomobject]@{Path=$_;Exists=Test-Path $path} } | ConvertTo-Json
```

Expected: all four paths are either missing before recovery or intentionally created by a later recovery step.

- [ ] **Step 3: Confirm all scheduled tasks are still planned**

Run:

```powershell
$s=Get-Content -Raw -Path C:\Users\14907\Documents\Codex\2026-05-23\petalpay\docs\agent-runs\2026-06-06-DESIGN-2026-002\agent-schedule.json | ConvertFrom-Json; $s.tasks | Group-Object status | Select-Object Name,Count | ConvertTo-Json
```

Expected before recovery:

```json
{"Name":"planned","Count":27}
```

---

### Task 2: Repair Control-Plane Projection Before Dispatch

**Files:**
- Runtime-generated: `C:/Users/14907/Documents/Codex/2026-05-23/petalpay/docs/agent-runs/2026-06-06-DESIGN-2026-002/control-plane.json`
- Runtime-generated: `C:/Users/14907/Documents/Codex/2026-05-23/petalpay/docs/agent-runs/2026-06-06-DESIGN-2026-002/coordinator-results/*.json`

- [ ] **Step 1: Run the explicit control-plane import repair**

Run:

```powershell
e2e-harness control-plane repair . --run-dir docs/agent-runs/2026-06-06-DESIGN-2026-002 --scope legacy-import --json
```

Expected: command exits successfully and writes `docs/agent-runs/2026-06-06-DESIGN-2026-002/control-plane.json`.

- [ ] **Step 2: Re-check the next action**

Run:

```powershell
e2e-harness next . --state docs/agent-runs/2026-06-06-DESIGN-2026-002/run-state.json
```

Expected: still routes to service-design dispatch, but `state-control-plane` should no longer report `control-plane-missing`.

- [ ] **Step 3: Stop if projection repair mutates business code**

Run:

```powershell
git -C C:\Users\14907\Documents\Codex\2026-05-23\petalpay status --short
```

Expected: changes are confined to harness artifacts under `docs/agent-runs/`, `.e2e/`, and generated harness metadata. Any Java source change at this stage is a blocker.

---

### Task 3: Dispatch Service-Design Workers Through The Harness

**Files:**
- Runtime-generated: `C:/Users/14907/Documents/Codex/2026-05-23/petalpay/docs/agent-runs/2026-06-06-DESIGN-2026-002/dispatch-spawn-requests/`
- Runtime-generated: `C:/Users/14907/Documents/Codex/2026-05-23/petalpay/docs/agent-runs/2026-06-06-DESIGN-2026-002/dispatch-invocations/`
- Runtime-updated: `C:/Users/14907/Documents/Codex/2026-05-23/petalpay/docs/agent-runs/2026-06-06-DESIGN-2026-002/run-state.json`
- Runtime-updated: `C:/Users/14907/Documents/Codex/2026-05-23/petalpay/docs/agent-runs/2026-06-06-DESIGN-2026-002/agent-schedule.json`

- [ ] **Step 1: Dispatch one beat**

Run:

```powershell
e2e-harness dispatch-beat . --schedule docs/agent-runs/2026-06-06-DESIGN-2026-002/agent-schedule.json --state docs/agent-runs/2026-06-06-DESIGN-2026-002/run-state.json --runtime claude-code --max-workers 2
```

Expected: command creates spawn requests or records active dispatches for service-design work. It must not ask the coordinator to write service design slices locally.

- [ ] **Step 2: If runtime cannot spawn automatically, use the generated spawn request**

Run:

```powershell
Get-ChildItem docs/agent-runs/2026-06-06-DESIGN-2026-002/dispatch-spawn-requests -Force | Sort-Object LastWriteTime
```

Expected: one or two `*-spawn-request.json` / `*-prompt.md` files exist. Use those exact prompts to start isolated workers; do not paste full context into the coordinator chat.

- [ ] **Step 3: Close each worker only with scheduled evidence**

For each dispatched task, run the command shape returned by the worker packet:

```powershell
e2e-harness dispatch-complete . --schedule docs/agent-runs/2026-06-06-DESIGN-2026-002/agent-schedule.json --state docs/agent-runs/2026-06-06-DESIGN-2026-002/run-state.json --task-id <TASK_ID> --agent <AGENT_NAME> --evidence <SCHEDULED_OUTPUT_PATH>
```

Expected: task status advances from active/running to `completed`, and completion evidence is one of the task's declared outputs.

---

### Task 4: Validate The Service-Design Gate

**Files:**
- Read/update: `C:/Users/14907/Documents/Codex/2026-05-23/petalpay/docs/agent-runs/2026-06-06-DESIGN-2026-002/service-designs/*.md`
- Read/update: `C:/Users/14907/Documents/Codex/2026-05-23/petalpay/docs/agent-runs/2026-06-06-DESIGN-2026-002/run-state.json`

- [ ] **Step 1: Run the service-design gate**

Run:

```powershell
e2e-harness service-design . --state docs/agent-runs/2026-06-06-DESIGN-2026-002/run-state.json --schedule docs/agent-runs/2026-06-06-DESIGN-2026-002/agent-schedule.json --json
```

Expected: if all required service slices are valid, lifecycle advances toward `PLANNED`; otherwise output names exact missing evidence or malformed slice fields.

- [ ] **Step 2: Refresh navigation**

Run:

```powershell
e2e-harness next . --state docs/agent-runs/2026-06-06-DESIGN-2026-002/run-state.json
```

Expected after gate success: next action is no longer service-design dispatch; it should route to planning/TDD red/R2 review.

---

### Task 5: Reproduce And Fix `status/doctor` External Command Hang

**Files:**
- Modify only after GitNexus impact analysis:
  - `skills/e2e-dev-harness/scripts/e2e_dev_harness.py`
  - `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/doctor.py`
  - `skills/e2e-dev-harness/scripts/e2e_harness/cli/status.py`
  - `bin/e2e-harness.js`
  - `lib/resolve.js`
- Test:
  - `tests/test_harness_doctor.py`
  - `tests/test_enterprise_harness_architecture.py`
  - Node CLI tests covering `status -> doctor`

- [ ] **Step 1: Run GitNexus impact before code edits**

Run impact on the first symbol to edit, for example:

```text
gitnexus_impact({target: "run_from_args", file_path: "skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/doctor.py", direction: "upstream", repo: "e2e-dev-workflow"})
```

Expected: report blast radius before modifying a function. If risk is HIGH or CRITICAL, warn before editing.

- [ ] **Step 2: Add a failing regression test for command invocation parity**

Test intent: invoking doctor through the same path used by the shim must terminate and produce compact JSON.

Run:

```powershell
python -m unittest discover -s tests -p test_harness_doctor.py -k doctor
```

Expected before fix: a new focused test should fail or time out when reproducing the `python <script> doctor ... --compact-output` path.

- [ ] **Step 3: Implement the minimal fix**

Possible fix locations depend on the failing test:

- If direct Python script invocation hangs but `main()` called in-process does not, fix CLI entrypoint setup in `e2e_dev_harness.py`.
- If `e2e-harness status` hangs but direct Python invocation does not, fix Node command resolution in `lib/resolve.js` or process spawning in `bin/e2e-harness.js`.
- If only full/JSON output hangs, fix `output_contract.write_full_result(...)` or command-event emission.

- [ ] **Step 4: Verify focused behavior on the live `petalpay` fixture**

Run:

```powershell
e2e-harness status . --state docs/agent-runs/2026-06-06-DESIGN-2026-002/run-state.json
```

Expected: command returns within 5 seconds with compact JSON or clear doctor output; no 15-30 second timeout.

---

### Task 6: Sync Installed Runtime Copies And Verify

**Files:**
- Installed copies:
  - `C:/Users/14907/.claude/skills/e2e-dev-harness/`
  - `C:/Users/14907/.codex/skills/e2e-dev-harness/`
  - `C:/Users/14907/.agents/skills/e2e-dev-harness/`

- [ ] **Step 1: Sync installed copies**

Run from the harness repo:

```powershell
node tools/install-e2e-dev-harness.mjs --sync --yes --json
```

Expected: `.claude`, `.codex`, and `.agents` skill copies are updated.

- [ ] **Step 2: Verify installed command surface**

Run from `petalpay`:

```powershell
e2e-harness env
e2e-harness next . --state docs/agent-runs/2026-06-06-DESIGN-2026-002/run-state.json
e2e-harness status . --state docs/agent-runs/2026-06-06-DESIGN-2026-002/run-state.json
```

Expected: `env` reports `ok: true`; `next` and `status` both return without hanging.

---

### Task 7: Final Verification

**Files:**
- Read: harness repo git status and test outputs.
- Read: `petalpay` run-state and coordinator results.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
python -m unittest discover -s tests -p test_harness_doctor.py
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py -k Doctor
```

Expected: focused doctor/status and navigation tests pass.

- [ ] **Step 2: Run broad regression**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: full Python suite passes.

- [ ] **Step 3: Run GitNexus change audit before commit**

Run:

```text
gitnexus_detect_changes({repo: "e2e-dev-workflow", scope: "all"})
```

Expected: affected execution flows match doctor/status/dispatch control-plane surfaces. Unexpected Java/business repo changes are blockers.

- [ ] **Step 4: Confirm `petalpay` is no longer stuck**

Run from `petalpay`:

```powershell
e2e-harness next . --state docs/agent-runs/2026-06-06-DESIGN-2026-002/run-state.json
```

Expected: lifecycle has moved past `SERVICE_DESIGN_REQUIRED`, or the output names a specific worker-owned artifact/evidence blocker with an exact dispatch or complete command.

---

## Self-Review

- Spec coverage: The plan covers the live stuck run, missing dispatch artifacts, missing `control-plane.json`, service-design dispatch, service-design gate validation, `status/doctor` hang reproduction, installed-copy sync, and final GitNexus/test verification.
- Placeholder scan: No task uses `TBD`, open-ended "handle edge cases", or unspecified test commands.
- Type and command consistency: Commands use the observed active run `docs/agent-runs/2026-06-06-DESIGN-2026-002/run-state.json`; `dispatch-complete` placeholders are limited to worker-specific values that can only be known after dispatch creates concrete task packets.
