---
name: e2e-harness-clarification
description: Use for e2e-dev-harness requirements-clarifier worker tasks that must clarify intent, acceptance criteria, impact, and open questions from a fresh isolated context.
---

# E2E Harness Clarification Worker

Do not inherit coordinator chat context.

Use only the context pack, allowed inputs, project instructions selected for clarification, and GitNexus/dependency evidence requested by the schedule.

Write `docs/agent-runs/<run>/handoffs/01-requirements-clarifier.md`.

Ask the user only for intent confirmation, unresolved product decisions, or explicit tool-degradation approval.

## v2 契约 (e2e-dev-harness-v2)

- **方法委派**: 用 `superpowers:brainstorming` 完成澄清(意图、验收标准、影响、开放问题)。本 skill 只持 harness 专属胶水,不重造方法。
- **expected_outputs**: 产出证据键 `clarification` —— 写 `docs/agent-runs/<run>/handoffs/01-requirements-clarifier.md`,然后:
  `python skills/e2e-dev-harness-v2/scripts/e2e_dev_harness_v2.py submit --state <run-state> --phase CLARIFIED --key clarification --path <handoff-path>`
- **上下文**: 不继承 coordinator 对话;只用 packet 的 `context_paths`。
