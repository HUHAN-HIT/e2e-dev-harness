---
name: e2e-harness-clarification
description: Use for e2e-dev-harness requirements-clarifier worker tasks that must clarify intent, acceptance criteria, impact, and open questions from a fresh isolated context.
---

# E2E Harness Clarification Worker

Do not inherit coordinator chat context.

Use only the context pack, allowed inputs, project instructions selected for clarification, and GitNexus/dependency evidence requested by the schedule.

Write `docs/agent-runs/<run>/handoffs/01-requirements-clarifier.md`.

Run `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py clarify . --design-doc <design-doc>` before returning evidence.

Ask the user only for intent confirmation, unresolved product decisions, or explicit tool-degradation approval.
