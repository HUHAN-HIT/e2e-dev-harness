# Agent Orchestration

Use this reference when a Java/Spring 6/Maven change benefits from smaller, isolated agent contexts.

## Modes

| Mode | Use when | Behavior |
| --- | --- | --- |
| `single` | Small, single-module, low-risk work | One implementation agent may run clarification, use-case design, TDD, and implementation, but R1/R2/R3 semantic reviews still require independent reviewer agents or separate reviewer sessions. |
| `multi` | User asks for split agents, cross-service work, contract/data changes, or high risk | Separate agents own requirements, use cases, tests, service-scoped code, and coverage review. |
| `auto` | Default recommendation mode | The helper chooses based on repo shape, design doc size, services, and risk keywords. |

Do not let an implementation agent review its own work. If the runtime cannot spawn subagents, use a separate reviewer session with only the review request and allowed artifact inputs. Same-chat/self-review is not an acceptable fallback for R1/R2/R3.

## Service Scope

`kg_refresh.detect()` reports all service candidates. Treat that list as discovery data, not as the implementation list.

- `--service-scope discovery`: pre-clarification/default when affected services are unknown. Return only a lean service inventory and next steps; do not generate agent plans, handoff artifacts, or per-service plans from all candidates.
- `--service-scope affected`: post-clarification mode. Generate service plans only for `--service` / `--path` matches or for design-declared affected services/modules that match discovered candidates.
- `--service-scope all`: explicit whole-repo mode. Use only when every service is genuinely in scope.

This mirrors AGENT loading: first discover services, then narrow the implementation plan after requirements and use cases identify affected services.
If `--service` does not match a discovered service path or service directory name, the helper blocks instead of silently planning no service work.

When `--service-scope auto` and no explicit service/path is supplied, the helper first uses verified dependency-report services. If none exist, it reads `Scope`, `Affected services/modules`, `Affected modules`, or equivalent Chinese headings from the design document and matches bullet items against discovered candidates. This includes root Maven modules such as `jeepay-core`, `jeepay-service`, and `jeepay-payment`, not only `services/*` directories. A matching design must generate one service plan, one code-agent handoff, and one service-local implementation manifest per affected module.

## Agent Roles

### Requirements Clarifier

Inputs:

- User request or design seed
- Current knowledge graph refresh summary
- Cross-service dependency report when HTTP/DMQ/service contracts are in scope
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
- Cross-service dependency report with unresolved dependency questions resolved or carried forward explicitly
- `memory/service-boundaries.md`, `memory/graph-findings.md`

Outputs:

- `docs/agent-runs/<date-feature>/handoffs/02-use-case-designer.md`
- Happy paths, failure paths, actors, cross-service flows, data effects, contracts, observability
- Initial implementation completeness notes: required modules, explicit file/class requirements, reference patterns to inventory

Gate:

- Every acceptance criterion maps to at least one use case or is explicitly deferred.
- Every affected module/service from the design is either in scope for implementation or explicitly out of scope with approval.

### R1 Design Reviewer

Inputs:

- Original user request or design seed
- Requirements and use-case artifacts
- Knowledge graph summary, dependency report, and selected project reference patterns

Outputs:

- `docs/agent-runs/<date-feature>/review-requests/R1-design-review-request.md`
- `docs/agent-runs/<date-feature>/reviews/R1-design-review.md`
- Findings on AC completeness, affected services/modules, security-sensitive behavior, hidden config/query requirements, and project pattern consistency

Gate:

- Planning waits until this review is `approved` or findings have rework/clarification items. The reviewer does not patch the design silently.
- The review report must reference the review request, name a different Developer Agent and Reviewer Agent, declare `Independence: independent-agent`, and state `No Code Changes: confirmed`.

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

### R2 Test Reviewer

Inputs:

- Requirements, use cases, and test plan
- Red test files or test snippets
- Target class/interface signatures and relevant existing tests

Outputs:

- `docs/agent-runs/<date-feature>/review-requests/R2-test-review-request.md`
- `docs/agent-runs/<date-feature>/reviews/R2-test-review.md`
- Service-local `docs/agent-runs/<date-feature>/service-plans/<service>/review-requests/R2-test-review-request.md` when services are split
- Service-local `docs/agent-runs/<date-feature>/service-plans/<service>/reviews/R2-test-review.md` when services are split

Gate:

- Production code waits until tests prove meaningful behavior. Shallow tests that only assert a code or DTO field become `missing-test` rework for high-risk ACs.
- R2 cannot be completed by the test author or code developer.

### Service-Scoped Code Developer

Inputs:

- Approved requirements, use cases, test plan
- Failing tests
- Service-specific implementation plan under `docs/agent-runs/<date-feature>/service-plans/<service>/implementation-plan.md`
- `docs/agent-runs/<date-feature>/evidence/cross-service-dependencies.json`
- Knowledge graph summary
- The service's `AGENT.md`
- `memory/service-boundaries.md`, `memory/graph-findings.md`, `memory/decisions.md`

Outputs:

- Minimal production code through Red-Green-Refactor
- Updated tests
- `docs/agent-runs/<date-feature>/service-plans/<service>/code-agent.md`
- `docs/agent-runs/<date-feature>/service-plans/<service>/implementation-manifest.md`
- `docs/agent-runs/<date-feature>/service-plans/<service>/unit-test-evidence.txt`
- `docs/agent-runs/<date-feature>/service-plans/<service>/coverage-matrix.md`
- `docs/agent-runs/<date-feature>/service-plans/<service>/business-review.md`

Gate:

- Refactor only while green. Edit only the assigned service/module plus shared files explicitly listed in the service plan. Broaden Maven verification before completion.
- Write `unit-test-evidence.txt` as JSON command evidence with `command`, integer `exit_code`, `stdout_tail`, and `stderr_tail`. Narrative PASS text does not satisfy the completion gate.

Service implementation plans should include:

- Scope and allowed files.
- Modification points table.
- Implementation manifest rows for every required artifact in the service/module.
- Service-local TDD plan with Maven command.
- Cross-service contracts and compatibility rules.
- Data/transaction effects.
- Risks, rollback, and completion evidence.

### R3 Implementation Reviewer

Inputs:

- Production diff or listed code refs
- Tests, green command evidence, implementation manifest, service plans, dependency report
- Existing same-domain implementation patterns selected with GitNexus, Graphify, `rg`, or memory

Outputs:

- `docs/agent-runs/<date-feature>/review-requests/R3-implementation-review-request.md`
- `docs/agent-runs/<date-feature>/reviews/R3-implementation-review.md`
- Service-local R3 review requests under `service-plans/<service>/review-requests/`
- Service-local R3 reviews under `service-plans/<service>/reviews/`
- Rework items for missing code, missing tests, security flaws, anti-patterns, or project-pattern drift

Gate:

- Completion waits for R3 review in the formal workflow. Findings create rework items; the implementation reviewer does not become a second code developer.
- R3 cannot be authored by the same agent that wrote the code or service implementation handoff.

### Coverage Reviewer

Inputs:

- Requirements, use cases, test plan, service implementation plans
- Service-scoped code agent handoffs and unit-test evidence
- GitNexus-first cross-service dependency report
- Final diff or code refs

Outputs:

- `docs/agent-runs/<date-feature>/evidence/implementation-manifest.md`
- `docs/agent-runs/<date-feature>/evidence/coverage-matrix.md`
- `docs/agent-runs/<date-feature>/evidence/business-review.md`
- `docs/agent-runs/<date-feature>/evidence/verification.txt`
- `docs/agent-runs/<date-feature>/rework/rework-NNN.md` or `docs/agent-runs/<date-feature>/service-plans/<service>/rework-NNN.md` when missed behavior is found

Gate:

- Merge service-local implementation manifests into the global manifest. Required rows must name the source (`explicit-requirement`, `reference-pattern`, `dependency-report`, or `service-plan`), artifact path, tests, status, and evidence.
- Confirm every module/service listed in the design appears in the implementation manifest. Missing modules become `missing-code` rework.
- Confirm design-named artifacts such as response objects, config services, listeners, clients, DTOs, or utility classes appear in the manifest and exist in the repo.
- Every acceptance criterion extracted from the design document maps to a use case, service plan, tests, code refs, and business review evidence before completion.
- Confirm the global `green-test.txt` or service `unit-test-evidence.txt` files contain structured command JSON with `exit_code: 0`.
- Confirm cross-service designs have `cross-service-dependencies.json` and that it has no unresolved URL/topic/tag/service mapping questions.
- Confirm Spring static check is clean or an explicit `--skip-spring-static-check` exception is justified.
- Confirm semantic review artifacts are approved and machine-checkably independent for every completion run.
- If any requirement, test, code, contract, or business-logic gap is found, create a rework item instead of telling the code agent to patch directly. Completion remains blocked until each item is `verified` or explicitly approved as `deferred`.

## Rework Protocol

Rework items are the controlled loop from completion review back into the workflow.

Use `docs/agent-runs/<date-feature>/rework/rework-NNN.md` for global gaps and `docs/agent-runs/<date-feature>/service-plans/<service>/rework-NNN.md` for service-local gaps. Each item must include `Source`, `Related AC`, `Affected Services`, `Problem Type`, `Return Phase`, `Required Red Test`, `Evidence`, `Exit Criteria`, and `Status`.

Route by problem type:

| Problem Type | Return Phase |
| --- | --- |
| `unclear-requirement`, `missing-acceptance` | `clarify` |
| `missing-use-case`, `business-logic-risk` | `use-case-design` |
| `missing-test` | `test-case-design` |
| `missing-code`, `test-failure` | `tdd-implement` |
| `multi-service-contract` | `plan` |

The receiving agent must load only the relevant design, handoff, service plan, AGENT files, graph status, memory, and rework item. For `tdd-implement`, the first action is to add or update the required red test and observe it failing for the expected reason.

## Handoff Rules

- Treat handoff files as the source of truth, not chat memory.
- Put agent process artifacts under `docs/agent-runs/<date-feature>/`.
- Keep `docs/design/` for durable design documents and reusable templates.
- Keep multi-service implementation details under `docs/agent-runs/<date-feature>/service-plans/<service>/`.
- Keep global semantic reviews under `docs/agent-runs/<date-feature>/reviews/`; keep service-local semantic reviews under `service-plans/<service>/reviews/`.
- Keep review requests under `docs/agent-runs/<date-feature>/review-requests/` and `service-plans/<service>/review-requests/`. A review report must be the exact `Output` declared by its request.
- Do not pre-fill review reports during archive creation. Create review request files first, assign concrete Developer Agent and Reviewer Agent ids, then let the independent reviewer write the report with `Reviewer Session`, `Reviewer Invocation`, and `Request Hash`.
- Keep service-local rework next to that service plan as `rework-NNN.md`; do not merge similar service rework into one shared code-agent context.
- Keep service-local implementation manifest rows next to each service plan, then merge them into `evidence/implementation-manifest.md` for the completion gate.
- Keep each handoff artifact focused and under roughly 300 lines unless the task truly requires more.
- Include `Open Questions: None` explicitly before the next phase proceeds.
- Name assumptions and mark whether they are approved, inferred, or still pending.
- Record knowledge graph refresh location and timestamp in the requirements or use-case artifact.
- Record the dependency report path and any GitNexus evidence used for HTTP/DMQ impact reasoning.
- Record proposed memory updates in the phase handoff artifact first. Append them to `memory/*.md` only after verification or user approval.

## Parallelism

Parallel work is useful only after requirements are stable:

- The Use Case Designer and Test Case Developer may overlap only when acceptance criteria are stable.
- Code Developer starts after the first red test is observed.
- For multiple services, split Code Developer work by service or module with disjoint file ownership.
- Service-scoped Code Developers may run in parallel only after requirements, cross-service flows, contracts, and service plans are stable.
- R1 review runs after clarification and before planning. R2 review runs after red tests and before green implementation. R3 review runs after green/refactor and before coverage review. Each one runs in an independent reviewer agent/session with no inherited developer chat context.
- Coverage Reviewer runs after semantic reviewers and service-scoped developers finish; it blocks completion if any acceptance criterion lacks tests, code refs, business review, approved semantic review, or closed rework.

## Recommended Invocation Pattern

1. Run `superpowers_probe.py --mode auto` during repository discovery; switch to `--mode strict` only when the project has committed to making Superpowers a hard gate.
2. Run `kg_refresh.py . --mode auto`.
3. Run `memory_capture.py scan .`.
4. Run `orchestration_plan.py . --mode auto --service-scope discovery --design-doc <doc>` to get service candidates and next steps only.
5. After affected services are clear, run `orchestration_plan.py . --mode auto --design-doc <doc>`; if the design names affected modules, auto mode selects them. Use `--service-scope affected --service services/<service>` only when you need to override or disambiguate.
6. Create an archive with `e2e_dev_workflow.py plan . --design-doc <doc> --create-archive`; verify the archive contains one `service-plans/<service>/code-agent.md` per affected service/module.
7. In `multi` mode, update the handoff artifacts under `docs/agent-runs/<date-feature>/handoffs/` and the service plans under `docs/agent-runs/<date-feature>/service-plans/<service>/`.
8. Run R1/R2/R3 semantic reviews at the phase boundaries and convert findings into rework items.
9. Gate each phase with review before passing work forward.
10. Run `e2e_dev_workflow.py gate . --phase completion ... --review-dir docs/agent-runs/<run>/reviews` before reporting done; include service-local `--review-dir` values, `--implementation-manifest`, and `--rework-dir` when the run uses non-standard locations.
