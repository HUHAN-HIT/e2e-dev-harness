# Agent Handoff Schema

Use this schema when splitting work across Requirements Clarifier, Use Case Designer, Test Case Developer, service-scoped Code Developer, and Coverage Reviewer agents.

Each agent writes a Markdown handoff file with YAML frontmatter:

```yaml
---
agent: requirements-clarifier
status: draft | blocked | ready
inputs:
  - user request
  - AGENT.md load order
  - knowledge graph status
outputs:
  - docs/agent-runs/<date-feature>/handoffs/01-requirements-clarifier.md
blocked_by: []
memory_updates_proposed: []
---
```

## Body Sections

- Summary
- Facts used
- Decisions made
- Open questions
- Downstream assumptions
- Verification or review evidence
- Proposed memory updates

## Role Contracts

## Archive Layout

Generated agent files belong under:

```text
docs/agent-runs/<date-feature>/
  exec-plan.md
  prepare.json (optional status output)
  handoffs/
    01-requirements-clarifier.md
    02-use-case-designer.md
    03-test-case-developer.md
    04-code-developer.md
  service-plans/
    <service>/
      implementation-plan.md
      code-agent.md
      unit-test-evidence.txt
      coverage-matrix.md
      business-review.md
      rework-NNN.md
  evidence/
    knowledge-graph-refresh.json
    red-test.txt
    green-test.txt
    coverage-matrix.md
    business-review.md
    verification.txt
  proposed-memory-updates.md
  rework/
    rework-NNN.md
```

Keep `AGENT.md` files in their directory scopes. Do not move them into this archive.

Knowledge graph refresh skips `agent-runs` by default so previous execution traces do not pollute current project analysis.

Requirements Clarifier:
- Owns goal, non-goals, constraints, acceptance criteria, open questions.
- Stops while behavior/API/data/test-impacting questions remain unresolved.

Use Case Designer:
- Owns happy paths, failure paths, data effects, contracts, cross-service sequence.
- Maps every acceptance criterion to at least one use case or marks it deferred.

Test Case Developer:
- Owns test strategy, first red test, contract tests, Maven scope, red-test evidence path.
- Does not modify production code.

Code Developer:
- Owns minimal implementation, red-green-refactor, service-local verification evidence, residual risk report.
- Does not start without approved requirements, use cases, test plan, and red-test evidence.
- For multi-service work, each Code Developer owns exactly one service/module and writes under `service-plans/<service>/`.

Coverage Reviewer:
- Owns final design-to-code/test coverage and business logic review.
- Builds a matrix with `id`, `acceptance`, `use_case`, `service`, `tests`, `code_refs`, `business_review`, and `status`.
- Blocks completion if any acceptance criterion lacks test evidence, code refs, or business review.
- Accepts unit-test evidence only when it is structured command JSON with `exit_code: 0`.
- Checks Spring static check results unless the run explicitly documents why the check was skipped.
- Creates a rework item instead of directly asking for code patches when review finds missed behavior, missing tests, failed verification, business-logic risk, or multi-service contract gaps.
- Blocks completion while any rework item is `open`, `in-progress`, `blocked`, or `deferred` without explicit approval.

## Memory Rule

Agents may propose memory updates in their handoff files. The controlling agent writes durable memory only after the fact is verified or user-approved.
