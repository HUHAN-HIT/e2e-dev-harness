# Harness e2e-dev-harness �?U2: `spawn_worker` runtime seam (design)

**Date:** 2026-06-07 · **Branch:** `e2e-dev-harness-m2` · **Roadmap unit:** U2 (M2-tail)
**Roadmap:** [2026-06-07-e2e-dev-harness-remaining-work-roadmap.md](../plans/2026-06-07-e2e-dev-harness-remaining-work-roadmap.md) · **Design source:** [2026-06-07-e2e-dev-harness-redesign-design.md](2026-06-07-e2e-dev-harness-redesign-design.md) §5 ("runtime adapters �?收敛到一�?`spawn_worker(packet) -> handle` 接口").

## Problem

Legacy has two overlapping runtime-adapter families �?`runtime_adapters.py` (388L) and the thin `e2e_harness/adapters/runtime/{base,claude_code,codex_multi_agent,manual,opencode_task}.py` wrappers �?each exposing `spawn/ack/complete/recover`. Design §5 asks e2e-dev-harness to converge them into **one** narrow seam. There is **no legacy test** anchoring this (it is a redesign, not a faithful port), so U2 ships a fresh TDD suite.

## Key observation (grounds the contract)

Legacy `spawn()` never launches a process. It returns a runtime-specific **spawn-request descriptor** (`tool`, `arguments`, `ack_command`, `completion_command`, `context_policy`); the coordinator LLM performs the real tool call. e2e-dev-harness keeps this "pointer" philosophy �?the coordinator stays a pure control plane.

## Decisions (settled in brainstorming)

1. **Pure descriptor.** `spawn_worker(packet)` translates the packet into a launch **descriptor** and returns it as the "handle". It spawns nothing. Keeps the seam pure and unit-testable; honors "coordinator stays a pure control plane."
2. **Scope = claude-code + manual.** Two packet→descriptor mappings now (current backend-first, YAGNI). `codex` and `opencode` are **explicitly deferred** (see Deferred), not silently dropped �?re-adding each is just another mapping.
3. **Portable type, no model pin.** The claude-code descriptor sets `subagent_type` to a portable default `"general-purpose"`, overridable per-role via env `E2E_e2e_harness_SUBAGENT_TYPE_<ROLE>`. It pins **no model**, so the worker inherits the coordinator's accessible default �?the by-construction fix for the observed broken dispatch (model resolved to inaccessible `glm-4.7`).
4. **方案1 �?adapter module + additive CLI wiring.** Seam lives in `adapters/runtime/` (sibling to kg/scanner/memory/tier). The `dispatch` command additively emits `worker_descriptor` via an optional `--runtime` arg; existing dispatch output keys are unchanged.

## Interface

```python
# e2e_harness/adapters/runtime/__init__.py
def spawn_worker(packet: dict, runtime: str = "claude-code") -> dict
```

- **Input:** the existing `worker_packet` from `core/dispatch.py` �?`{schema, role, skill, context_paths[], expected_outputs[]}`. The seam consumes only the packet (so no packet-schema change is needed; the env override is keyed on `packet["role"]`).
- **Output ("handle"):** descriptor `schema = "e2e-dev-harness.worker-descriptor.v1"`.
- **Robustness:** unknown runtime �?falls back to `manual` with a `warning`, never raises (mirrors legacy `adapter_for`).

### claude-code descriptor
```jsonc
{
  "schema": "e2e-dev-harness.worker-descriptor.v1",
  "runtime": "claude-code",
  "tool": "Task",
  "arguments": {
    "description": "<role>: <skill>",
    "prompt": "<role/skill + context_paths + expected_outputs, fresh-context instruction>",
    "subagent_type": "general-purpose"   // or env override E2E_e2e_harness_SUBAGENT_TYPE_<ROLE>
  },
  "context_paths": ["..."],
  "expected_outputs": ["..."],
  "context_policy": "fresh Claude Code Task only; no inherited coordinator chat beyond these context_paths."
}
```
- **No `model` key.** (Regression-guarded by a test.)

### manual descriptor
```jsonc
{
  "schema": "e2e-dev-harness.worker-descriptor.v1",
  "runtime": "manual",
  "tool": null,
  "instruction": "Run the <skill> worker yourself using the listed context_paths; produce expected_outputs.",
  "context_paths": ["..."],
  "expected_outputs": ["..."]
}
```

## Wiring

`cli/commands/dispatch.py` gains an optional `--runtime` (default `claude-code`). After building the packet it adds `worker_descriptor = spawn_worker(packet, runtime)` to the JSON result. The pre-existing keys (`skill`, `expected_outputs`, `role`, `context_paths`) are untouched, so `test_dispatch_returns_pointer_packet` stays green. The seam computes a descriptor; it never calls the Task tool �?that remains the coordinator's job.

## Acceptance criteria

- `adapters/runtime/__init__.py` exposes `spawn_worker(packet, runtime="claude-code") -> dict`.
- Fresh `tests/test_runtime_spawn.py` (no legacy test) covering:
  - claude-code descriptor shape (schema, runtime, tool=`Task`, arguments incl. `prompt`).
  - `subagent_type` defaults to `general-purpose`; env `E2E_e2e_harness_SUBAGENT_TYPE_<ROLE>` overrides it.
  - **no `model` key anywhere in the descriptor** (regression guard for the glm-4.7 breakage).
  - `expected_outputs` and `context_paths` pass through unchanged.
  - manual mapping (`tool` null, has `instruction`).
  - unknown runtime �?manual fallback + `warning`, no exception.
- `dispatch` emits `worker_descriptor`; `--runtime manual` yields the manual descriptor; existing CLI dispatch assertions stay green.
- Full e2e-dev-harness suite green; changes confined to `skills/e2e-dev-harness/`; no legacy edits.

## Deferred (explicit, not dropped)

- **codex** (`multi_agent_v1.spawn_agent`) and **opencode** (`Task` w/ `agent`) runtime mappings �?re-add as additional `runtime` branches when a real flow needs them.
- `ack` / `complete` / `recover` runtime verbs �?e2e-dev-harness already records evidence/lifecycle via `submit` + the dispatch enum; the legacy per-runtime ack/complete/recover are not reintroduced unless a runtime needs out-of-band acknowledgement.
- Live worker observation (`DispatchStatus.RUNNING`) �?the pointer/descriptor model doesn't track mid-flight workers; wired only if a runtime can observe one.
