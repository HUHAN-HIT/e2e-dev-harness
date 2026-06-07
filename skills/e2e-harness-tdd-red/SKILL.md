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
