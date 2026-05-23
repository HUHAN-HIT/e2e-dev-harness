# ExecPlan Guidance

Use an ExecPlan for complex features, significant refactors, cross-service changes, migrations, or work likely to span multiple agent turns.

An ExecPlan is a living document. Keep it updated as facts change. It is not a one-time proposal.

## Required Sections

- Design source: issue, design doc, or user-approved requirement.
- Current state: loaded AGENT files, memory reviewed, graph status, affected services.
- Target behavior: goal, non-goals, acceptance criteria.
- Handoff artifacts: requirements, use cases, test plan, implementation plan, service-scoped plans.
- Agent protocol: role ownership, inputs, outputs, stop conditions.
- Milestones: small verifiable implementation steps.
- Evidence: commands, graph status, red test output, green/unit test output, coverage matrix, business review, residual risks.

## Archive Location

By default, generated agent-run files are archived under:

```text
docs/agent-runs/<date-feature>/
  exec-plan.md
  handoffs/
  service-plans/
    <service>/
  evidence/
  proposed-memory-updates.md
```

Use `docs/design/` for durable human-facing design docs and templates. Use `docs/agent-runs/` for execution traces, handoffs, and evidence.

## Command

Generate a starter plan:

```bash
python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py plan . \
  --design-doc docs/design/<feature>.md \
  --create-archive
```

Before production-code edits, the ExecPlan should identify the first red test and where its failing output will be recorded. For multi-service changes, it should also list one implementation plan file per affected service. Before completion, it should reference the coverage matrix, unit test evidence, and business review evidence used by the completion gate.
