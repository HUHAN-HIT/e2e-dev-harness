---
name: e2e-harness-review
description: Use for e2e-dev-harness r1/r2/r3 reviewer worker tasks that independently review a phase from a fresh isolated context and never review their own implementation.
---

# E2E Harness Review Worker

Do not inherit coordinator chat context.

Use only the context pack, the review request, the relevant handoffs, and the invocation JSON listed in the schedule.

Write the phase review report named in the task outputs.

Run `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py gate . --phase <review-phase>` before returning evidence.

Stop after the review report is written; do not modify implementation files.
