---
name: e2e-harness-completion
description: Use for e2e-dev-harness coverage-review and completion worker tasks that assemble the coverage matrix, completion evidence, and strict guard report from a fresh isolated context.
---

# E2E Harness Completion Worker

Do not inherit coordinator chat context.

Use only the context pack, the implementation manifests, the coverage matrix, the reviews, and any rework records listed in the schedule.

Write the completion evidence, archive, and strict guard report named in the task outputs.

Run the coverage gate and the strict completion guard before returning evidence.

Stop after the guard report is written; do not reopen implementation tasks.

## v2 契约 (e2e-dev-harness-v2)

- **方法委派**: 用 `superpowers:verification-before-completion` 做完成前验证(全测通过、验收对齐)。
- **expected_outputs**: 产出证据键 `verification` —— 验证通过后:
  `python skills/e2e-dev-harness-v2/scripts/e2e_dev_harness_v2.py submit --state <run-state> --phase VERIFIED --key verification --path <evidence-path>`
- **上下文**: 不继承 coordinator 对话;只用 packet 的 `context_paths`。
