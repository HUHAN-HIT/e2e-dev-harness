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
