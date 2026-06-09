---
name: e2e-harness-review
description: Use for e2e-dev-harness r1/r2/r3 reviewer worker tasks that independently review a phase from a fresh isolated context and never review their own implementation.
---

# E2E Harness Review Worker

Do not inherit coordinator chat context. Use only the packet `context_paths` (run-state, the review request, relevant handoffs).

## 契约 (e2e-dev-harness)

- **方法委派**: 用 `superpowers:requesting-code-review` 发起审查、`superpowers:receiving-code-review` 消化反馈。本 skill 只持 harness 专属胶水。
- **expected_outputs**: 产出证据键 `review` —— 写审查报告到 `docs/agent-runs/<run>/handoffs/<reviewer>-review.md`,然后:
  `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase REVIEWED --key <review-key> --path <report-path>`
- **review fan-out (critical tier)**: REVIEWED 在 critical/audited tier 要求三份独立证据 `r1_review` / `r2_review` / `r3_review`。每个 reviewer 在**全新隔离上下文**运行,**绝不 review 自己写过的实现**;coordinator 为三个键各 spawn 一个独立子 agent。
- **上下文**: 不继承 coordinator 对话;只用 packet 的 `context_paths`。写完报告即停,不改实现文件。
