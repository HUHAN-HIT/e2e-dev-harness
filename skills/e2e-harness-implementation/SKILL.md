---
name: e2e-harness-implementation
description: Use for e2e-dev-harness implement worker tasks that make red tests green with minimal code, produce a manifest and coverage rows, from a fresh isolated context.
---

# E2E Harness Implementation Worker

Do not inherit coordinator chat context.

Use only the context pack, the service design, the red-test evidence, and the claimed task listed in the schedule.

Write the code changes, green tests, implementation manifest, and coverage rows named in the task outputs.

Run the service test command and the implementation gate before returning evidence.

Stop after tests pass and the manifest is written; do not perform R1/R2/R3 self-review in this session.

## 契约 (e2e-dev-harness)

- **方法委派**: 用 `superpowers:test-driven-development`(绿阶段)写最小实现让红测转绿;遇阻用 `superpowers:systematic-debugging`。
- **expected_outputs**: 产出证据键 `passing_tests` —— 测试转绿后:
  `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase IMPLEMENTED --key passing_tests --path <evidence-path>`
- **上下文**: 不继承 coordinator 对话;只用 packet 的 `context_paths`。
