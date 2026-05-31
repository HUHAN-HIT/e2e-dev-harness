---
name: e2e-dev-harness
description: Use when a feature, bugfix, refactor, or design-doc task needs strict requirements, TDD, service isolation, knowledge graph evidence, memory capture, and completion verification across single-service or multi-service repositories.
---

# E2E Dev Harness

Turn a request or design doc into a clarified, tested, verified code change.
Tuned for Java 21, Spring 6.x, and Maven; stack-neutral workflow name.

Governing rule: do not implement while behavior, APIs, data effects, contracts, or tests are ambiguous.

## Platform Compatibility

This skill is agent-neutral for Codex, Claude Code, Gemini CLI, OpenCode, and runtimes that can read `SKILL.md` plus bundled scripts. Read `references/platform-compatibility.md`.

## Fast Path

Start every non-trivial run by creating a controlled harness run. This must
happen before dependency analysis or implementation so `.phase-lock` can block
production-code writes until the implementation gate passes:

```bash
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py start . \
  --feature "<feature>" \
  --request "<original user request>"
```

Call `next` and do only the returned phase:

```bash
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py next . \
  --state docs/agent-runs/<run>/run-state.json
```

Fill the generated design doc, then run `clarify` before planning or coding.
After clarification identifies affected services or paths, rerun prepare or plan with `--service-scope affected` plus explicit `--service` or `--path` when ambiguous.
Workflow tiers tune evidence depth; all keep auditable test proof and replayable run records.

Use focused subcommands as needed: `clarify`, `plan`, `gate`, `verify`, `guard`. Read `references/implementation-gates.md`.

## Hard Rules

- Load project instructions before requirement clarification. Use discovery scope first; load affected service `AGENT.md` / `AGENTS.md` only after scope is known. Read `references/agent-instructions.md`.
- Use Superpowers when available. `superpowers:brainstorming` owns clarification; `superpowers:test-driven-development` owns TDD. Read `references/superpowers-integration.md`.
- Clarification is a hard gate. The design must state goals, non-goals, affected services/modules, use cases,
  change logic, bounded impact summary, contracts, acceptance criteria, test design, and resolved open questions.
  Read `references/clarification-gate.md`.
  For high-risk or interactive runs, require `Restated Intent` with `--require-intent` so the agent's understanding is confirmed before planning.
  MQ/DMQ/Kafka requirements must name the cross-layer call chain and sender/producer injection point before implementation.
- Prefer GitNexus for code-level cross-service evidence and explicit impact artifacts.
  Do not duplicate low-level `grep`/`rg` instructions just because GitNexus augments searches.
  Use explicit GitNexus commands when a gate needs auditable evidence; failed required evidence blocks unless the user approves documented degradation.
  Put raw impact output in evidence files; keep only a bounded affected-interface summary in agent context.
  Use Graphify for docs, ADRs, diagrams, and semantic context. Scanner facts seed both. Read `references/kg-tool-selection.md`.
- Memory is optional context, not authority. Capture only verified or user-approved facts; Obsidian tags and links help selection but never replace explicit text. Read `references/memory-integration.md`.
- TDD is mandatory for production changes, but enforcement depth is scenario-based.
  Use the default `--tdd-mode auto`; it resolves to strict red/green command evidence for critical/audited work.
  Write a red test, observe the expected failure, implement minimally, then broaden Maven verification. Read `references/tdd-java-spring.md`.
- Large repositories use planned incremental verification, not ad hoc test selection.
  Generate `evidence/test-impact-plan.json` from changed files and dependency evidence; completion must prove every required command passed in unit-test JSON.
  Root/shared build or source changes expand to full `mvn test`.
- Multi-service designs use one global design anchor plus service-local design slices.
  Each affected service gets `service-designs/<service>.md` with mapped ACs, edit scope, runtime path, TDD plan, dependency boundary, and test impact.
  Multi-service `plan --create-archive` enters `SERVICE_DESIGN_REQUIRED`; validate slices with `e2e_dev_harness.py service-design --run-state <state>` before R2/TDD red or service code-agent dispatch.
- Design, test, code, review, and coverage are separate role groups.
  `agent-schedule.json` assigns different agents, references generated `agent-roles/*.md`, and downstream agents consume ready handoffs instead of chat memory.
- Review profiles are portable project policy. Auto-discover project profiles and extend bundled profiles only when useful.
  Use common issue guidance for reviewer focus. Read `references/review-profiles.md` and `references/common-review-issues.md`.
- R1/R2/R3 are independent-agent reviews, not same-chat roleplay.
  Reviewer Invocation JSON must prove runtime/session isolation; same agent or same session blocks.
- Archive the final requirement summary after completion so future analysis can read outcomes without replaying every run artifact. Read `references/requirements-archive.md`.
- Completion requires task-completion proof, not chat claims: every AC has concrete code refs and concrete test refs.
  Semantic reviews, implementation manifest, coverage matrix, unit-test JSON, business review, dependency report when cross-service,
  task-alignment evidence, closed rework, and passing guard are completion evidence.
- The implementation completion unit is all assigned ACs, not the first passing AC.
  After any individual AC turns green, run or mentally apply `ac-progress`; if assigned ACs remain, continue TDD red/green without asking whether to proceed or whether to start R3.
  R3 review is allowed only after `e2e_dev_harness.py ac-progress` is ready for the current service slice or global design.
- Skipped phases are blockers in strict completion. R1/R2/R3 reviews, harness plan state, TDD red/green, completion gate, and strict guard must have machine-readable evidence; do not mark them as skipped in the final report.
- Task drift is a blocker. Changed production files must stay inside declared design/manifest/coverage scope.
  If a change is outside scope, adds undeclared ACs, or changes interface-like files without Impact Summary rows, return to `plan` or `clarify`.
- Every run has `run-state.json` and `artifact-registry.json`; never edit harness control files directly.
  Valid high-phase states need transition history and gate evidence.
- Do not run `prepare` as a substitute for `start`. `prepare` is dependency discovery only; `start` creates the active run, design template, and phase lock.
- Runtime hooks can enforce phase locks before code-writing tools run.
  Use `install_hooks.py`, `phase_guard.py`, and hook examples when the agent runtime supports pre-action checks.
  Claude Code hooks must include `Read/Grep/Glob/Bash` plus `Stop`; read hooks force `start`, stop hooks block ending before R3/completion/guard/archive.
  OpenCode installs `.opencode/plugins/e2e-dev-harness.js` via `install_hooks.py --runtime opencode`.
  If runtime hooks are unavailable, run `e2e_dev_harness.py pre-code --path <planned-code-file> --run-dir docs/agent-runs/<run>` before each code edit.
  Read `references/execution-control.md`.
  After red-test evidence exists, run `e2e_dev_harness.py gate --phase implementation --run-state docs/agent-runs/<run>/run-state.json`;
  a passing gate opens the `IMPLEMENTED` phase automatically.
- Replay a run with `harness_verify.py` or `verify --harness`; emit run summaries for CI, reviewers, evaluation, and later analysis.
- Use `execution_trace.py`, `command_evidence.py`, and `context_pack.py` for timing/decision traces, command proof, and bounded request-scoped agent inputs.
  Use `agent-task --action claim` before any multi-service code agent writes code; phase guard blocks unclaimed service writes and cross-service edits by a single claimed task.
  Claims carry leases; renew long tasks, and reclaim stale ones before completion.
  Use `checkpoint_gate.py` or `gate --checkpoint-mode required` after clarify, R1, and TDD Red on critical or interactive work.
  Agent start/stop is runtime-specific; this harness enforces portable state, hooks, gates, and rework routing instead of claiming non-portable process control.

## Workflow

1. Prepare: load root instructions, scan memory, probe Superpowers, refresh GitNexus-first dependency evidence.
2. Clarify: use Superpowers brainstorming and the Markdown clarification gate; stop on unresolved behavior/API/data/test or impact-summary questions.
3. R1 design review: independent semantic reviewer checks AC completeness, affected modules, security paths, and reference patterns.
4. Plan: choose `single`, explicit `single-review`, or `multi`; write an ExecPlan for complex work. Read `references/exec-plan.md`.
5. Service design split for multi-service: fill and validate every `service-designs/<service>.md`; do not proceed while run-state is `SERVICE_DESIGN_REQUIRED`.
6. TDD red: write the first failing service-local test and capture failing evidence.
7. R2 test review: independent reviewer checks happy/failure paths, security cases, and contract coverage before production code.
8. Dispatch/claim service code tasks: each service code agent claims its `agent-schedule.json` task before writing code; one claimed task edits only its service/module.
9. TDD green/refactor: implement with the Superpowers Red-Green-Refactor cycle for every assigned AC; run the test-impact plan's required Maven commands before broadening verification.
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

```bash
python skills/e2e-dev-harness/scripts/orchestration_plan.py . \
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
- Service code agents consume `service-designs/<service>.md` first, then the service implementation plan and service-local test impact plan; they should not reload the full global design unless the slice is incomplete.
- Before dispatching a service code agent, create `docs/agent-runs/<run>/context-packs/<agent-or-service>.json` from `agent-schedule.json`; do not pass inherited developer chat as context.
- Before a service code agent writes code, claim its task with `e2e_dev_harness.py agent-task --action claim --schedule docs/agent-runs/<run>/agent-schedule.json --task-id <id> --agent <agent> --state docs/agent-runs/<run>/run-state.json`.
- Completion requires each service implement task to be completed with `agent-task --action complete` and an existing evidence file that matches one of the task outputs; the completion gate replays `agent-schedule.json`.
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
It uses a tree-sitter Java AST when `tree_sitter_java` is installed (`java_parser.backend: tree-sitter`).
That drops regex false positives like commented-out or string-literal annotations, and falls back per file to regex otherwise.
The scanner only emits seeds; GitNexus stays the authoritative impact engine.

```bash
python skills/e2e-dev-harness/scripts/cross_service_dependency_scan.py . \
  --gitnexus-mode auto \
  --json
```

For Java/Spring code dependencies, GitNexus is the primary evidence engine. Graphify can enrich design-document and architecture semantics, but inferred or ambiguous Graphify findings become clarification questions, not completion evidence.
If GitNexus/MCP/CLI is unavailable for required evidence, pause for user-approved degradation.
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

Before dispatching phase-specific or service-scoped agents, select only relevant memory:

```bash
python skills/e2e-dev-harness/scripts/memory_capture.py select . \
  --phase code \
  --service services/<service>
```

At completion, process proposed memory updates from the agent run. Promote accepted, approved, or verified entries only after validation.

Final reports should name loaded AGENT files, Superpowers status, graph status, affected services, review artifacts, tests and Maven commands, coverage/rework state, memory decisions, and residual risks.
