---
name: e2e-dev-harness
description: Use when a feature, bugfix, refactor, or design-doc task needs strict requirements, TDD, service isolation, knowledge graph evidence, memory capture, and completion verification across single-service or multi-service repositories.
---

# E2E Dev Harness

Use this skill to turn a request or design document into a clarified, tested, verified code change.
It is tuned for Java 21, Spring Framework 6.x, and Maven, but the workflow name is intentionally stack-neutral.

Governing rule: do not start implementation while behavior, use cases, APIs, data effects, service contracts, or test expectations are ambiguous.

## Platform Compatibility

This skill is agent-neutral. Use it from Codex, Claude Code, Gemini CLI, OpenCode,
or any agent runtime that can read a `SKILL.md` plus bundled scripts.
For runtime-specific invocation, install paths, and fallback behavior, read `references/platform-compatibility.md`.

## Fast Path

Start every non-trivial run by creating a controlled harness run. This must
happen before dependency analysis or implementation so `.phase-lock` can block
production-code writes until the implementation gate passes:

```bash
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py start . \
  --feature "<feature>" \
  --request "<original user request>"
```

Then call `next` and do only the returned phase:

```bash
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py next . \
  --state docs/agent-runs/<run>/run-state.json
```

Fill the generated design doc, then run `clarify` before planning or coding.
After clarification identifies affected services or paths, rerun prepare or plan with `--service-scope affected` plus explicit `--service` or `--path` when names are ambiguous.
Workflow tiers are `basic`, `standard`, `critical`, and `audited`; all preserve auditable evidence, test proof, and replayable run records.
Tiers decide evidence depth and orchestration strength, not whether the run is rigorous.

Use focused subcommands only when needed:

- `clarify`: machine-check a Markdown design note.
- `plan`: choose agent mode and optionally create an agent-run archive.
- `gate`: enforce planning, implementation, or completion phase requirements.
- `verify`: run prepare, clarification, optional gate, and optional Maven.
- `guard`: hook/CI guard over a saved strict `verify` result.

For command details, read `references/implementation-gates.md`.

## Hard Rules

- Load project instructions before requirement clarification. Use discovery scope first; load affected service `AGENT.md` / `AGENTS.md` only after scope is known. Read `references/agent-instructions.md`.
- Use Superpowers when available. `superpowers:brainstorming` owns clarification; `superpowers:test-driven-development` owns TDD. Read `references/superpowers-integration.md`.
- Clarification is a hard gate. The design must state goals, non-goals, affected services/modules, use cases,
  change logic, bounded impact summary, contracts, acceptance criteria, test design, and resolved open questions.
  Read `references/clarification-gate.md`.
  For high-risk or interactive runs, require `Restated Intent` with `--require-intent` so the agent's understanding is confirmed before planning.
  MQ/DMQ/Kafka requirements must name the cross-layer call chain and sender/producer injection point before implementation.
- Prefer GitNexus for code-level cross-service evidence and explicit impact artifacts.
  Do not duplicate low-level `grep`/`rg` usage instructions just because GitNexus augments searches.
  Use explicit GitNexus commands when a gate needs auditable evidence.
  Put raw impact output in evidence files; keep only a bounded affected-interface summary in agent context.
  Use Graphify for docs, ADRs, diagrams, and semantic context. Scanner facts seed both. Read `references/kg-tool-selection.md`.
- Memory is optional context, not authority. Capture only verified or user-approved facts; Obsidian tags and links help selection but never replace explicit text. Read `references/memory-integration.md`.
- TDD is mandatory for production changes, but enforcement depth is scenario-based.
  Use the default `--tdd-mode auto`; it resolves to strict red/green command evidence for critical/audited work.
  Write a red test, observe the expected failure, implement minimally, then broaden Maven verification. Read `references/tdd-java-spring.md`.
- Review profiles are portable project policy. Auto-discover project profiles and extend bundled profiles only when useful.
  Use common issue guidance for reviewer focus. Read `references/review-profiles.md` and `references/common-review-issues.md`.
- Archive the final requirement summary after completion so future analysis can read outcomes without replaying every run artifact. Read `references/requirements-archive.md`.
- Completion requires task-completion proof, not chat claims: every AC has concrete code refs and concrete test refs.
  Semantic reviews, implementation manifest, coverage matrix, unit-test JSON, business review, dependency report when cross-service,
  task-alignment evidence, closed rework, and passing guard are completion evidence.
- Skipped phases are blockers in strict completion. R1/R2/R3 reviews, harness plan state, TDD red/green, completion gate, and strict guard must have machine-readable evidence; do not mark them as skipped in the final report.
- Task drift is a blocker. Changed production files must stay inside declared design/manifest/coverage scope.
  If a change is outside scope, introduces undeclared acceptance criteria, or changes interface-like production files without Impact Summary rows, return to `plan` or `clarify`; do not normalize the drift in the final report.
- Every created agent run has `run-state.json` and `artifact-registry.json`.
  Treat them as the portable harness state for Codex, Claude Code, or generic CLI agents.
- Do not run `prepare` as a substitute for `start`. `prepare` is dependency discovery only; `start` creates the active run, design template, and phase lock.
- Runtime hooks can enforce phase locks before code-writing tools run.
  Use `install_hooks.py`, `phase_guard.py`, and hook examples when the agent runtime supports pre-action checks.
  Read `references/execution-control.md`.
  After red-test evidence exists, run `e2e_dev_harness.py gate --phase implementation --run-state docs/agent-runs/<run>/run-state.json`;
  a passing gate opens the `IMPLEMENTED` phase automatically.
- Harness verification can replay a run from state and policy with `harness_verify.py` or `verify --harness`.
  Emit `run-summary.json` / `run-summary.md` for CI, reviewer agents, evaluation, and later requirement analysis.
- Use `execution_trace.py` or `verify --trace-file` to record phase timing, decisions, artifacts, and optional token counts.
  Use `command_evidence.py` for tests and graph commands when evidence must include exit code, elapsed time, output hashes, and environment metadata.
  Use `checkpoint_gate.py` or `gate --checkpoint-mode required` to pause after clarify, R1, and TDD Red on critical or interactive work.
  Agent start/stop is runtime-specific; this harness enforces portable state, hooks, gates, and rework routing instead of claiming non-portable process control.

## Workflow

1. Prepare: load root instructions, scan memory, probe Superpowers, refresh GitNexus-first dependency evidence.
2. Clarify: use Superpowers brainstorming and the Markdown clarification gate; stop on unresolved behavior/API/data/test or impact-summary questions.
3. R1 design review: independent semantic reviewer checks AC completeness, affected modules, security paths, and reference patterns.
4. Plan: choose `single`, explicit `single-review`, or `multi`; write an ExecPlan for complex work. Read `references/exec-plan.md`.
5. TDD red: write the first failing test and capture failing evidence.
6. R2 test review: independent reviewer checks happy/failure paths, security cases, and contract coverage before production code.
7. TDD green/refactor: implement with the Superpowers Red-Green-Refactor cycle.
8. R3 implementation review: independent reviewer traces every AC through the concrete code path.
   Then check completeness, tests, security, anti-patterns, and project-pattern consistency. The bundled default review profile is enforced unless an explicit project profile overrides it.
9. Completion gate: prove every acceptance criterion and required artifact has use cases, service ownership, concrete tests, concrete code refs, business review, task alignment, and closed rework.
10. Rework loop: findings create rework items and return to the earliest required phase before more production-code edits.
11. Strict guard/report: run `verify --strict-workflow` or `guard`, capture accepted memory updates, and report evidence plus residual risks.
12. Trace/archive: attach `execution-trace.json` and summaries when reporting or evaluating the run.

## Agent Orchestration

Default to `single` for small low-risk work.
Use explicit `single-review` only for single-service medium work where one developer context is acceptable but R1/R2/R3 still need independent request-scoped reviewer invocations.
Use `multi` for cross-service, contract/data-risk, design-heavy, or user-requested context isolation.

```bash
python skills/e2e-dev-harness/scripts/orchestration_plan.py . \
  --mode auto \
  --service-scope discovery \
  --design-doc docs/design/<feature>.md
```

Important boundaries:

- `auto` recommends only `single` or `multi`; `single-review` is explicit.
- `single-review` escalates to `multi` if multiple services or high-risk evidence is detected.
- Discovery scope lists service candidates but does not create service plans.
- Affected scope creates service plans only from explicit `--service` / `--path` or design-declared affected modules.
- Multi-service work keeps each service plan and code-agent handoff under `docs/agent-runs/<run>/service-plans/<service>/`.
- The orchestration result records `multi_agent_decision` with criteria, evidence, and required artifacts.
- R1/R2/R3 reviews must be independent agents or separate reviewer sessions; one consolidated after-the-fact review is invalid.
- Coverage Reviewer always runs before completion.
- Service-local R2/R3 reviews are required for every generated service plan.
- Handoffs are file boundaries with ready markers and hashes; do not rely on chat memory.
- For multi-service, contract/data-risk, or split-agent work, completion must pass `--require-handoffs` so empty `handoffs/` cannot masquerade as a completed archive.

For role contracts, handoff schema, atomic handoff, and reviewer invocation details, read `references/agent-orchestration.md` and `references/agent-handoff-schema.md`.

## Cross-Service Dependencies

Run dependency discovery before planning implementation.
The deterministic scanner extracts HTTP/DMQ seeds: routes, configured URLs, `@Value`, `Environment.getProperty`, client calls, producer/listener annotations, topic constants, tags, groups, and payload hints.

```bash
python skills/e2e-dev-harness/scripts/cross_service_dependency_scan.py . \
  --gitnexus-mode auto \
  --json
```

For Java/Spring code dependencies, GitNexus is the primary evidence engine. Graphify can enrich design-document and architecture semantics, but inferred or ambiguous Graphify findings become clarification questions, not completion evidence.

For changed requirements or code diffs, use GitNexus impact tooling explicitly:

When multiple repositories are indexed, GitNexus CLI symbol and diff commands
must target the current project root with `--repo <repo-root>`; prefer an
absolute path, or `.` only when the command is run from the project root.

```bash
gitnexus detect-changes --repo <repo-root> --scope unstaged
gitnexus detect-changes --repo <repo-root> --scope staged
gitnexus detect-changes --repo <repo-root> --scope compare --base-ref main
gitnexus context "<symbol-or-path>" --repo <repo-root>
gitnexus impact "<symbol-or-path>" --repo <repo-root> --include-tests
```

Do not require agents to call GitNexus for every `grep`/`rg` command when local GitNexus search augmentation is already installed. Treat that as exploration help, not completion evidence.

When service A depends on service B through HTTP or DMQ, freeze the shared contract before parallel implementation.
Use `docs/agent-runs/<run>/contracts/<contract-id>.md`.
Missing producer/consumer ACKs, contract tests, or DMQ topic/tag/group details block the workflow.

## Gates And Rework

Use `e2e_dev_harness.py gate` at planning, implementation, and completion phases. Use `verify --strict-workflow` plus `guard` when scripts must be enforceable in pre-push or CI.

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

Before dispatching phase-specific or service-scoped agents, select only relevant memory:

```bash
python skills/e2e-dev-harness/scripts/memory_capture.py select . \
  --phase code \
  --service services/<service>
```

At completion, process proposed memory updates from the agent run. Promote accepted, approved, or verified entries only after validation.

Final reports should name loaded AGENT files, Superpowers status, graph status, affected services, review artifacts, tests and Maven commands, coverage/rework state, memory decisions, and residual risks.
