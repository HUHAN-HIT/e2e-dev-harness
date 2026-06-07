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
