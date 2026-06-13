# Requirements Clarification: Plugin Agent Team Design

## Restated Intent

Implement the approved design in `docs/superpowers/specs/2026-06-11-plugin-agent-team-design.md`: add a plugin-style agent-team planning layer to `skills/e2e-dev-harness` while preserving the current deterministic control plane, evidence gates, runtime adapter boundary, and existing single-worker dispatch compatibility.

The requested feature is not a new runtime and not a replacement for lifecycle phases. It is an additive provider/profile layer between pipeline phase selection and runtime-specific worker descriptor generation:

```text
pipeline phase -> agent team provider/profile -> worker packet(s) -> runtime adapter -> runtime descriptor(s)
```

## Goals

- Add a pure `adapters/agent_team` package that can plan one or more workers for an active phase.
- Keep existing single-worker behavior unchanged for minimal and standard single-evidence phases.
- Allow packets to declare `runtime_subagent_type`, while preserving environment-variable precedence in Claude Code and OpenCode adapters.
- Thread agent-team output through dispatch so future phases can emit multiple runtime descriptors.
- Add bundled team profile files for minimal, standard, critical, and audited tiers.
- Enable critical/audited reviewer fan-out into R1/R2/R3 workers after provider parity and runtime descriptor tests are in place.
- Preserve manual runtime blocking and existing evidence-key-based gates.
- Update harness docs and run installed-copy sync after implementation.

## Non-Goals

- Do not add a new lifecycle enum such as `WAITING_DISPATCH`.
- Do not let runtime adapters own scheduling policy.
- Do not allow team providers to spawn tools, mutate `run-state.json`, or submit evidence.
- Do not allow project-local profiles to silently override bundled defaults.
- Do not parallelize code writers inside one service unless a future design adds disjoint edit-scope enforcement.

## Affected Scope

Primary implementation scope:

- `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/`
- `skills/e2e-dev-harness/scripts/e2e_harness/adapters/runtime/__init__.py`
- `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py`
- `skills/e2e-dev-harness/scripts/e2e_harness/core/dispatch.py` only if packet helper extension is needed.
- `skills/e2e-dev-harness/agent-teams/*.yaml`
- Focused tests under `skills/e2e-dev-harness/tests/`
- Documentation in `skills/e2e-dev-harness/SKILL.md` and `skills/e2e-dev-harness/references/agent-orchestration.md`

## Impact Summary

GitNexus exploration found the relevant runtime and dispatch surfaces:

- `adapters/runtime/__init__.py`: `_codex`, `get_adapter`, `spawn_worker`, and existing runtime descriptor tests.
- `cli/commands/dispatch.py`: `run`, consumed by CLI dispatch tests.
- Existing review fan-out expectations in `tests/test_review_fanout.py`.

Before editing named functions or methods, run GitNexus upstream impact on the exact symbols required by the design, especially `_subagent_type`, `_claude_code`, `_opencode`, `run` in `cli/commands/dispatch.py`, and `worker_packet`.

## Contracts

Agent team provider request:

- Schema: `e2e-dev-harness.agent-team-request.v1`
- Inputs include run-state path, runtime, pipeline, active phase metadata, context paths, selected profile, and constraints.
- The provider must be pure and deterministic.

Agent team plan:

- Schema: `e2e-dev-harness.agent-team-plan.v1`
- Contains provider, profile, phase, execution model, max workers, worker definitions, blocked parallelism, and evidence contract.
- Worker definitions must remain compatible with `runtime.spawn_worker(...)`.

Worker packet invariant:

- Schema remains `e2e-dev-harness.worker-packet.v1`.
- May include `runtime_subagent_type`.
- Runtime adapters translate packet intent into runtime-specific tool descriptors.

Runtime subagent precedence:

```text
environment override -> packet runtime_subagent_type -> portable default
```

Dispatch output:

- Existing single-worker keys must remain compatible.
- Team-aware output should include durable agent-team plan information and per-worker descriptors when a phase expands to multiple workers.
- Manual runtime remains blocked and must not mark the phase as dispatched.

## Acceptance Criteria

- AC-001: Builtin provider parity. A normal phase planned by the builtin provider produces the same worker packet fields as the current `core.dispatch.worker_packet(...)` behavior for single-worker phases.
- AC-002: Provider purity. Provider planning returns dictionaries and does not spawn runtimes, mutate run-state, or submit evidence.
- AC-003: Runtime subagent override. Claude Code and OpenCode descriptors honor packet-level `runtime_subagent_type` when no environment override exists.
- AC-004: Environment precedence. Existing environment override behavior continues to win over packet-declared `runtime_subagent_type`.
- AC-005: Codex compatibility. Codex descriptors remain model-unpinned and use `fork_context=false`.
- AC-006: Dispatch integration. Dispatch can consume an agent-team plan and emit descriptors for every ready worker while preserving existing single-worker dispatch compatibility.
- AC-007: Manual runtime safety. Manual or unknown runtime dispatch remains blocked and does not mark the phase as dispatched.
- AC-008: Profile validation. Bundled profile files validate deterministically; invalid project-local profiles fail with path and field information; project-local profiles load only by explicit name.
- AC-009: Critical/audited review fan-out. Critical and audited REVIEWED phases expand into independent R1, R2, and R3 reviewer workers, each with one expected evidence key.
- AC-010: Gate compatibility. Existing evidence-key gates still determine phase completion; agent-team metadata adds producer accountability without weakening gates.
- AC-011: Documentation and sync. Skill and orchestration docs describe the provider/profile/runtime boundary, and installer sync succeeds after implementation.

## Test Design

- Add provider unit tests for parity, purity, evidence contract shape, and review fan-out worker ids.
- Extend runtime adapter tests for packet-level subagent type and env precedence.
- Add dispatch integration tests for single-worker unchanged output, multiple descriptors, manual blocking, and agent-team metadata.
- Add profile schema tests for bundled profiles and invalid local profile diagnostics.
- Run focused pytest suites before broad verification.

## Open Questions

No user-blocking product decisions remain. The design document already recommends:

- Project-local profiles stay under `.e2e/agent-teams/`.
- Dispatch writes the phase-local `agent-team-plan.json` first.
- Critical reviewer fan-out is enabled after provider parity and descriptor tests pass.
- OpenCode preserves the current lowercase `task` descriptor contract.
