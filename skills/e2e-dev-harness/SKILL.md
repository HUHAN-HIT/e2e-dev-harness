---
name: e2e-dev-harness
description: Use when a feature, bugfix, refactor, or design-doc task needs strict requirements, TDD, service isolation, knowledge graph evidence, memory capture, and completion verification across single-service or multi-service repositories.
---

# E2E Dev Harness

Turn requests/design docs into clarified, tested code changes.

Do not implement while behavior, APIs, data effects, contracts, or tests are ambiguous.

## Platform Compatibility

This skill is agent-neutral for Codex, Claude Code, Gemini CLI, OpenCode, and runtimes that can read `SKILL.md` plus bundled scripts. `references/platform-compatibility.md`.

## Fast Path

Start every non-trivial run before dependency analysis or implementation so `.phase-lock` can block production-code writes until the implementation gate passes:

```bash
e2e-harness start . \
  --feature "<feature>" \
  --request "<original user request>"
```

Call `next` and do only the returned phase:

```bash
e2e-harness next . \
  --state docs/agent-runs/<run>/run-state.json \
  --runtime <codex|claude-code|opencode|manual>
```

CLI stdout is compact. Read `full_result_path` or
`coordinator_summary_path`; use `--json-full` only for debugging or legacy automation.
Coordinator minimal reading set: instructions, `next`, active design/slice, paths, blockers; keep full CLI JSON in evidence files.
Coordinator write budget: long design/plan/handoff bodies must be worker evidence or generator outputs; keep only paths in chat.

Use `next.required_todo_list`; the coordinator stays control-plane only.
In `CREATED`, dispatch `requirements-clarifier` and relay only returned Restated Intent/Open Questions and evidence paths.
Workers use GitNexus-first evidence; the coordinator never does local code exploration, design writing, TDD, review, or implementation.

## Hard Rules

Load each `references/*.md` only when its rule's phase begins, never all at start.

- Load project instructions before clarification: discovery scope first, then affected service `AGENT.md`/`AGENTS.md` once scope is known (`references/agent-instructions.md`).
- Use Superpowers when available: `brainstorming` for clarification, `test-driven-development` for TDD (`references/superpowers-integration.md`).
- Clarification gate requires goals, non-goals, affected services, use cases, change logic, impact summary, contracts, ACs, test design, and closed questions.
  CLI: `clarify`, not `gate --phase clarification` (`references/clarification-gate.md`).
  In `CREATED`, TodoList must dispatch `requirements-clarifier`, then relay returned Restated Intent/Open Questions before plan/TDD/code.
  Interactive `clarify` requires `Restated Intent` and user confirmation provenance; do not self-answer open questions.
  MQ/DMQ/Kafka requirements must name the cross-layer call chain and sender/producer injection point before implementation.
- Prefer GitNexus for code-level cross-service evidence and explicit impact artifacts.
  Do not duplicate low-level `grep`/`rg` instructions just because GitNexus augments searches.
  Use explicit GitNexus commands for auditable gate evidence; failures block unless the user approves documented degradation.
  Put raw impact output in evidence files; keep only a bounded affected-interface summary in agent context.
  Use Graphify for docs, ADRs, diagrams, and semantic context. Scanner facts seed both. `references/kg-tool-selection.md`.
- Memory is optional context, not authority. Capture only verified or user-approved facts; Obsidian tags and links help selection but never replace explicit text. `references/memory-integration.md`.
- TDD is mandatory for production changes; enforcement depth is scenario-based.
  Use the default `--tdd-mode auto`; it resolves to strict red/green command evidence for critical/audited work.
  Test/code workers write red tests, observe expected failures, implement minimally, then broaden Maven verification. `references/tdd-java-spring.md`.
- Large repositories use planned incremental verification, not ad hoc test selection.
  Generate `evidence/test-impact-plan.json` from changed files and dependency evidence; completion must prove every required command passed in unit-test JSON.
  Root/shared build or source changes expand to full `mvn test`.
- Multi-service designs use one global design anchor plus service-local design slices.
  Global design includes `System Sequence`; each `service-designs/<service>.md` includes mapped ACs, edit scope, runtime path, local sequence, TDD plan, dependency boundary, and test impact.
  Local sequence is required for cross-service, contract, shared-state, or event dependencies.
  Multi-service `plan --create-archive` enters `SERVICE_DESIGN_REQUIRED`; dispatch service-design workers and validate returned slices before R2/TDD red or service code-agent dispatch.
- Design, test, code, review, and coverage are separate role groups.
  `agent-schedule.json` assigns different agents, references generated `agent-roles/*.md`, and downstream agents consume ready handoffs instead of chat memory.
- Review profiles are portable project policy. Auto-discover project profiles and extend bundled profiles only when useful.
  Use common issue guidance for reviewer focus. `references/review-profiles.md` and `references/common-review-issues.md`.
- R1/R2/R3 are independent-agent reviews, not same-chat roleplay.
  Reviewer Invocation JSON must prove runtime/session isolation; same agent or same session blocks.
- Archive the final requirement summary so future analysis avoids replaying every run artifact. `references/requirements-archive.md`.
- Completion requires task-completion proof, not chat claims: every AC has concrete code refs and concrete test refs.
  Semantic reviews, implementation manifest, coverage matrix, unit-test JSON, business review, dependency report when cross-service,
  task-alignment evidence, closed rework, and passing guard are completion evidence.
- The implementation completion unit is all assigned ACs, not the first passing AC.
  After any AC turns green, apply `ac-progress` to worker evidence; if ACs remain, continue code-developer dispatch without asking whether to proceed or start R3.
  R3 review is allowed only after `e2e_dev_harness.py ac-progress` is ready for the current service slice or global design.
- Skipped phases are blockers in strict completion. R1/R2/R3 reviews, harness plan state, TDD red/green, completion gate, and strict guard must have machine-readable evidence; do not mark them as skipped in the final report.
- Task drift is a blocker. Changed production files must stay inside declared design/manifest/coverage scope.
  If a change is outside scope, adds undeclared ACs, or changes interface-like files without Impact Summary rows, return to `plan` or `clarify`.
- Every run has `run-state.json` and `artifact-registry.json`; never edit harness control files directly.
  Valid high-phase states need transition history and gate evidence.
- Do not run `prepare` as a substitute for `start`. `prepare` is dependency discovery only; `start` creates the active run, design template, and phase lock.
- Runtime hooks can enforce phase locks before code-writing tools run.
  Bootstrap order: `start` -> `e2e-harness init . --runtime <runtime>` -> `next` -> `dispatch-beat`; dispatch blocks with install guidance when hooks are not ready.
  Claude Code hooks need `Read/Grep/Glob/Bash` plus `Stop`; OpenCode installs `.opencode/plugins/e2e-dev-harness.js`.
  If hooks are unavailable, run `e2e_dev_harness.py pre-code --path <planned-code-file> --run-dir docs/agent-runs/<run>` before each code edit.
  `references/execution-control.md`.
  After red-test evidence exists, run `e2e_dev_harness.py gate --phase implementation --run-state docs/agent-runs/<run>/run-state.json`;
  a passing gate opens the `IMPLEMENTED` phase automatically.
- Replay with `harness_verify.py` or `verify --harness`; emit summaries for CI, reviewers, evaluation, and later analysis.
- Use `execution_trace.py`, `command_evidence.py`, and `context_pack.py` for decision traces, command proof, and bounded worker inputs.
  Use `agent-task --action claim` before any multi-service code agent writes code; phase guard blocks unclaimed service writes and cross-service edits by a single claimed task.
  Claims carry leases; renew long tasks, and reclaim stale ones before completion.
  Use `checkpoint_gate.py` or `gate --checkpoint-mode required` after clarify, R1, and TDD Red on critical or interactive work.
  Use `dispatch-beat`/`dispatch-ack`/`dispatch-complete` for runtime handoffs.
  `dispatch-next` is single-worker compatibility for `dispatch-beat --max-workers 1`.
  The coordinator flow is `dispatch-beat` -> spawn returned workers -> hook/`dispatch-ack` -> `dispatch-complete` -> `dispatch-beat` again.
  Spawn requests target Claude Code `Task` or Codex `multi_agent_v1.spawn_agent`; call that tool,
  let the Task hook confirm or record the worker id with `dispatch-ack`, then accept `dispatch-complete`.
  The coordinator must not do dispatched work locally or paste full worker context into chat; keep only task id, context-pack path, invocation path, worker handle, and final evidence paths.

## Workflow

1. Prepare: load root instructions, scan memory, probe Superpowers, refresh GitNexus-first dependency evidence.
2. Clarify: dispatch `requirements-clarifier`; relay Restated Intent/Open Questions and record evidence paths.
3. R1 design review: dispatch an independent semantic reviewer.
4. Plan: choose `single`, `single-review`, or `multi`; dispatch `implementation-planner` after R1 evidence is ready.
5. Service design split: dispatch workers for `service-designs/<service>.md`, then validate; block while `SERVICE_DESIGN_REQUIRED`.
6. TDD red: dispatch test workers to write the first failing service-local test and capture evidence.
7. R2 test review: dispatch an independent reviewer before production code.
8. Dispatch/claim service code tasks: each service code agent claims its `agent-schedule.json` task before writing code; one claimed task edits only its service/module.
9. TDD green/refactor: dispatch code-developer workers for every assigned AC; run required test-impact commands before broader verification.
10. AC progress gate: prove all assigned ACs for the service slice or global design have coverage rows, implementation manifest rows, and passing green/unit command evidence. Do not ask to start R3 while ACs remain.
11. R3 implementation review: independent reviewer traces every AC through the concrete code path.
   Then check completeness, tests, security, anti-patterns, and project-pattern consistency. The bundled default review profile is enforced unless an explicit project profile overrides it.
12. Completion gate: prove every acceptance criterion and required artifact has use cases, service ownership, concrete tests, concrete code refs, business review, task alignment, completed service tasks, and closed rework.
13. Rework loop: findings create rework items and return to the earliest required phase before more production-code edits.
14. Strict guard/report: run `verify --strict-workflow` or `guard`, capture accepted memory updates, and report evidence plus residual risks.
15. Trace/archive: attach `execution-trace.json` and summaries when reporting or evaluating the run.

## Agent Orchestration

Default to `single` only for small low-risk single-service work.
Use explicit `single-review` only for single-service medium work with separated design/test/code agents plus formal reviewer invocations.
Use `multi` for cross-service, contract/data-risk, design-heavy, or user-requested context isolation.

Large `multi` schedules are normal: `expected_handoffs` predicts sessions; never downgrade to manual coding.

```bash
e2e-harness exec orchestration_plan.py . \
  --mode auto \
  --service-scope discovery \
  --design-doc docs/design/<feature>.md
```

Important boundaries:

- `auto` recommends `single`, `single-review`, or `multi`; risk/large single-service work becomes `single-review`.
- `single` and `single-review` escalate to `multi` if multiple affected services/modules, contract/data-risk, or design-heavy evidence is detected; do not keep serial same-agent coding for multi-service work.
- Discovery scope lists service candidates but does not create service plans.
- Affected scope creates service plans only from explicit `--service` / `--path`, dependency evidence, or design-declared affected services/modules.
- Multi-service work keeps each service plan and code-agent handoff under `docs/agent-runs/<run>/service-plans/<service>/`.
- Service code agents consume `service-designs/<service>.md`, service implementation plan, and service-local test impact plan; do not reload the full global design unless the slice is incomplete.
- Before dispatching, create `context-packs/<task>.json` from `agent-schedule.json`; never pass inherited developer chat as worker context.
- `dispatch-beat --max-workers N` dispatches a ready wave across distinct `parallel_group` values by default; rerun after worker completion events.
- Returned spawn requests target Claude Code `Task` or Codex `multi_agent_v1.spawn_agent`; invoke them with fresh worker context, then confirm with the Task hook or `dispatch-ack` before `dispatch-complete`.
- `dispatch-next` remains the single-worker compatibility wrapper when a runtime cannot consume a beat wave yet.
- Before a service code agent writes code, claim its task with `e2e_dev_harness.py agent-task --action claim --schedule docs/agent-runs/<run>/agent-schedule.json --task-id <id> --agent <agent> --state docs/agent-runs/<run>/run-state.json`.
- Generated schedules use `completion_mode: dispatcher-confirmed`.
  Complete scheduled role tasks through `dispatch-complete` after `dispatch-ack`.
  Use `agent-task --action complete --allow-local-completion` only for explicit
  legacy/manual recovery with an audit warning.
- The orchestration result records `multi_agent_decision` with criteria, evidence, and required artifacts.
- R1/R2/R3 reviews must be independent agents or separate reviewer sessions; one consolidated after-the-fact review is invalid.
- Coverage Reviewer always runs before completion.
- Service-local R2/R3 reviews are required for every generated service plan.
- Handoffs are file boundaries with ready markers and hashes; do not rely on chat memory.
- For multi-service, contract/data-risk, or split-agent work, completion must pass `--require-handoffs` so empty `handoffs/` cannot masquerade as a completed archive.

For role contracts, handoff schema, atomic handoff, and reviewer invocation details, read `references/agent-orchestration.md` and `references/agent-handoff-schema.md`.

## Cross-Service Dependencies

Run dependency discovery before implementation planning.
The deterministic scanner extracts HTTP/MQ seeds and GitNexus remains authoritative; Graphify enriches docs/architecture semantics only.
Unavailable required evidence needs user-approved degradation.
Record `Approval: user-approved`, `Reason:`, and `Fallback Evidence:` and pass the file with `--gitnexus-degradation`.

For changed requirements or code diffs, use GitNexus impact tooling explicitly:

When multiple repositories are indexed, GitNexus CLI symbol and diff commands must target the current project root with `--repo <repo-root>`; prefer an absolute path.

```bash
gitnexus detect-changes --repo <repo-root> --scope unstaged
gitnexus detect-changes --repo <repo-root> --scope staged
gitnexus detect-changes --repo <repo-root> --scope compare --base-ref main
gitnexus context "<ClassName|methodName|ClassName.methodName>" --repo <repo-root>
gitnexus impact "<changed-symbol-or-file>" --repo <repo-root> --include-tests
```

`context` is a 360-degree symbol view; do not pass service directories to it.
For affected-scope analysis use `impact` or `detect-changes`, seeded by changed symbols/files and limited to the services named in the design/service slices.
Do not require agents to call GitNexus for every `grep`/`rg` command when local GitNexus search augmentation is already installed. Treat that as exploration help, not completion evidence.

When service A depends on service B through HTTP or DMQ, freeze the shared contract before parallel implementation.
Use `docs/agent-runs/<run>/contracts/<contract-id>.md`.
Missing producer/consumer ACKs, contract tests, or DMQ topic/tag/group details block the workflow.

## Gates And Rework

Use `e2e_dev_harness.py gate` at planning, implementation, and completion phases. 
Use `verify --strict-workflow` plus `guard` when scripts must be enforceable in pre-push or CI.

Gate details live in `references/implementation-gates.md`, including:

- run-state and artifact registry validation
- phase-lock execution control
- harness policy and replay verification
- run summary reporting
- required review/request/invocation fields
- review profiles, project discovery, inheritance, and required checklist coverage
- completion manifest and coverage matrix rules
- final requirements archive rules
- unit-test evidence JSON format
- dependency report and contract requirements
- required handoffs for multi-service/split-agent runs
- Spring static checks
- strict guard skip approvals
- rework item schema and return-phase routing

If a reviewer, test, business review, completion gate, or user review finds missed behavior, create a rework item. Only `Status: verified` or `Status: deferred` with explicit `Approval: user-approved` can pass completion.

## Memory And Reporting

Memory is context, not authority. Code/tests and fresh graph win.

Context packs automatically inject relevant memory:

```bash
e2e-harness exec memory_capture.py select . \
  --phase code \
  --service services/<service> \
  --format context-pack
```

At completion, registry `proposed_memory_updates` are validated automatically. Promote accepted, approved, or verified entries only after validation; promotion refreshes `memory/index/*.json`.

Final reports name instructions, evidence, memory, and risks.
