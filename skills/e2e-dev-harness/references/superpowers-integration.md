# Superpowers Integration

This skill treats Superpowers as a pluggable process adapter.

## Modes

Set mode with `E2E_DEV_HARNESS_SUPERPOWERS_MODE` or pass `--mode` to `scripts/superpowers_probe.py`. The legacy `E2E_DEV_WORKFLOW_SUPERPOWERS_MODE` name is still accepted for backward compatibility.

| Mode | Behavior |
| --- | --- |
| `auto` | Default. Use Superpowers when discovered; otherwise continue with the built-in clarification gate and report the missing adapter. |
| `strict` | Block design clarification and implementation if required Superpowers sub-skills are missing. |
| `optional` | Probe and report Superpowers status, but never block. |
| `off` | Skip Superpowers entirely and use the built-in workflow. |

## Required Sub-Skills

For design clarification:

- `superpowers:using-superpowers`
- `superpowers:brainstorming`

For implementation planning and coding:

- `superpowers:writing-plans`
- `superpowers:test-driven-development`

`superpowers:test-driven-development` is the authoritative TDD process. Local Java/Spring references are addenda for test style and Maven command selection, not a replacement.

Prefer native skill invocation when the runtime exposes Superpowers skills. If the runtime only has local plugin files, use the probe output paths as a compatibility fallback.

## Discovery

The probe checks, in order:

1. `SUPERPOWERS_SKILLS_DIR`
2. `SUPERPOWERS_ROOT`
3. Codex caches and skill directories: `.codex/plugins/...`, `.codex/skills`, `.agents/skills`
4. Claude Code skill/plugin directories: `.claude/skills`, `.claude/plugins/...`
5. Gemini/custom directories: `.gemini/skills`, `.config/superpowers/skills`

Use explicit environment variables in CI or custom harnesses so the adapter does not depend on cache layout.

## Clarification Contract

When Superpowers is available, apply `superpowers:brainstorming` as the primary design clarification process:

- Explore project context first.
- Ask clarifying questions before implementation.
- Propose 2-3 approaches with trade-offs.
- Present the design and obtain user approval.
- Write the design/spec document.
- Do not start implementation until the written spec is reviewed and approved.

The local `clarification_gate.py` remains useful as a machine-checkable fallback for Markdown design notes.
