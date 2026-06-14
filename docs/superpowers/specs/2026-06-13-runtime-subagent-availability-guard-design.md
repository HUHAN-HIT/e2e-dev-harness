# Runtime Subagent Availability Guard (residual S-A)

> Status: implemented · 2026-06-13 · scope: **runtime portability of worker descriptors**
> Companion to `docs/superpowers/specs/2026-06-13-loop-engineering-truth-chain-closure-design.md`
> (its Slice 0 — land this working tree as a clean SSOT baseline before the
> truth-chain changes stack on top).

## Problem

A worker packet may declare a runtime-specific subagent type
(`runtime_subagent_type`, e.g. a custom `tdd-red` Task subagent). The Task/`task`
runtime adapters (`_claude_code`, `_opencode`) emitted that declared type into the
launchable descriptor **unconditionally**. On a runtime that does not actually have
that subagent registered, the spawn fails — a silent fan-out break that surfaces
only at dispatch time, on exactly the runtimes the harness is meant to be portable
across. The coordinator had no way to know, before spawning, whether a declared
subagent existed.

## Contract: confirm-or-fall-back

A declared subagent type is honored **only when the runtime confirms it exists**;
otherwise the descriptor falls back to the universally-available portable type and
**records why**. Confirmation is an explicit, env-supplied allowlist so the harness
never assumes a non-portable capability it cannot verify.

- `E2E_HARNESS_AVAILABLE_SUBAGENTS` — comma/semicolon-separated allowlist of the
  subagent types the current runtime actually has (e.g. `tdd-red,code-reviewer`).
  `*` confirms any declared type (a runtime that opts into trusting packets).
- `PORTABLE_SUBAGENT_TYPE = "general-purpose"` — the fallback every supported
  runtime is guaranteed to provide.

Selection precedence (`_subagent_selection`, `adapters/runtime/__init__.py`):

1. **env override** — `E2E_HARNESS_SUBAGENT_TYPE_<ROLE>` set → use it
   (`subagent_type_source: "env"`). The operator's explicit per-role choice always wins.
2. **confirmed packet declaration** — packet declares `runtime_subagent_type` AND it
   is in `E2E_HARNESS_AVAILABLE_SUBAGENTS` (or `*`) → use it
   (`subagent_type_source: "packet"`).
3. **portable fallback** — packet declares a type that is NOT confirmed → use
   `general-purpose` (`subagent_type_source: "portable-fallback"`,
   `subagent_fallback_reason: "runtime_subagent_not_confirmed"`).
4. **default** — packet declares nothing → use `general-purpose`
   (`subagent_type_source: "default"`).

## Descriptor fields (additive)

Every Task/`task` descriptor now carries, alongside `arguments.subagent_type`:

- `requested_subagent_type` — what the packet/role asked for (before any fallback).
- `subagent_type_source` — `env` | `packet` | `portable-fallback` | `default`.
- `subagent_fallback_reason` — present ONLY on a fallback; today the sole value is
  `runtime_subagent_not_confirmed`. This is the attribution a downstream auditor
  (truth-chain Phase 2's coordinator projections) reads to see *why* a worker ran
  under the portable subagent instead of its requested one.

The builtin agent-team provider now emits the declared type into the packet
(`include_subagent_type=True`, `adapters/agent_team/builtin.py`) so the adapter can
make this confirm-or-fall-back decision per worker.

## Why this lands before the truth chain

Phase 2 of the truth-chain arc audits fan-out from the verified event log. A
descriptor that silently claimed an unavailable subagent would be an unaudited
failure mode; `subagent_fallback_reason` makes the degradation **explicit and
attributable** — the same "loud, not silent" principle the truth-chain witness
applies to run-state. Committing it as a clean baseline keeps the truth-chain diff
focused on the event-log seam, not entangled with runtime-adapter changes.

## Compatibility

- No env set → declared types are never confirmed → descriptors use the portable
  `general-purpose` with `subagent_type_source: "portable-fallback"` or `"default"`.
  This is the safe default: portable everywhere, no spawn failures.
- The descriptor schema (`e2e-dev-harness.worker-descriptor.v1`) gains additive
  fields only; existing consumers that read `arguments.subagent_type` are unchanged.
- `--runtime codex` and `--runtime manual` descriptors are unaffected (they carry no
  Task/`task` subagent type).
