---
name: java-spring-tdd-kg
description: Analyze and implement Java 21 Spring Framework 6.x Maven changes with mandatory project/microservice AGENT instruction loading before clarification, pluggable Superpowers-based clarification, optional multi-agent orchestration, memory capture, use-case design, knowledge graph refresh, and TDD. Use for Spring 6 services, Maven monorepos, multi-service repos, design documents, feature work, bug fixes, refactors, or any code change where Codex must clarify requirements before implementation.
---

# Java Spring TDD KG

Use this skill to turn a design request into a clarified, tested Java/Spring Framework 6.x/Maven change. The governing rule is: do not start implementation while behavior, use cases, APIs, data effects, or test expectations are still ambiguous.

## Project Instructions Gate

Before any requirement clarification, load project instructions:

```bash
python skills/java-spring-tdd-kg/scripts/agent_instructions.py . --mode strict --include-content
```

Load files in this order:

1. Root project `AGENT.md` or `AGENTS.md`.
2. `AGENT.md` or `AGENTS.md` for every affected microservice directory under the project, usually `services/<service>/`.

If affected services are not known yet, load all discovered service instruction files before asking clarification questions. User instructions override `AGENT.md`; `AGENT.md` overrides this skill's defaults.

Use `--include-content` when the command output is the loading mechanism. For large repos, run the scan first, then open only the root and affected service instruction files from `load_order`. Read `references/agent-instructions.md` for strict/optional mode guidance and service discovery rules.

## Superpowers Adapter

Use Superpowers as the clarification and TDD process provider whenever it is available. For TDD, `superpowers:test-driven-development` is authoritative; this skill only adds Java/Spring 6/Maven-specific test selection and command guidance.

Before any clarification question or implementation action, run:

```bash
python skills/java-spring-tdd-kg/scripts/superpowers_probe.py --mode auto
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
python skills/java-spring-tdd-kg/scripts/orchestration_plan.py . --mode auto --design-doc docs/design/<feature>.md
```

The orchestration helper recommends `single` or `multi` mode and names the handoff artifacts. In multi-agent mode, split work into:

- Requirements Clarifier: owns requirements, non-goals, acceptance criteria, and open questions.
- Use Case Designer: owns happy paths, failure paths, cross-service flows, data effects, and contracts.
- Test Case Developer: owns test strategy, first red tests, contract tests, and Maven test scope using `superpowers:test-driven-development`.
- Code Developer: owns implementation after approved requirements, use cases, test plan, and failing tests exist.

Use files as handoff boundaries. Do not rely on chat memory for cross-agent transfer. Read `references/agent-orchestration.md` for mode selection and role contracts.

## Memory Adapter

Use repository memory to preserve verified project knowledge across tasks without bloating every agent context.

Before planning, run:

```bash
python skills/java-spring-tdd-kg/scripts/memory_capture.py scan .
```

If the repo has no memory files yet, initialize them:

```bash
python skills/java-spring-tdd-kg/scripts/memory_capture.py init .
```

Memory has two layers:

- `memory/*.md`: durable project memory that can be reviewed and committed.
- `graphify-out/memory/`: Graphify local feedback-loop memory, usually generated and local.

Only write verified or user-approved facts. Never let memory override current code, tests, or freshly refreshed knowledge graphs. Read `references/memory-integration.md` for capture rules.

## Workflow

1. Load root and microservice `AGENT.md`/`AGENTS.md` instructions before requirement clarification.
2. Resolve the Superpowers adapter. Apply Superpowers sub-skills if discovered.
3. Choose single-agent or multi-agent orchestration. Use multi-agent mode only when authorized by user request, explicit mode, or task risk.
4. Scan project memory. Use it as context hints, not as truth over code or tests.
5. Read the design document, issue, or request. Extract goal, non-goals, actors, service boundaries, domain terms, invariants, API/message contracts, acceptance criteria, and risks.
6. Refresh the repository knowledge graph before planning code changes. Run `scripts/kg_refresh.py <repo>` in dry-run mode first, then use the selected Graphify/GitNexus commands if available and approved by the repo workflow.
7. Apply the clarification gate. If unresolved questions affect behavior, data, APIs, integration contracts, or tests, ask concise questions and stop before production-code edits.
8. Design the use cases. Name happy paths, failure paths, authorization/validation rules, data changes, cross-service effects, and observable outputs.
9. Invoke or load `superpowers:test-driven-development`, then write the TDD plan. Pick the smallest red test that proves the next behavior, usually a domain/unit test before a Spring MVC/integration test.
10. Implement through the Superpowers Red-Green-Refactor cycle. Keep controllers thin, put orchestration in application services, keep business rules testable without Spring when practical, and use Java 21 language features conservatively.
11. Verify with the narrow Maven command first, then broaden to the affected module set. For multi-service changes, test every touched service and any contract/shared module.
12. Capture durable memory updates only for user-approved decisions, verified graph findings, service-boundary facts, or workflow preferences.
13. Report: loaded AGENT files, orchestration mode, Superpowers adapter status, memory status, clarified assumptions, graph refresh result, tests added/changed, commands run, and any residual risks.

## Knowledge Graph Choice

Prefer GitNexus for Java/Spring 6/Maven code understanding: package structure, call paths, dependency impact, and code-centric graphs.

Add Graphify when the task depends on design documents, diagrams, screenshots, PDFs, architecture notes, or broad project visualization.

Use both when the repo is multi-service and the change is driven by docs or architecture decisions. If only one tool is installed, use that tool and compensate with `rg`, Maven module inspection, and focused code reads.

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

Open questions must be empty or explicitly marked as none before production-code implementation. Use `scripts/clarification_gate.py <design-doc>` when a Markdown design note exists. Read `references/clarification-gate.md` for gate details.

## TDD Rules

`superpowers:test-driven-development` is the primary TDD method. Do not replace or soften it with local rules.

Use this skill's Java/Spring guidance only as an addendum:

- Prefer pure JUnit tests for domain rules and application-service tests for orchestration.
- Add Spring MVC/Data/integration tests only when framework behavior, serialization, validation, transactions, or repository wiring is the risk.
- Keep each Superpowers red test small enough that it explains the next implementation step.
- Run the narrow Maven test command for each red/green cycle, then broaden verification.

Read `references/tdd-java-spring.md` for the Java/Spring/Maven addendum to Superpowers TDD.

## Useful Commands

Run from the repo root, adapting module paths as needed:

```bash
python skills/java-spring-tdd-kg/scripts/agent_instructions.py . --mode strict --include-content
python skills/java-spring-tdd-kg/scripts/superpowers_probe.py --mode auto
python skills/java-spring-tdd-kg/scripts/superpowers_probe.py --mode strict --phase implementation
python skills/java-spring-tdd-kg/scripts/orchestration_plan.py . --mode auto --design-doc docs/design/<feature>.md
python skills/java-spring-tdd-kg/scripts/memory_capture.py scan .
python skills/java-spring-tdd-kg/scripts/kg_refresh.py .
python skills/java-spring-tdd-kg/scripts/clarification_gate.py docs/design/<feature>.md
mvn -pl services/<service> -am test
mvn test
```

If the skill is installed globally or copied under `.agents/skills`, resolve script paths from that skill directory.
