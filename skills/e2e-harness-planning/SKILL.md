---
name: e2e-harness-planning
description: Use for e2e-dev-harness implementation-planner worker tasks that turn clarified requirements into a service-sliced implementation plan and schedule from a fresh isolated context.
---

# E2E Harness Planning Worker

Do not inherit coordinator chat context. Use only the packet `context_paths` (run-state, requirements handoff, any R1 review, service-scope inputs).

## 契约 (e2e-dev-harness)

- **方法委派**: 用 `superpowers:writing-plans` 把澄清后的需求转成服务切片实现计划与调度。本 skill 只持 harness 专属胶水,不重造规划方法。
- **expected_outputs**: 产出证据键 `plan` —— 写实现计划到 `docs/agent-runs/<run>/handoffs/02-implementation-planner.md`,然后:
  `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase PLANNED --key plan --path <plan-path>`
- **上下文**: 不继承 coordinator 对话;只用 packet 的 `context_paths`。
- 仅就需求 handoff 未解决的范围/排序决策向用户提问。
