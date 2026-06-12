---
name: e2e-harness-tdd-red
description: Use for e2e-dev-harness tdd-red worker tasks that write failing tests proving acceptance criteria before any implementation, from a fresh isolated context.
---

# E2E Harness TDD Red Worker

Do not inherit coordinator chat context.

Use only the context pack, the service design, the acceptance criteria, and the test impact plan listed in the schedule.

Write the failing red test files and the red-test evidence named in the task outputs.

Run the service test command and capture the failing red test output before returning evidence.

Stop after the red test fails for the intended reason; do not implement production code in this task.

## 契约 (e2e-dev-harness)

- Superpowers is an external skill system. If it is unavailable, continue directly with this worker's expected_outputs and harness contract instead of inventing behavior or stopping.
- **方法委派**: 用 `superpowers:test-driven-development`(红阶段)写出证明验收标准的失败测试。
- **expected_outputs**: 产出证据键 `failing_tests` —— 提交失败测试证据后:
  `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase RED --key failing_tests --path <evidence-path>`
- **上下文**: 不继承 coordinator 对话;只用 packet 的 `context_paths`。
