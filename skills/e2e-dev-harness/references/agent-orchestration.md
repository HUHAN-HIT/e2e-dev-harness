# Agent Orchestration

Use this reference when a Java/Spring 6/Maven change benefits from smaller, isolated agent contexts.

## Modes

| Mode | Use when | Behavior |
| --- | --- | --- |
| `single` | Small, single-module, low-risk work | Service scope stays single, but design, test, code, semantic review, and coverage still use separate role groups and ready handoffs. |
| `single-review` | Single-service medium or high-risk work where service scope is still compact but role isolation is required | Separate agents own design, tests, code, R1/R2/R3 reviews, and coverage. Multiple affected services/modules escalate to `multi`. |
| `multi` | User asks for split agents, cross-service work, or multiple affected services/modules | Separate agents own requirements, use cases, tests, service-scoped code, semantic reviews, and coverage review. |
| `auto` | Default recommendation mode | The helper chooses `single`, `single-review`, or `multi`; risk keywords and large single-service designs become `single-review`, while multiple services/modules become `multi`. |

The orchestration result includes `multi_agent_decision`. Treat it as the audit record for why multi-agent development was or was not used. The decision checks affected service count, HTTP/DMQ/shared contracts, data/schema/config/security/payment/refund risk, design size, and explicit user requests.

Agent start/stop and scheduler APIs are runtime-specific. The portable harness control plane is phase locks, blocking hooks, handoff ready markers, state transitions, rework routing, and execution traces. Do not claim that the harness can launch or terminate agents unless the active runtime provides that integration; instead, record which runtime/session owns each role and block unsafe next actions through gates.

## L0 Serial Isolated Dispatch

Use this as the first operational layer before attempting true parallel execution. The coordinator reads `agent-schedule.json` and dispatches one ready task at a time into a fresh runtime context: a Claude Code subagent, a separate Claude session, a Codex thread/worktree session, or another runtime-isolated worker. The worker receives only its role template, context pack, declared inputs, and the current task id; it must not inherit the coordinator's full chat history.

For each task:

1. Confirm all `depends_on_phases` and input handoff ready markers are satisfied.
2. Run `e2e_dev_harness.py agent-task --action claim` with the scheduled `task_id`, `agent`, `agent-schedule.json`, and `run-state.json`.
3. Dispatch the worker in a fresh runtime context and include the claim result in its prompt.
4. Require the worker to write only scheduled outputs and to return structured evidence paths.
5. Run `e2e_dev_harness.py agent-task --action complete --evidence <scheduled-output>` before the next dependent task starts.

This L0 mode is intentionally serial. It still gives the harness the main multi-agent benefits: context isolation, role separation, explicit handoffs, leases, and machine-checkable ownership. Runtime adapters may parallelize independent `parallel_group` tasks later, but only after service designs, red-test evidence, contracts, and R2 review are stable.

## L1 Beat Cadence Dispatch

Use `dispatch-beat` when the runtime can spawn multiple independent workers. A
beat is one coordinator scheduling cycle: consume prior completion events, find
ready scheduled tasks, claim a safe wave, emit runtime spawn requests, then stop
until workers ack/complete. `dispatch-next` stays as the compatibility wrapper
for `dispatch-beat --max-workers 1`.

```bash
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-beat . \
  --schedule docs/agent-runs/<run>/agent-schedule.json \
  --state docs/agent-runs/<run>/run-state.json \
  --runtime codex \
  --max-workers 4
```

The beat output includes `runtime_spawn_requests`, `claimed_tasks`,
`blocked_tasks`, `dispatches`, and `next_beat_hint`. The coordinator invokes the
returned runtime tools, records worker handles through the Task hook or
`dispatch-ack`, and each worker finishes with `dispatch-complete`. Completion
writes `dispatch-events/<task-id>-completed.json`; the next beat can use those
events plus the updated schedule to unlock successors.

## Coordinator Context Budget

Coordinator CLI output is intentionally bounded. `next`, `gate`, and
`dispatch-*` default to a short summary and write full JSON under
`evidence/cli-responses/`; use `--full-json` only when diagnosing a failed gate
or dispatcher invariant. Spawn requests and worker prompts are persisted as
files, so the coordinator should keep paths plus worker handles in chat rather
than pasting prompts, context packs, or full dispatch packets.

Treat `WAITING_DISPATCH`, a completed dispatch wave, and each worker completion
wave as a coordinator context handoff point. Run `next` to refresh
`session-checkpoint.json`, then a fresh coordinator session can resume from
`run-state.json`, the checkpoint, dispatch event files, and scheduled evidence
without replaying prior chat.

`session-checkpoint.json` also carries a soft coordinator budget. The harness
cannot see the real LLM context window, so it records proxy metrics instead:
bytes under `evidence/`, phase/dispatch event count, and CLI response artifact
count as a tool-call proxy. If `coordinator_context_budget.handoff_recommended`
is true, do not keep reading more evidence in the same chat; checkpoint and
resume from the compact run-state plus paths.

Coordinator write actions are budgeted too. Runtime hooks extract inline
Write/Edit/MultiEdit/patch payloads for coordinator-owned design, plan, and
handoff artifacts. Medium bodies produce a `Coordinator write budget warning`;
oversized inline bodies are blocked with `coordinator_write_budget` guidance.
Long detail belongs in a dispatched worker's scheduled evidence file, or in a
checked-in generator/harness command that writes the artifact without echoing
the full body through coordinator chat.

By default, one beat dispatches only distinct `parallel_group` values. This keeps
same-service or same-scope code work serialized while still allowing unrelated
services, role handoffs, or review tasks to run concurrently when their gates and
handoffs are ready.

The Claude Code/Superpowers adapter is exposed through the unified CLI:

```bash
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py runtime-capabilities . --runtime claude-code
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-next . \
  --schedule docs/agent-runs/<run>/agent-schedule.json \
  --state docs/agent-runs/<run>/run-state.json \
  --runtime claude-code
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-complete . \
  --schedule docs/agent-runs/<run>/agent-schedule.json \
  --state docs/agent-runs/<run>/run-state.json \
  --task-id <task-id> \
  --agent <agent> \
  --evidence <scheduled-output>
```

`dispatch-next` scans for the first ready task and reports skipped tasks with
their blockers. It validates handoff readiness, dependencies, role template, and
context-pack budget before claiming; a blocked context pack must not leave a task
claim behind. It then writes `context-packs/<task-id>.json`, claims the scheduled
task, writes an invocation record, and returns a `runtime_spawn_request`. For
Claude Code this request is a fresh `Task`; for Codex it is
`multi_agent_v1.spawn_agent` with `fork_context=false`. The dispatch remains
`awaiting_runtime_spawn` until the Task hook confirms the generated Task prompt
or `dispatch-ack` records a concrete worker handle. `dispatch-complete` rejects
unconfirmed tasks, so the coordinator cannot mark locally executed work as a
dispatched worker result.

Implementation Task hooks require the generated Task ID and context pack after
the implementation gate, so a coordinator cannot bypass the scheduler with a
free-form "implement this service" Task.

When a runtime cannot spawn an independent worker, dispatch enters
`WAITING_DISPATCH` and records `dispatch.status=waiting_dispatch`. This is a
pause state, not a completion state: Stop hooks may allow the coordinator to end
so a fresh session can be started, but `dispatch-ack` must record the fresh worker
before `dispatch-complete`. Completion/guard commands still require closed
scheduled tasks, independent semantic reviews, ready handoffs, and evidence.

Do not let an implementation agent review its own work. If the runtime cannot spawn subagents, use a separate reviewer session with only the review request and allowed artifact inputs. Same-chat/self-review is not an acceptable fallback for R1/R2/R3.

When a review worker reports evidence, complete it through `dispatch-complete`, not
raw `agent-task complete`; the dispatcher reruns the reviewer gate and keeps the
task open when independence, request hash, required fields, or no-code-change
checks fail.

Do not use `single-review` to collapse design, test, code, or the three reviews into one after-the-fact report. It only keeps implementation service scope compact; role timing, handoffs, reviewer independence, request hashes, invocation JSON, and Coverage Reviewer remain unchanged.

For `multi`, `single-review`, and any contract/data-risk run, empty `handoffs/` or missing service artifacts is not a valid completed archive. Populate role/service handoffs with ready markers before downstream claim or completion.

## Service Scope

`kg_refresh.detect()` reports all service candidates. Treat that list as discovery data, not as the implementation list.

- `--service-scope discovery`: pre-clarification/default when affected services are unknown. Return only a lean service inventory and next steps; do not generate agent plans, handoff artifacts, or per-service plans from all candidates.
- `--service-scope affected`: post-clarification mode. Generate service plans only for `--service` / `--path` matches or for design-declared affected services/modules that match discovered candidates.
- `--service-scope all`: explicit whole-repo mode. Use only when every service is genuinely in scope.

This mirrors AGENT loading: first discover services, then narrow the implementation plan after requirements and use cases identify affected services.
If `--service` does not match a discovered service path or service directory name, the helper blocks instead of silently planning no service work.

When `--service-scope auto` and no explicit service/path is supplied, the helper first uses verified dependency-report services. If none exist, it reads `Scope`, `Affected services/modules`, `Affected modules`, or equivalent Chinese headings from the design document and matches bullet items against discovered candidates. This includes root Maven modules such as `jeepay-core`, `jeepay-service`, and `jeepay-payment`, not only `services/*` directories. A matching design must generate one service plan, one code-agent handoff, and one service-local implementation manifest per affected module.

Every generated `service-plans/<service>/implementation-plan.md` must include agent assignment, allowed change scope, modification points, service-local change logic, TDD plan, contracts, data/transaction effects, risks, and completion evidence. The code agent owns that plan; reviewer agents validate it independently.

`start` writes a bootstrap `agent-schedule.json` with a `requirements-clarifier`
task so clarification can run in a subagent before the full archive exists.
`plan --create-archive` replaces that with the full compact task board for agent
dispatch: each task has an agent id, phase, service scope, dependency phases,
input artifacts, output artifacts, and parallel group. Agents update task status
through dispatcher commands instead of exchanging long free-form chat transcripts.
Generated tasks also declare `requires_runtime_dispatch: true`,
`dispatch_contract: fresh-subagent`, and `runtime_subagent_type:
general-purpose`; the coordinator may write archive scaffolding, but it must not
treat R1/R2/R3 review or implementation planning as completed until the
corresponding dispatched task writes its scheduled evidence.
It also writes short role templates under `agent-roles/`; generated schedules set `require_role_templates: true`, so claim is blocked if the referenced template is missing or malformed.

For multi-service work, `plan --create-archive` leaves run-state at `SERVICE_DESIGN_REQUIRED`. Fill and validate every service design slice with `service-design --run-state` before service code dispatch. Service-scoped code-developer tasks in different `service:<name>` parallel groups may run concurrently only after shared contracts, service designs, the implementation-planner task, service-local TDD plans, and R2 review are stable.

Before writing code, a service code agent must claim its task:

```bash
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py agent-task . \
  --schedule docs/agent-runs/<run>/agent-schedule.json \
  --action claim \
  --task-id <task-id> \
  --agent <agent-name> \
  --state docs/agent-runs/<run>/run-state.json
```

The claim writes service ownership into run-state and `.phase-lock`, allowing `phase_guard.py` to block unclaimed service writes and one-task multi-service edits. Completion requires each service implementation task to be marked `completed` with evidence.

### Claim leases and recovery

A claim records `claimed_at`, `heartbeat_at`, and `lease_seconds` (default 1800). This is the portable substitute for cross-runtime agent liveness: the harness never starts or stops agent processes, but it can tell a live claim from an abandoned one.

- A long-running code agent should refresh its lease: `--action renew --task-id <id> --agent <name>` (owner-only; updates `heartbeat_at`).
- `validate_schedule` flags a claim whose lease has expired as `stale`: a warning by default, and a hard blocker under `--require-claims` so an abandoned claim cannot masquerade as active before code writes.
- Recovery is explicit and portable. `--action claim` by a different agent automatically takes over a stale claim (recording `previous_owner`) but is blocked while the lease is still live. `--action reclaim` forces a takeover; it requires either an expired lease or `--force`, and is rejected against a live claim without `--force`.

This keeps recovery deterministic and file-based without claiming non-portable process control over agents.

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

### Implementation Planner

Inputs:

- Approved requirements and use-case artifacts
- R1 design review output
- Impact summary and dependency report
- Project reference patterns needed to bound implementation

Outputs:

- `docs/agent-runs/<date-feature>/exec-plan.md`
- Dispatch-ready implementation assumptions, open rework routing, and task sequencing evidence

Gate:

- TDD red work depends on the `plan` phase as well as R1. `PLANNED` run-state means the archive exists and test writes are phase-lock eligible; it does not mean R1 review or planner evidence may be skipped.
- The planner runs as a fresh dispatched worker, not as coordinator inline reasoning. The coordinator may create scaffolding files, but the scheduled planner task must own the final plan evidence used by downstream workers.

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
- Design acceptance criteria and use cases, used to build a per-AC code path trace

Outputs:

- `docs/agent-runs/<date-feature>/review-requests/R3-implementation-review-request.md`
- `docs/agent-runs/<date-feature>/reviews/R3-implementation-review.md`
- Service-local R3 review requests under `service-plans/<service>/review-requests/`
- Service-local R3 reviews under `service-plans/<service>/reviews/`
- Rework items for missing code, missing tests, security flaws, anti-patterns, or project-pattern drift

Required review content:

- `## Code Path Trace`
- One line per AC: `AC-n: <entry point> -> <service/orchestration> -> <repository/client/sender> -> <response, persistence change, or emitted event>`.
- For MQ/DMQ/Kafka work, the trace must name the sender/producer injection point and the method that calls `send`/`publish`.

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
- Run task alignment with changed-file evidence when available. If changed files are outside declared scope, return to `plan` or `clarify` before allowing more production-code edits.
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
| `scope-drift`, `task-drift` | `plan` or `clarify` |
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
- When `service-plans/<service>/` exists, required R2 and R3 phases must have service-local reports under that service's `reviews/` directory. Global R2/R3 reports are still useful for cross-cutting synthesis but do not replace service-local review evidence.
- Keep service-local rework next to that service plan as `rework-NNN.md`; do not merge similar service rework into one shared code-agent context.
- Keep service-local implementation manifest rows next to each service plan, then merge them into `evidence/implementation-manifest.md` for the completion gate.
- Keep each handoff artifact focused and under roughly 300 lines unless the task truly requires more.
- Before another agent consumes a handoff, fill `agent_id`, `status`, `inputs`, `outputs`, `input_hashes`, `output_hashes`, `consumed_by`, and `open_questions: None`, then run `handoff_gate.py`. Hashes make stale or silently rewritten handoffs visible at the communication boundary. Writers must use `<handoff>.md.partial` then atomically rename to `<handoff>.md` and write `<handoff>.ready.json`; readers must reject missing ready markers and any leftover partial files.
- Keep cross-service HTTP/DMQ contracts under `docs/agent-runs/<date-feature>/contracts/<contract-id>.md`. Producer and consumer agents both ACK the frozen contract before service-scoped code agents proceed. Run `contract_gate.py`; missing ACKs, missing contract tests, incomplete endpoint/topic/tag/group data, or draft contracts block parallel service implementation.
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
- Service-scoped Code Developers may run in parallel only after requirements, cross-service flows, contracts, and service plans are stable. If service A depends on service B, freeze and ACK the shared contract first; otherwise run the producer/contract work before the consumer implementation.
- R1 review runs after clarification and before planning. R2 review runs after red tests and before green implementation. R3 review runs after green/refactor and before coverage review. Each one runs in an independent reviewer agent/session with no inherited developer chat context.
- In `single-review`, the reviewer may share a role family such as `single-reviewer-*`, but each phase still gets its own review request, output file, invocation JSON, and reviewer session.
- Coverage Reviewer runs after semantic reviewers and service-scoped developers finish; it blocks completion if any acceptance criterion lacks tests, code refs, business review, approved semantic review, or closed rework.

## Recommended Invocation Pattern

1. Run `superpowers_probe.py --mode auto` during repository discovery; switch to `--mode strict` only when the project has committed to making Superpowers a hard gate.
2. Run `e2e_dev_harness.py start`; dispatch the bootstrap `requirements-clarifier` when the runtime supports isolated Task sessions.
3. Run `kg_refresh.py . --mode auto`.
4. Run `memory_capture.py scan .`.
5. Run `orchestration_plan.py . --mode auto --service-scope discovery --design-doc <doc>` to get service candidates and next steps only.
6. After affected services are clear, run `orchestration_plan.py . --mode auto --design-doc <doc>`; if the design names affected modules, auto mode selects them. Use `--service-scope affected --service services/<service>` only when you need to override or disambiguate.
7. Let the coordinator create the archive with `e2e_dev_harness.py plan . --design-doc <doc> --create-archive`; then dispatch scheduled use-case, test, review, service-code, and coverage workers from that archive. Verify it contains one `service-plans/<service>/code-agent.md` per affected service/module.
8. In `multi` mode, update the handoff artifacts under `docs/agent-runs/<date-feature>/handoffs/` and the service plans under `docs/agent-runs/<date-feature>/service-plans/<service>/`.
9. Run R1/R2/R3 semantic reviews at the phase boundaries and convert findings into rework items.
10. Gate each phase with review before passing work forward.
11. Run `e2e_dev_harness.py gate . --phase completion ... --review-dir docs/agent-runs/<run>/reviews --handoff-dir docs/agent-runs/<run>/handoffs --require-handoffs --contract-dir docs/agent-runs/<run>/contracts` before reporting done for multi-service/split-agent work; explicit review dirs are merged with inferred service-local reviews from the same agent run. Include additional service-local `--review-dir` values, `--implementation-manifest`, and `--rework-dir` when the run uses non-standard locations.
