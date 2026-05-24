# Agent Handoff Schema

Use this schema when splitting work across Requirements Clarifier, Use Case Designer, R1/R2/R3 semantic Reviewer agents, Test Case Developer, service-scoped Code Developer, and Coverage Reviewer agents.

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

Each role owns a narrow context boundary and writes only its promised outputs. Later roles consume the previous files as artifacts instead of reloading the whole conversation.

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
  review-requests/
    R1-design-review-request.md
    R2-test-review-request.md
    R3-implementation-review-request.md
  reviews/
    R1-design-review.md
    R2-test-review.md
    R3-implementation-review.md
  service-plans/
    <service>/
      implementation-plan.md
      code-agent.md
      review-requests/
        R2-test-review-request.md
        R3-implementation-review-request.md
      reviews/
        R2-test-review.md
        R3-implementation-review.md
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

Semantic Reviewers:
- R1 Design Reviewer checks requirements, AC completeness, affected modules, security-sensitive paths, and reference-pattern consistency before planning.
- R2 Test Reviewer checks red-test depth, happy/failure coverage, security paths, and contract coverage before production code.
- R3 Implementation Reviewer checks code/test completeness, security flaws, anti-patterns, and project-pattern consistency before completion.
- Review requests use fields: `Phase`, `Reviewer Role`, `Context Package`, `Allowed Inputs`, `Forbidden`, and `Output`.
- Review reports use fields: `Phase`, `Reviewer`, `Review Request`, `Developer Agent`, `Reviewer Agent`, `Independence`, `Context Boundary`, `No Code Changes`, `Scope`, `Inputs Reviewed`, `Findings`, `Required Rework`, and `Status`.
- `Developer Agent` and `Reviewer Agent` must be different. `Independence` must be `independent-agent`. `Context Boundary` must be request-scoped with no inherited developer chat context. `No Code Changes` must be confirmed/read-only.
- The `Review Request` file must exist, match the report phase, and declare the report as its exact `Output`.
- Findings become rework items; reviewer agents do not patch implementation directly.

Code Developer:
- Owns minimal implementation, red-green-refactor, service-local verification evidence, residual risk report.
- Does not start without approved requirements, use cases, test plan, and red-test evidence.
- For multi-service work, each Code Developer owns exactly one service/module and writes under `service-plans/<service>/`.
- Does not write R1/R2/R3 semantic review reports.

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
