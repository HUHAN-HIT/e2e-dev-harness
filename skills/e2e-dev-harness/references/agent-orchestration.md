# Agent Orchestration

Agent-team support keeps four responsibilities separate:

```text
Lifecycle:
  pipeline + Phase define the evidence a phase needs.

Agent team:
  provider/profile defines how many workers produce that evidence.

Runtime:
  adapter turns one worker packet into a runtime-specific descriptor.

Control plane:
  dispatch emits descriptors, submit records evidence, and gate advances state.
```

## Dispatch

`dispatch` builds an agent-team request from the current run-state phase, then
uses the builtin provider to create an `agent-team-plan`. It writes that plan to:

```text
docs/agent-runs/<run>/agent-team-plan.json
```

Each dispatch call also writes an invocation record:

```text
docs/agent-runs/<run>/dispatch-invocations/<phase>-<timestamp>.json
```

Single-worker phases preserve the legacy top-level worker packet fields and
`worker_descriptor` so existing automation can continue to read the old shape.
They also carry the profile-declared `runtime_subagent_type`, which records the
role-specific subagent the harness wants. Multi-worker phases add
`worker_descriptors`, one entry per planned worker.

## Profiles

Bundled profiles live under:

```text
skills/e2e-dev-harness/agent-teams/default-*.yaml
```

Project-local profiles may live under:

```text
.e2e/agent-teams/*.yaml
```

Project-local profiles are loaded only by explicit `--team-profile <name>`.
They do not silently override bundled defaults.

## Runtime Portability

Team providers emit portable worker packets. Runtime adapters own all launch
shape details:

- Codex uses `multi_agent_v1.spawn_agent` with `fork_context=false`.
- Claude Code uses `Task`.
- OpenCode uses `task`.
- Manual runtimes produce instructions and block auto-dispatch.

Packet-level `runtime_subagent_type` is supported by Claude Code and OpenCode,
but it is guarded for portability. Descriptors always record
`requested_subagent_type`; they use the requested runtime subagent only when a
per-role environment override is set or `E2E_HARNESS_AVAILABLE_SUBAGENTS`
confirms that the alias exists for the runtime. Otherwise they keep
`subagent_type=general-purpose` and record
`subagent_fallback_reason=runtime_subagent_not_confirmed`.

Resolution order:

```text
per-role env override -> confirmed packet runtime_subagent_type -> general-purpose fallback
```

## Gates

Gates remain evidence-key based. Agent-team metadata adds producer
accountability, but it does not replace real worker evidence.
