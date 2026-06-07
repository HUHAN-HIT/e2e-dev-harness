---
name: e2e-harness-planning
description: Use for e2e-dev-harness implementation-planner worker tasks that turn clarified requirements into a service-sliced implementation plan and schedule from a fresh isolated context.
---

# E2E Harness Planning Worker

Do not inherit coordinator chat context.

Use only the context pack, the requirements handoff, any R1 review, and service-scope inputs listed in the schedule.

Write the implementation plan and service schedule evidence named in the task outputs.

Run `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py gate . --phase plan` before returning evidence.

Ask the user only for scope or sequencing decisions that the requirements handoff does not resolve.
