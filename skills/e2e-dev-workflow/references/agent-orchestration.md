# Agent Orchestration

Use this reference when a Java/Spring 6/Maven change benefits from smaller, isolated agent contexts.

## Modes

| Mode | Use when | Behavior |
| --- | --- | --- |
| `single` | Small, single-module, low-risk work | One agent runs clarification, use-case design, TDD, and implementation. |
| `multi` | User asks for split agents, cross-service work, contract/data changes, or high risk | Separate agents own requirements, use cases, tests, service-scoped code, and coverage review. |
| `auto` | Default recommendation mode | The helper chooses based on repo shape, design doc size, services, and risk keywords. |

Do not spawn subagents unless the runtime supports them and the user has explicitly allowed multi-agent work. If subagents are unavailable, emulate the same separation by completing one artifact at a time and keeping each handoff file small.

## Service Scope

`kg_refresh.detect()` reports all service candidates. Treat that list as discovery data, not as the implementation list.

- `--service-scope discovery`: pre-clarification/default when affected services are unknown. Return only a lean service inventory and next steps; do not generate agent plans, handoff artifacts, or per-service plans from all candidates.
- `--service-scope affected`: post-clarification mode. Generate service plans only for `--service` or `--path` matches.
- `--service-scope all`: explicit whole-repo mode. Use only when every service is genuinely in scope.

This mirrors AGENT loading: first discover services, then narrow the implementation plan after requirements and use cases identify affected services.

## Agent Roles

### Requirements Clarifier

Inputs:

- User request or design seed
- Current knowledge graph refresh summary
- Existing docs, ADRs, and public API references
- `memory/project.md`, `memory/decisions.md`, `memory/workflow-preferences.md`

Outputs:

- `docs/agent-runs/<date-feature>/handoffs/01-requirements-clarifier.md`
- Goal, non-goals, constraints, acceptance criteria, open questions

Gate:

- Open questions that affect behavior, APIs, data, ownership, or tests must be resolved before the next role starts.

### Use Case Designer

Inputs:

- Approved requirements artifact
- Knowledge graph summary
- `memory/service-boundaries.md`, `memory/graph-findings.md`

Outputs:

- `docs/agent-runs/<date-feature>/handoffs/02-use-case-designer.md`
- Happy paths, failure paths, actors, cross-service flows, data effects, contracts, observability

Gate:

- Every acceptance criterion maps to at least one use case or is explicitly deferred.

### Test Case Developer

Inputs:

- Approved requirements and use cases
- `superpowers:test-driven-development`
- Java/Spring test guidance
- `memory/workflow-preferences.md`, `memory/decisions.md`

Outputs:

- `docs/agent-runs/<date-feature>/handoffs/03-test-case-developer.md`
- First red test, test type selection, Maven command scope, contract/integration coverage
- Optionally failing test files when implementation is ready to begin

Gate:

- Production code cannot start until the first red test has been written and observed failing for the expected reason.

### Service-Scoped Code Developer

Inputs:

- Approved requirements, use cases, test plan
- Failing tests
- Service-specific implementation plan under `docs/agent-runs/<date-feature>/service-plans/<service>/implementation-plan.md`
- Knowledge graph summary
- The service's `AGENT.md`
- `memory/service-boundaries.md`, `memory/graph-findings.md`, `memory/decisions.md`

Outputs:

- Minimal production code through Red-Green-Refactor
- Updated tests
- `docs/agent-runs/<date-feature>/service-plans/<service>/code-agent.md`
- `docs/agent-runs/<date-feature>/service-plans/<service>/unit-test-evidence.txt`
- `docs/agent-runs/<date-feature>/service-plans/<service>/coverage-matrix.md`
- `docs/agent-runs/<date-feature>/service-plans/<service>/business-review.md`

Gate:

- Refactor only while green. Edit only the assigned service/module plus shared files explicitly listed in the service plan. Broaden Maven verification before completion.

### Coverage Reviewer

Inputs:

- Requirements, use cases, test plan, service implementation plans
- Service-scoped code agent handoffs and unit-test evidence
- Final diff or code refs

Outputs:

- `docs/agent-runs/<date-feature>/evidence/coverage-matrix.md`
- `docs/agent-runs/<date-feature>/evidence/business-review.md`
- `docs/agent-runs/<date-feature>/evidence/verification.txt`

Gate:

- Every acceptance criterion maps to a use case, service plan, tests, code refs, and business review evidence before completion.

## Handoff Rules

- Treat handoff files as the source of truth, not chat memory.
- Put agent process artifacts under `docs/agent-runs/<date-feature>/`.
- Keep `docs/design/` for durable design documents and reusable templates.
- Keep multi-service implementation details under `docs/agent-runs/<date-feature>/service-plans/<service>/`.
- Keep each handoff artifact focused and under roughly 300 lines unless the task truly requires more.
- Include `Open Questions: None` explicitly before the next phase proceeds.
- Name assumptions and mark whether they are approved, inferred, or still pending.
- Record knowledge graph refresh location and timestamp in the requirements or use-case artifact.
- Record proposed memory updates in the phase handoff artifact first. Append them to `memory/*.md` only after verification or user approval.

## Parallelism

Parallel work is useful only after requirements are stable:

- The Use Case Designer and Test Case Developer may overlap only when acceptance criteria are stable.
- Code Developer starts after the first red test is observed.
- For multiple services, split Code Developer work by service or module with disjoint file ownership.
- Service-scoped Code Developers may run in parallel only after requirements, cross-service flows, contracts, and service plans are stable.
- Coverage Reviewer runs after service-scoped developers finish and blocks completion if any acceptance criterion lacks tests, code refs, or business review.

## Recommended Invocation Pattern

1. Run `superpowers_probe.py --mode strict`.
2. Run `kg_refresh.py . --mode auto`.
3. Run `memory_capture.py scan .`.
4. Run `orchestration_plan.py . --mode auto --service-scope discovery --design-doc <doc>` to get service candidates and next steps only.
5. After affected services are clear, run `orchestration_plan.py . --mode auto --service-scope affected --service services/<service> --design-doc <doc>`.
6. Create an archive with `e2e_dev_workflow.py plan . --design-doc <doc> --service-scope affected --service services/<service> --create-archive`.
7. In `multi` mode, update the handoff artifacts under `docs/agent-runs/<date-feature>/handoffs/` and the service plans under `docs/agent-runs/<date-feature>/service-plans/<service>/`.
8. Gate each phase with review before passing work forward.
9. Run `e2e_dev_workflow.py gate . --phase completion ...` before reporting done.
