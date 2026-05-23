# Agent Orchestration

Use this reference when a Java/Spring 6/Maven change benefits from smaller, isolated agent contexts.

## Modes

| Mode | Use when | Behavior |
| --- | --- | --- |
| `single` | Small, single-module, low-risk work | One agent runs clarification, use-case design, TDD, and implementation. |
| `multi` | User asks for split agents, cross-service work, contract/data changes, or high risk | Separate agents own requirements, use cases, tests, and code. |
| `auto` | Default recommendation mode | The helper chooses based on repo shape, design doc size, services, and risk keywords. |

Do not spawn subagents unless the runtime supports them and the user has explicitly allowed multi-agent work. If subagents are unavailable, emulate the same separation by completing one artifact at a time and keeping each handoff file small.

## Agent Roles

### Requirements Clarifier

Inputs:

- User request or design seed
- Current knowledge graph refresh summary
- Existing docs, ADRs, and public API references
- `memory/project.md`, `memory/decisions.md`, `memory/workflow-preferences.md`

Outputs:

- `docs/design/<feature>-requirements.md`
- Goal, non-goals, constraints, acceptance criteria, open questions

Gate:

- Open questions that affect behavior, APIs, data, ownership, or tests must be resolved before the next role starts.

### Use Case Designer

Inputs:

- Approved requirements artifact
- Knowledge graph summary
- `memory/service-boundaries.md`, `memory/graph-findings.md`

Outputs:

- `docs/design/<feature>-use-cases.md`
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

- `docs/design/<feature>-test-plan.md`
- First red test, test type selection, Maven command scope, contract/integration coverage
- Optionally failing test files when implementation is ready to begin

Gate:

- Production code cannot start until the first red test has been written and observed failing for the expected reason.

### Code Developer

Inputs:

- Approved requirements, use cases, test plan
- Failing tests
- Knowledge graph summary
- `memory/service-boundaries.md`, `memory/graph-findings.md`, `memory/decisions.md`

Outputs:

- Minimal production code through Red-Green-Refactor
- Updated tests
- Verification command results

Gate:

- Refactor only while green. Broaden Maven verification before completion.

## Handoff Rules

- Treat handoff files as the source of truth, not chat memory.
- Keep each handoff artifact focused and under roughly 300 lines unless the task truly requires more.
- Include `Open Questions: None` explicitly before the next phase proceeds.
- Name assumptions and mark whether they are approved, inferred, or still pending.
- Record knowledge graph refresh location and timestamp in the requirements or use-case artifact.
- Record proposed memory updates in the phase handoff artifact first. Append them to `memory/*.md` only after verification or user approval.

## Parallelism

Parallel work is useful only after requirements are stable:

- The Use Case Designer and Test Case Developer may overlap only when acceptance criteria are stable.
- Code Developer starts last.
- For multiple services, split Code Developer work by service or module with disjoint file ownership.

## Recommended Invocation Pattern

1. Run `superpowers_probe.py --mode strict`.
2. Run `kg_refresh.py . --mode auto`.
3. Run `memory_capture.py scan .`.
4. Run `orchestration_plan.py . --mode auto --design-doc <doc>`.
5. In `multi` mode, create or update the four handoff artifacts.
6. Gate each phase with review before passing work forward.
