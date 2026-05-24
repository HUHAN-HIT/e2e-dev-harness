# ExecPlan Guidance

Use an ExecPlan for complex features, significant refactors, cross-service changes, migrations, or work likely to span multiple agent turns.

An ExecPlan is a living document. Keep it updated as facts change. It is not a one-time proposal.

## Required Sections

- Design source: issue, design doc, or user-approved requirement.
- Current state: loaded AGENT files, memory reviewed, graph status, cross-service dependency report, affected services.
- Target behavior: goal, non-goals, acceptance criteria.
- Handoff artifacts: requirements, use cases, test plan, implementation plan, implementation manifest, service-scoped plans.
- Agent protocol: role ownership, inputs, outputs, stop conditions.
- Milestones: small verifiable implementation steps.
- Evidence: commands, graph status, GitNexus-first dependency report, implementation manifest, red test output, green/unit test output, coverage matrix, business review, residual risks.
- Rework log: missed requirements, missing tests/code, business review issues, return phase, status, and approval when deferred.

## Archive Location

By default, generated agent-run files are archived under:

```text
docs/agent-runs/<date-feature>/
  exec-plan.md
  handoffs/
  service-plans/
    <service>/
      implementation-manifest.md
      rework-NNN.md
  rework/
    rework-NNN.md
  evidence/
    cross-service-dependencies.json
    implementation-manifest.md
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

Before production-code edits, the ExecPlan should identify the first red test and where its failing output will be recorded. For multi-service or multi-module changes, it should also list one implementation plan file per affected service/module and reference `evidence/cross-service-dependencies.json`. Before completion, it should reference the dependency report, implementation manifest, coverage matrix, structured unit test command JSON, independent R1/R2/R3 semantic review requests and reports, Spring static check result, business review evidence, and rework gate result used by the completion gate.

## Implementation Manifest

Use `docs/agent-runs/<run>/evidence/implementation-manifest.md` to prevent self-selected coverage from hiding missed work. The table columns are:

```text
id | module | artifact | artifact_type | source | required | tests | status | evidence
```

Rows come from explicit task requirements, reference implementation inventory, dependency reports, and service plans. If the design itself names required classes/files, put them in explicit sections such as `Required Artifacts`, `Affected Classes`, or mark them with `[artifact] ClassName`; generic notes and examples are not treated as required artifacts. Required rows must point to existing artifacts and real tests. If a required artifact is missing, create a `missing-code` or `missing-test` rework item and return to the required phase.

## Re-entry Protocol

If completion review finds missed behavior, do not patch code directly from review notes. Add a rework item and return to the earliest necessary phase:

| Problem Type | Return Phase |
| --- | --- |
| `unclear-requirement`, `missing-acceptance` | `clarify` |
| `missing-use-case`, `business-logic-risk` | `use-case-design` |
| `missing-test` | `test-case-design` |
| `missing-code`, `test-failure` | `tdd-implement` |
| `multi-service-contract` | `plan` |

Use `Status: verified` only after the rework has red-test evidence, green command JSON, updated coverage/business review, and a passing completion gate. Use `Status: deferred` only with explicit approval such as `Approval: user-approved`.
