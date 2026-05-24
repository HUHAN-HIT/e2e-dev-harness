---
name: e2e-dev-workflow
description: Use when Codex must drive an end-to-end development workflow from project instruction loading, requirements clarification, use-case design, knowledge graph refresh, memory capture, planning, implementation gates, TDD implementation, and verification. Applies to design docs, feature work, bug fixes, refactors, mono-service repos, and multi-service repos; currently tuned for Java.
---

# E2E Dev Workflow

Use this skill to turn a design request into a clarified, tested code change. It is currently tuned for Java. **The governing rule is: do not start implementation while behavior, use cases, APIs, data effects, or test expectations are still ambiguous.**

## Project Instructions Gate

Before any requirement clarification, load project instructions:

```bash
python skills/e2e-dev-workflow/scripts/agent_instructions.py . --mode strict --scope discovery --include-content
```

Load files in this order:

1. Root project `AGENTS.override.md`, `AGENT.override.md`, `AGENT.md`, or `AGENTS.md`.
2. During early clarification, list discovered service AGENT files without loading their contents.
3. After the design identifies affected services, load only AGENT files whose directory scope contains the touched paths and only affected service `AGENT.md` or `AGENTS.md` files.

If affected services are known, pass services or paths so the loader can apply directory scope:

```bash
python skills/e2e-dev-workflow/scripts/agent_instructions.py . --mode strict --scope affected --include-content --service services/<service>
python skills/e2e-dev-workflow/scripts/agent_instructions.py . --mode strict --scope affected --include-content --path services/<service>/src/main/java/...
```

Do not load every service AGENT file just because affected services are unknown. Use `--scope all` only when the task explicitly requires whole-repo service rules. User instructions override `AGENT.md`; deeper AGENT files override broader AGENT files; AGENT files override this skill's defaults.

Use `--include-content` when the command output is the loading mechanism. In discovery scope this includes the root instruction content only; service AGENT files are listed for later scoped loading. Read `references/agent-instructions.md` for strict/optional mode guidance and service discovery rules.

## Unified CLI

Prefer the unified CLI for normal runs. It reduces missed steps by combining AGENT loading, Superpowers probing, memory scanning, orchestration selection, and knowledge graph dry-run:

```bash
python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py prepare . --design-doc docs/design/<feature>.md --agent-mode strict --agent-scope discovery --service-scope discovery --include-agent-content
```

Use focused subcommands when needed:

- `prepare`: pre-clarification/pre-planning discovery.
- `clarify`: machine-check a design document.
- `plan`: choose single/multi-agent mode and optionally write an ExecPlan.
- `gate`: hook-like planning, implementation, and completion gate.
- `verify`: run prepare, clarification, optional gate, and optional Maven.
- `guard`: strict hook/CI guard over a saved verify status artifact.

In `prepare`, `--agent-scope` and `--service-scope` are aligned when only one is explicitly set to `discovery`, `affected`, or `all`. Set both only when you intentionally need different instruction-loading and orchestration scopes.

## Superpowers Adapter

Use Superpowers as the clarification and TDD process provider whenever it is available. For TDD, `superpowers:test-driven-development` is authoritative; this skill only adds Java/Spring 6/Maven-specific test selection and command guidance.

Before any clarification question or implementation action, run:

```bash
python skills/e2e-dev-workflow/scripts/superpowers_probe.py --mode auto
```

If Superpowers is discovered, apply these sub-skills in order:

1. `superpowers:using-superpowers` before responding or choosing process.
2. `superpowers:brainstorming` for design/requirements/use-case clarification. Respect its hard gate: no implementation until the design is presented and approved.
3. `superpowers:writing-plans` after the design is approved and written.
4. `superpowers:test-driven-development` before any production-code change. Follow its iron law: no production code without first watching a failing test fail for the expected reason.

When the runtime exposes Superpowers in the available skill list, invoke those skills normally by name. If the runtime does not expose them but `superpowers_probe.py` returns local `SKILL.md` paths, read those discovered files as a compatibility fallback and follow them directly.

If Superpowers is missing, follow the adapter policy in `references/superpowers-integration.md`. Default behavior is `auto`: use Superpowers when found; otherwise continue with this skill's built-in clarification gate while reporting the missing adapter.

## Agent Orchestration

Default to single-agent mode for small, low-risk changes. Use multi-agent mode when the task is cross-service, high-risk, design-heavy, or the user asks to keep agent contexts small.

Before planning a non-trivial change, run:

```bash
python skills/e2e-dev-workflow/scripts/orchestration_plan.py . --mode auto --service-scope discovery --design-doc docs/design/<feature>.md
```

After clarification identifies affected services, rerun with service scope. If the approved design has an `Affected services/modules` or `Scope` section whose bullets match discovered service candidates, root Maven modules, or service directory names, `--service-scope auto` derives the affected services automatically. Use explicit `--service` or `--path` when the design is still incomplete or the names are ambiguous:

```bash
python skills/e2e-dev-workflow/scripts/orchestration_plan.py . --mode auto --service-scope affected --service services/<service> --design-doc docs/design/<feature>.md
python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py plan . --mode auto --design-doc docs/design/<feature>.md --create-archive
```

The orchestration helper recommends `single` or `multi` mode and names the handoff artifacts under `docs/agent-runs/<date-feature>/` by default. Discovery scope reports available service candidates but does not generate per-service implementation plans from the full `service_candidates` list. Affected scope generates service plans only for explicit `--service`/`--path` matches or for design-declared affected services/modules that match discovered candidates; `--service-scope all` is reserved for whole-repo service work. In multi-agent mode, split work into:

Discovery scope is intentionally lightweight: it returns a service inventory summary, next steps, and no agent plan or handoff artifact map. Create ExecPlans, agent-run archives, and service-scoped code agents only after the design names affected services/modules, after rerunning with `--service-scope affected`, or with explicit `--service-scope all`.

- Requirements Clarifier: owns requirements, non-goals, acceptance criteria, and open questions.
- Use Case Designer: owns happy paths, failure paths, cross-service flows, data effects, and contracts.
- Test Case Developer: owns test strategy, first red tests, contract tests, and Maven test scope using `superpowers:test-driven-development`.
- Code Developer: owns implementation after approved requirements, use cases, test plan, and failing tests exist. For multi-service work, split Code Developer into one service-scoped agent per affected service/module.
- Coverage Reviewer: owns the implementation manifest, design-to-code coverage matrix, unit-test evidence check, and business logic review before completion.

Use files as handoff boundaries. Do not rely on chat memory for cross-agent transfer. Keep process files in `docs/agent-runs/`; keep durable human-facing design in `docs/design/`. For multi-service or multi-module changes, keep each service/module implementation plan under `docs/agent-runs/<date-feature>/service-plans/<service>/` so similar service logic does not bleed across agent contexts. Read `references/agent-orchestration.md` for mode selection and role contracts, and `references/agent-handoff-schema.md` for the handoff file schema.

## Memory Adapter

Use repository memory to preserve verified project knowledge across tasks without bloating every agent context.

Before planning, run:

```bash
python skills/e2e-dev-workflow/scripts/memory_capture.py scan .
python skills/e2e-dev-workflow/scripts/memory_capture.py validate .
```

If the repo has no memory files yet, initialize them:

```bash
python skills/e2e-dev-workflow/scripts/memory_capture.py init .
```

Before dispatching a phase-specific or service-scoped agent, select only relevant memory:

```bash
python skills/e2e-dev-workflow/scripts/memory_capture.py select . --phase code --service services/<service>
```

Memory has two layers:

- `memory/*.md`: durable project memory that can be reviewed and committed.
- `graphify-out/memory/`: Graphify local feedback-loop memory, usually generated and local.

Only write verified or user-approved facts. Use controlled Obsidian tags such as `#service/<service>` and links such as `[[services/<service>]]` to make memory selectable and graphable, but never let tags/links replace the verified text. Never let memory override current code, tests, or freshly refreshed knowledge graphs. Read `references/memory-integration.md` for capture rules.

Memory validation is a hard hygiene gate: it blocks unresolved TODO/TBD markers, local absolute paths, likely secrets, empty entry text, exact duplicate memory facts, invalid Obsidian tags/links, and proposed updates that duplicate existing durable memory. Fuzzy duplicates are returned as warnings so the agent can merge or reject them before promotion.

At completion, process proposed memory updates from the agent run. Accepted, approved, or verified entries can be promoted; rejected, deferred, or skipped entries are treated as handled but not written:

```bash
python skills/e2e-dev-workflow/scripts/memory_capture.py promote . --from-file docs/agent-runs/<run>/proposed-memory-updates.md
```

## ExecPlans

For complex features, cross-service changes, migrations, or long-running refactors, write an ExecPlan after clarification and before implementation:

```bash
python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py plan . --design-doc docs/design/<feature>.md --create-archive
```

Keep the ExecPlan current as a living document. Read `references/exec-plan.md` for required sections.

## Workflow

1. Prepare: run the unified `prepare` command; load AGENT content before asking clarification questions; refresh GitNexus-first cross-service dependency evidence.
2. Clarify: use Superpowers brainstorming plus the Markdown clarification gate; stop while behavior/API/data/test-impacting questions remain unresolved.
3. Plan: design use cases, choose single/multi-agent mode, and write an ExecPlan for complex work.
4. TDD implement: invoke or load `superpowers:test-driven-development`, capture red-test evidence, implement with Red-Green-Refactor.
5. Completion gate: prove every acceptance criterion and every required implementation artifact is covered by use cases, service plans, tests, code refs, business review evidence, and closed rework items.
6. Rework loop: when coverage review, tests, business review, or user review finds missed behavior, create a rework item and return to the earliest required phase before more production-code edits.
7. Strict guard and report: run narrow then broadened Maven tests, run `verify --strict-workflow` or `guard`, capture approved memory updates, and report loaded AGENT files, graph status, tests, commands, coverage, rework status, and residual risks.

## Knowledge Graph Choice

Prefer GitNexus for Java/Spring 6/Maven code understanding: package structure, call paths, dependency impact, constants, HTTP client flow, producer/consumer flow, and code-centric graphs. For cross-service dependencies, GitNexus is the primary evidence engine.

Add Graphify when the task depends on design documents, diagrams, screenshots, PDFs, architecture notes, or broad project visualization. Graphify findings that are inferred or ambiguous become clarification questions; they do not replace GitNexus/code evidence for completion.

Use the deterministic cross-service scanner to extract structured HTTP/DMQ seeds before querying GitNexus. It scans Spring routes, configured URLs, `@Value`, `Environment.getProperty`, RestTemplate/WebClient-style call paths, DMQ producer/listener annotations, topic constants, tags, groups, and payload hints:

```bash
python skills/e2e-dev-workflow/scripts/cross_service_dependency_scan.py . --gitnexus-mode auto --json
```

Reports are written to `knowledge-graph/cross-service-dependencies.json` and `.md` by default. During `prepare`, the unified CLI runs this scan unless `--dependency-scan-mode off` is supplied. When a dependency report has unresolved URL/topic/tag/service questions, move them into clarification before planning implementation.

Use both GitNexus and Graphify when the repo is multi-service and the change is driven by docs or architecture decisions. If only one tool is installed, use that tool and compensate with `rg`, Maven module inspection, and focused code reads.

Read `references/kg-tool-selection.md` for the full decision matrix.

## Clarification Gate

When Superpowers is available, `superpowers:brainstorming` is the primary clarification gate. This built-in gate is the fallback and a machine-checkable quality bar for Markdown design notes.

Before implementation, produce or update a short design note with:

- Goal and non-goals
- In-scope services/modules
- Use cases and failure paths
- API/message/data contract changes
- Acceptance criteria
- Test design
- Open questions

Open questions must be explicitly marked as none or individually resolved/confirmed before production-code implementation. Use `scripts/clarification_gate.py <design-doc>` or the unified `clarify` command when a Markdown design note exists. Read `references/clarification-gate.md` for gate details.

## Implementation Gates

Use hook-like gates to keep lifecycle requirements enforceable:

```bash
python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py gate . --phase planning --design-doc docs/design/<feature>.md
python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py gate . --phase implementation --design-doc docs/design/<feature>.md --red-test-evidence docs/design/<feature>-red-test.txt
python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py gate . --phase completion --design-doc docs/design/<feature>.md --red-test-evidence docs/agent-runs/<run>/evidence/red-test.txt --implementation-manifest docs/agent-runs/<run>/evidence/implementation-manifest.md --coverage-matrix docs/agent-runs/<run>/evidence/coverage-matrix.md --unit-test-evidence docs/agent-runs/<run>/evidence/green-test.txt --business-review docs/agent-runs/<run>/evidence/business-review.md --dependency-report docs/agent-runs/<run>/evidence/cross-service-dependencies.json --memory-updates docs/agent-runs/<run>/proposed-memory-updates.md --rework-dir docs/agent-runs/<run>/rework
```

Planning gate checks clarification readiness and knowledge graph status. Implementation gate additionally requires red-test evidence. Completion gate requires `--design-doc`, non-empty red-test evidence, unit-test command evidence, business review evidence, and a coverage matrix that maps every acceptance criterion to use cases, service/module ownership, tests, code refs, and covered/verified status. For multi-module or artifact-heavy designs, completion also requires an implementation manifest at `docs/agent-runs/<run>/evidence/implementation-manifest.md`. The manifest table must include `id`, `module`, `artifact`, `artifact_type`, `source`, `required`, `tests`, `status`, and `evidence`; required rows must point to existing artifacts, real tests, and implemented/verified status. Build it from explicit task requirements, reference implementation patterns, dependency reports, and service plans before coding. This catches cases where the coverage matrix only proves self-selected ACs while required files or modules were skipped. If the design is cross-service, completion also requires `--dependency-report`; any unresolved URL/topic/tag/service mapping question blocks completion. Unit-test evidence must be structured JSON with `command` and integer `exit_code`; text that merely says PASS is not accepted. The coverage gate extracts acceptance IDs from the design doc; unnumbered acceptance bullets are treated as `AC-1`, `AC-2`, and so on, and every extracted AC must appear in the matrix `id` column. When `--memory-updates` is supplied, completion also blocks unhandled proposed memory updates; mark each one accepted, rejected, deferred, or skipped. Completion also scans inferred or explicit rework items and blocks while any item is `open`, `in-progress`, `blocked`, or `deferred` without `Approval: user-approved`. Completion also runs `spring_static_check.py` by default to catch repository-local constructor-injected types that are not Spring components or `@Bean`s; use `--skip-spring-static-check` only for non-Spring or exceptional cases.

## Strict Workflow Guard

Use the workflow guard when the requirement is "do not let the model skip scripts." It verifies the saved `verify` result instead of trusting chat claims:

```bash
python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py verify . --strict-workflow --run-gate --phase completion --design-doc docs/design/<feature>.md --red-test-evidence docs/agent-runs/<run>/evidence/red-test.txt --implementation-manifest docs/agent-runs/<run>/evidence/implementation-manifest.md --coverage-matrix docs/agent-runs/<run>/evidence/coverage-matrix.md --unit-test-evidence docs/agent-runs/<run>/evidence/green-test.txt --business-review docs/agent-runs/<run>/evidence/business-review.md --dependency-report docs/agent-runs/<run>/evidence/cross-service-dependencies.json --memory-updates docs/agent-runs/<run>/proposed-memory-updates.md --rework-dir docs/agent-runs/<run>/rework --status-file docs/agent-runs/<run>/evidence/verify.json
python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py guard . --verify-status docs/agent-runs/<run>/evidence/verify.json --strict --require-completion
```

Strict guard blocks missing `prepare`, disabled dependency scan, disabled dependency report writing, skipped Maven, skipped Spring static check during completion, missing clarification status, missing completion gate, failed completion gate, failed Maven, and unresolved dependency questions. A skip can pass only with an explicit approval file containing `Approval: user-approved`.

## Rework Loop

Do not directly patch production code when missed requirements, missing tests, test failures, multi-service contract gaps, or business logic risks are found after implementation. Write `docs/agent-runs/<run>/rework/rework-NNN.md` for global issues or `docs/agent-runs/<run>/service-plans/<service>/rework-NNN.md` for service-local issues, then route the item to the earliest required phase: unclear requirements and missing acceptance criteria return to `clarify`; missing use cases and business logic risks return to `use-case-design`; missing tests return to `test-case-design`; missing code and test failures return to `tdd-implement`; multi-service contract issues return to `plan`.

Each rework item must include `Source`, `Related AC`, `Affected Services`, `Problem Type`, `Return Phase`, `Required Red Test`, `Evidence`, `Exit Criteria`, and `Status`. Only `Status: verified` or `Status: deferred` with explicit approval can pass completion. Rework implementation still follows `superpowers:test-driven-development`: add or update the red test, observe the expected failure, implement minimally, rerun verification, then close the rework item.

## TDD Rules

`superpowers:test-driven-development` is the primary TDD method. Do not replace or soften it with local rules.

Use this skill's Java/Spring guidance only as an addendum:

- Prefer pure JUnit tests for domain rules and application-service tests for orchestration.
- Add Spring MVC/Data/integration tests only when framework behavior, serialization, validation, transactions, or repository wiring is the risk.
- Keep each Superpowers red test small enough that it explains the next implementation step.
- Run the narrow Maven test command for each red/green cycle, then broaden verification.
- Capture green test evidence as JSON: `{"command":"mvn -pl services/<service> -am test","exit_code":0,"stdout_tail":"...","stderr_tail":""}`.

Read `references/tdd-java-spring.md` for the Java/Spring/Maven addendum to Superpowers TDD.

## Useful Commands

Run from the repo root, adapting module paths as needed:

```bash
python skills/e2e-dev-workflow/scripts/agent_instructions.py . --mode strict --scope discovery --include-content
python skills/e2e-dev-workflow/scripts/agent_instructions.py . --mode strict --scope affected --include-content --service services/<service>
python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py prepare . --design-doc docs/design/<feature>.md --agent-mode strict --agent-scope discovery --service-scope discovery --include-agent-content
python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py prepare . --design-doc docs/design/<feature>.md --agent-mode strict --agent-scope affected --service-scope affected --service services/<service> --include-agent-content
python skills/e2e-dev-workflow/scripts/superpowers_probe.py --mode auto
python skills/e2e-dev-workflow/scripts/superpowers_probe.py --mode strict --phase implementation
python skills/e2e-dev-workflow/scripts/orchestration_plan.py . --mode auto --service-scope discovery --design-doc docs/design/<feature>.md
python skills/e2e-dev-workflow/scripts/orchestration_plan.py . --mode auto --service-scope affected --service services/<service> --design-doc docs/design/<feature>.md
python skills/e2e-dev-workflow/scripts/memory_capture.py scan .
python skills/e2e-dev-workflow/scripts/memory_capture.py validate .
python skills/e2e-dev-workflow/scripts/memory_capture.py select . --phase code --service services/<service>
python skills/e2e-dev-workflow/scripts/memory_capture.py promote . --from-file docs/agent-runs/<run>/proposed-memory-updates.md --dry-run
python skills/e2e-dev-workflow/scripts/kg_refresh.py .
python skills/e2e-dev-workflow/scripts/cross_service_dependency_scan.py . --gitnexus-mode auto --json
python skills/e2e-dev-workflow/scripts/clarification_gate.py docs/design/<feature>.md
python skills/e2e-dev-workflow/scripts/implementation_manifest.py . --manifest docs/agent-runs/<run>/evidence/implementation-manifest.md --design-doc docs/design/<feature>.md
python skills/e2e-dev-workflow/scripts/coverage_gate.py . --design-doc docs/design/<feature>.md --coverage-matrix docs/agent-runs/<run>/evidence/coverage-matrix.md --unit-test-evidence docs/agent-runs/<run>/evidence/green-test.txt --business-review docs/agent-runs/<run>/evidence/business-review.md
python skills/e2e-dev-workflow/scripts/spring_static_check.py . --json
python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py verify . --design-doc docs/design/<feature>.md --skip-maven
python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py guard . --verify-status docs/agent-runs/<run>/evidence/verify.json --strict --require-completion
mvn -pl services/<service> -am test
mvn test
```

If the skill is installed globally or copied under `.agents/skills`, resolve script paths from that skill directory.
